"""
mail_reply.py — "Svara på mejlet" från en uppgiftskort.

Bygger ett färdigt svar (till, ämne, citerad text) från originalmailet och öppnar det i
användarens STANDARD-mailprogram via en ``mailto:``-länk (Thunderbird om det är standard).

Begränsning (ärligt): en mailto-länk kan inte bära In-Reply-To/References, så svaret
hamnar inte i samma TRÅD i Thunderbird. Ämnet får "Re: ", och originalet citeras.

Ren logik (ingen Qt) så att den kan testas.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger("Ledgebord")

QUOTE_MAX_CHARS = 1200
MAILTO_MAX_CHARS = 1900   # Windows ShellExecute klarar ~2000 tecken
_RE_PREFIXES = ("re:", "sv:", "vs:", "aw:", "antw:")


def _read_eml(path: Optional[Path]) -> Dict[str, str]:
    """Läs Reply-To/From/Subject/Date/text ur .eml-filen. Tom dict om den inte går att läsa."""
    if path is None:
        return {}
    try:
        msg = email.message_from_bytes(Path(path).read_bytes(), policy=email.policy.default)
        body = ""
        part = msg.get_body(preferencelist=("plain",))
        if part is not None:
            body = part.get_content()
        return {
            "reply_to": str(msg.get("Reply-To") or ""),
            "from": str(msg.get("From") or ""),
            "subject": str(msg.get("Subject") or ""),
            "date": str(msg.get("Date") or ""),
            "body": str(body or ""),
        }
    except Exception as e:
        logger.info(f"[MAILREPLY] kunde inte läsa {path}: {e}")
        return {}


def _first_address(header: str) -> str:
    """Första giltiga adressen ur ett From/Reply-To-huvud ('Anna <a@b.se>' → 'a@b.se')."""
    for _name, addr in email.utils.getaddresses([header or ""]):
        addr = addr.strip()
        if "@" in addr and " " not in addr:
            return addr
    return ""


def reply_subject(subject: str) -> str:
    s = " ".join(str(subject or "").split())
    if not s:
        return "Re:"
    if s.lower().startswith(_RE_PREFIXES):
        return s
    return "Re: " + s


def quote_text(body: str, who: str, date: str) -> str:
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(body) > QUOTE_MAX_CHARS:
        body = body[:QUOTE_MAX_CHARS].rstrip() + "\n[…]"
    lines = [("> " + ln) if ln.strip() else ">" for ln in body.split("\n")] if body else []
    head = ""
    if who or date:
        head = f"Den {date} skrev {who}:" if date else f"{who} skrev:"
    return "\n".join(x for x in (head, "\n".join(lines)) if x)


def reply_info(task: Dict[str, Any], eml_file: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """
    {'to','subject','body'} för ett svar, eller None om ingen mottagare kan hittas.
    Reply-To i originalet vinner över From.
    """
    eml = _read_eml(eml_file)
    to = (
        _first_address(eml.get("reply_to", ""))
        or _first_address(eml.get("from", ""))
        or _first_address(str(task.get("email_from") or ""))
    )
    if not to:
        return None
    subject = eml.get("subject") or str(task.get("email_subject") or "") or str(task.get("title") or "")
    who = eml.get("from") or str(task.get("email_from") or "")
    date = eml.get("date") or str(task.get("email_date") or "")
    body = eml.get("body") or str(task.get("email_body") or "")
    quoted = quote_text(body, who, date)
    return {
        "to": to,
        "subject": reply_subject(subject),
        "body": ("\n\n" + quoted) if quoted else "",
    }


def build_mailto(info: Dict[str, str], max_chars: int = MAILTO_MAX_CHARS) -> str:
    """mailto:-länk med procent-kodning. Citatet kortas tills hela länken ryms."""
    def make(body: str) -> str:
        return (
            "mailto:" + quote(info["to"], safe="@,")
            + "?subject=" + quote(info["subject"], safe="")
            + "&body=" + quote(body.replace("\r\n", "\n").replace("\n", "\r\n"), safe="")
        )

    body = info.get("body", "")
    url = make(body)
    while len(url) > max_chars and body:
        body = body[: max(0, int(len(body) * 0.8) - 1)].rstrip()
        if len(body) < 20:
            body = ""
        elif not body.endswith("[…]"):
            body += "\n[…]"
        url = make(body)
    return url


def open_mailto(url: str) -> bool:
    """Öppna länken i standardmailprogrammet. True om försöket gjordes utan fel."""
    try:
        if sys.platform.startswith("win") and hasattr(os, "startfile"):
            os.startfile(url)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return True
    except Exception as e:
        logger.warning(f"[MAILREPLY] kunde inte öppna mailprogrammet: {e}")
        try:
            return bool(webbrowser.open(url))
        except Exception:
            return False
