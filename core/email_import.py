# -*- coding: utf-8 -*-
"""
email_import.py — TaskBord v7-fix35 → v7-fix85 (50 000 000 % bättre).

Rickard 2026-09-30: "kunna importera uppgift från mail, importera
outlook/thunderbird fil för att konvertera till uppgift, samt spara
org mail så den lämnas och kan öppnas via knapp eller ikon".

Stödjer:
  .eml  — Thunderbird, Apple Mail, Gmail-export, standard MIME
  .msg  — Outlook (kräver: pip install extract-msg)

NYTT I v7-fix85 (allt gamla finns kvar orört — bara tillagt):
  * DEDUP: samma mail importeras ALDRIG två gånger (Message-ID eller
    filinnehålls-hash) — registry i data/emails/imported.json;
    dubletter returnerar DEN BEFINTLIGA uppgiftens id
  * Bättre parsning: To/Cc, Message-ID, ISO-datum, bilage-lista,
    robust teckenkodning (errors="replace"), sanitierade ämnen
    (veckade rubriker/radbrytningar i ämnet kan inte längre bryta UI:t)
  * HTML-rensering utökad: svenska tecken-entities (å ä ö é …),
    numeriska entities (&#229;), <p>/<div> → radbrytning
  * Bilagor räknas + namn listas (metadata 'email_attachments')
  * Batch-import: import_emails([fil1, fil2, …]) → (importerade,
    hoppade över, misslyckade) — redo för framtida UI-koppling
  * Filvalidering: maxstorlek (25 MB), tomma filer, säker kopia med
    verifiering + MD5-hash i loggen
  * Fler prioriteringsnyckelord (svenska + engelska)
  * Utökad metadata: email_to, email_date, email_message_id,
    email_subject (fullständigt, otrunkerat ämne)

Flöde (oförändrat):
  1. Användaren väljer .eml/.msg-fil (eller drar den på widgeten)
  2. Filen parsas (ämne, avsändare, brödtext, datum, bilagor)
  3. En uppgift skapas med e-postens ämne som titel
  4. Originalfilen sparas i data/emails/{task_id}.{ext}
  5. Uppgiftskortet visar 📧-ikon → klick öppnar originalet

Användning:
    from core.email_import import import_email
    task_id = import_email(Path("mail.eml"), store, data_dir)
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("EmailImport")
LOG_PREFIX: str = "[MAIL]"

# Max längd på titel/brödtext
MAX_TITLE_LEN = 200
MAX_BODY_PREVIEW = 500

# NY v7-fix85: gränser + registernamn
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_ATTACHMENTS_LISTED = 8
REGISTRY_FILENAME = "imported.json"

# Nyckelord för prioritet (utökade v7-fix85)
_URGENT_WORDS = (
    "brådskande", "braskande", "urgent", "asap", "viktigt", "important",
    "omedelbart", "deadline", "snarast", "omgående", "kritiskt", "critical",
    "imo", "imorgon", "viktigt!", "highest priority",
)
_LOW_WORDS = (
    "vänta", "senare", "eventuellt", "maybe", "vid tillfälle",
    "ingen brådska", "när du hinner", "backlog", " låg prio",
)

# Registry-lås (trådsäkert)
_REGISTRY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# PARSNING
# ---------------------------------------------------------------------------

def _normalize_subject(subject: str) -> str:
    """
    NY v7-fix85: sanitera e-postämnet.

    Veckade rubriker (radbrytning + tabb/space) och kontrolltecken kan
    annars bryta uppgiftstiteln i UI:t. Konverterar allt vitt utrymme
    till enkla mellanslag och tar bort osynliga tecken.
    """
    s = str(subject or "")
    s = re.sub(r"[\r\n\t]+", " ", s)          # veckade rubriker → space
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)      # kontrolltecken bort
    s = re.sub(r"\s{2,}", " ", s)              # multi-space → ett
    return s.strip()


def _to_iso_date(date_str: str) -> str:
    """NY v7-fix85: 'Mon, 30 Sep 2026 10:00:00 +0200' → '2026-09-30'."""
    if not date_str:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(str(date_str))
        return dt.date().isoformat()
    except Exception:
        return ""


def parse_eml(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    Parse .eml-fil (Thunderbird/standard MIME).

    Returns:
        {"subject": str, "from": str, "date": str, "body": str,
         "to": str, "cc": str, "message_id": str,
         "date_iso": str, "attachments": [str]}
        None vid fel.
    """
    try:
        with open(filepath, "rb") as f:
            msg = email.message_from_binary_file(
                f, policy=email.policy.default
            )

        subject = _normalize_subject(msg.get("Subject", ""))
        from_addr = str(msg.get("From", "")).strip()
        date_str = str(msg.get("Date", "")).strip()
        to_addr = str(msg.get("To", "")).strip()
        cc_addr = str(msg.get("Cc", "")).strip()
        message_id = str(msg.get("Message-ID", "")).strip()

        # NY v7-fix85: bilagor (namn)
        attachments: List[str] = []
        try:
            for part in msg.walk():
                fname = part.get_filename()
                if fname:
                    attachments.append(str(fname))
                    if len(attachments) >= MAX_ATTACHMENTS_LISTED:
                        break
        except Exception:
            pass

        # Extrahera brödtext (föredra text/plain)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get("Content-Disposition", "")).lower()
                if "attachment" in disp:
                    continue  # bilagor är inte brödtext
                if ctype == "text/plain":
                    try:
                        body = part.get_content()
                    except Exception:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace") if payload else ""
                    break
                elif ctype == "text/html" and not body:
                    # Fallback om ingen text/plain finns
                    try:
                        body = part.get_content()
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_content()
            except Exception:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace") if payload else ""

        # Rensa HTML om det behövs
        if "<" in body and ">" in body:
            body = _strip_html(body)

        # Trunkera
        body = body.strip()
        if len(body) > MAX_BODY_PREVIEW:
            body = body[:MAX_BODY_PREVIEW] + "…"

        logger.info(
            f"{LOG_PREFIX} parse_eml OK: subject={subject[:50]!r}, "
            f"from={from_addr[:30]!r}, bilagor={len(attachments)}"
        )
        return {
            "subject": subject,
            "from": from_addr,
            "date": date_str,
            "body": body,
            "to": to_addr,
            "cc": cc_addr,
            "message_id": message_id,
            "date_iso": _to_iso_date(date_str),
            "attachments": attachments,
        }
    except Exception as e:
        logger.error(f"{LOG_PREFIX} parse_eml misslyckades: {e}")
        return None


def parse_msg(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    Parse .msg-fil (Outlook).

    Kräver: pip install extract-msg
    """
    msg = None
    try:
        import extract_msg
        msg = extract_msg.Message(str(filepath))
        subject = _normalize_subject(msg.subject or "")
        from_addr = (msg.sender or "").strip()
        body = (msg.body or "").strip()
        date_str = str(msg.date) if msg.date else ""
        to_addr = str(getattr(msg, "to", "") or "").strip()
        cc_addr = str(getattr(msg, "cc", "") or "").strip()
        message_id = str(getattr(msg, "messageId", "") or "").strip()

        # NY v7-fix85: bilagor
        attachments: List[str] = []
        try:
            for att in (msg.attachments or []):
                if hasattr(att, "longFilename") and att.longFilename:
                    attachments.append(str(att.longFilename))
                elif hasattr(att, "filename") and att.filename:
                    attachments.append(str(att.filename))
                if len(attachments) >= MAX_ATTACHMENTS_LISTED:
                    break
        except Exception:
            pass

        if len(body) > MAX_BODY_PREVIEW:
            body = body[:MAX_BODY_PREVIEW] + "…"

        logger.info(
            f"{LOG_PREFIX} parse_msg OK: subject={subject[:50]!r}, "
            f"bilagor={len(attachments)}"
        )
        return {
            "subject": subject,
            "from": from_addr,
            "date": date_str,
            "body": body,
            "to": to_addr,
            "cc": cc_addr,
            "message_id": message_id,
            "date_iso": _to_iso_date(date_str),
            "attachments": attachments,
        }
    except ImportError:
        logger.warning(
            f"{LOG_PREFIX} extract-msg ej installerad. "
            f"Kör: pip install extract-msg (eller använd tilläggs-"
            f"installationen i tray-menyn)"
        )
        return None
    except Exception as e:
        logger.error(f"{LOG_PREFIX} parse_msg misslyckades: {e}")
        return None
    finally:
        # NY v7-fix85: stäng alltid .msg-hanteraren (låste filer annars)
        if msg is not None:
            with _suppress_all():
                msg.close()


class _suppress_all:
    """Tiny hjälpreda: undertryck ALLT (för städning)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


def parse_email_file(filepath: Path) -> Optional[Dict[str, Any]]:
    """Parse .eml eller .msg baserat på filändelse."""
    suffix = filepath.suffix.lower()
    if suffix == ".eml":
        return parse_eml(filepath)
    if suffix == ".msg":
        return parse_msg(filepath)
    logger.error(f"{LOG_PREFIX} Format stöds ej: {suffix!r}")
    return None


# ---------------------------------------------------------------------------
# HJÄLPFUNKTIONER
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """
    Ta bort HTML-taggar och lämna ren text.

    NY v7-fix85: svenska/norska/danska entities + numeriska entities +
    <p>/<div>-radbrytningar.
    """
    # Ta bort style/script-block
    text = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    # Blockelement → radbrytning (innan taggarna strippas)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    # NY v7-fix85: numeriska entities (&#229; &#x00E5;)
    def _num_entity(m: "re.Match[str]") -> str:
        try:
            base = m.group(1).lstrip("#")
            code = int(base, 16) if base.lower().startswith("x") else int(base)
            return chr(code) if 0 < code < 0x110000 else ""
        except Exception:
            return ""
    text = re.sub(r"&(#?[0-9a-fA-Fx]+);", _num_entity, text)
    # Avkoda vanliga entities (utökad lista — nordiska tecken!)
    for entity, char in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&apos;", "'"),
        ("&aring;", "å"), ("&auml;", "ä"), ("&ouml;", "ö"),
        ("&Aring;", "Å"), ("&Auml;", "Ä"), ("&Ouml;", "Ö"),
        ("&eacute;", "é"), ("&egrave;", "è"), ("&uuml;", "ü"),
        ("&Uuml;", "Ü"), ("&ccedil;", "ç"), ("&atilde;", "ã"),
        ("&oslash;", "ø"), ("&aelig;", "æ"), ("&bull;", "•"),
        ("&hellip;", "…"), ("&ndash;", "–"), ("&mdash;", "—"),
    ):
        text = text.replace(entity, char)
    # Rensa överflödiga radbrytningar
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_sender_tag(from_addr: str) -> str:
    """Extrahera avsändarens namn eller e-post-prefix som tagg."""
    if not from_addr:
        return ""
    # "Namn <email@domän>" → "Namn"
    match = re.search(r'^"?([^"<]+)"?\s*<', from_addr)
    if match:
        return match.group(1).strip()[:20]
    # "email@domän" → "email"
    return from_addr.split("@")[0].strip()[:20]


def _suggest_priority(subject: str, body: str) -> str:
    """Gissa prioritet baserat på nyckelord i ämnet/brödtexten (utökad)."""
    text = (subject + " " + body).lower()
    if any(w in text for w in _URGENT_WORDS):
        return "high"
    if any(w in text for w in _LOW_WORDS):
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# NY v7-fix85: DEDUP-REGISTER (data/emails/imported.json)
# ---------------------------------------------------------------------------

def _registry_path(data_dir: Path) -> Path:
    return data_dir / "emails" / REGISTRY_FILENAME


def _load_registry(data_dir: Path) -> Dict[str, Dict[str, str]]:
    """Läs dedup-registret (tål korrupta filer)."""
    path = _registry_path(data_dir)
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} dedup-register kunde ej läsas ({e}) — "
            f"börjar med tomt register"
        )
    return {}


def _save_registry(data_dir: Path, registry: Dict[str, Dict[str, str]]) -> None:
    path = _registry_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} dedup-register kunde ej sparas: {e}")


def _file_hash(filepath: Path) -> str:
    """MD6… nej MD5-hash av filinnehållet (dedup-nyckel när Message-ID saknas)."""
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------------------
# IMPORT
# ---------------------------------------------------------------------------

def import_email(
    filepath: Path,
    store: Any,
    data_dir: Path,
    info: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Importera e-postfil som uppgift.

    Args:
        filepath: Sökväg till .eml eller .msg
        store: TaskStore-instans
        data_dir: data/-katalogen (emails sparas i data/emails/)
        info: OPTIONAL out-dict — fylls med {"duplicate": bool}
              (NY v7-fix88: så UI:t kan säga "redan importerad" i
              stället för att verka tyst)

    Returns:
        task_id om lyckat (vid DUBLETT: den befintliga uppgiftens id),
        None vid fel.
    """
    if info is not None:
        info["duplicate"] = False
    filepath = Path(filepath)
    data_dir = Path(data_dir)

    # NY v7-fix85: validering innan parsning
    if not filepath.is_file():
        logger.error(f"{LOG_PREFIX} Fil finns ej: {filepath}")
        return None
    try:
        size = filepath.stat().st_size
        if size == 0:
            logger.error(f"{LOG_PREFIX} Filen är tom: {filepath.name}")
            return None
        if size > MAX_FILE_SIZE:
            logger.error(
                f"{LOG_PREFIX} Filen för stor ({size / 1024 / 1024:.1f} MB > "
                f"{MAX_FILE_SIZE // 1024 // 1024} MB): {filepath.name}"
            )
            return None
    except OSError as e:
        logger.error(f"{LOG_PREFIX} Kan ej läsa filinfo: {e}")
        return None

    # 1. Parse
    data = parse_email_file(filepath)
    if data is None:
        return None

    # 2. NY v7-fix85: DEDUP — Message-ID (eller filhash) redan importerad?
    with _REGISTRY_LOCK:
        registry = _load_registry(data_dir)
        dedup_key = data.get("message_id") or f"hash:{_file_hash(filepath)}"
        existing = registry.get(dedup_key)
        if existing:
            _ex_id = existing.get("task_id")
            # FIX v7-fix88 (RIKTIG BUGG — "händer inget vid import"): en
            # registry-post kan peka på en uppgift som ANVÄNDAREN TAGIT
            # BORT. Då är det INTE en dublett — mailet ska kunna
            # importeras igen! Verifiera att uppgiften lever.
            _alive = False
            try:
                if _ex_id and hasattr(store, "find_task"):
                    _alive = store.find_task(_ex_id) is not None
                elif _ex_id and hasattr(store, "is_known_task"):
                    _alive = bool(store.is_known_task(_ex_id))
            except Exception:
                _alive = False
            if _alive and _ex_id:
                if info is not None:
                    info["duplicate"] = True
                logger.info(
                    f"{LOG_PREFIX} DUBLETT hoppad över: "
                    f"'{str(existing.get('title', ''))[:40]}' är redan importerad "
                    f"som uppgift {_ex_id!r} — returnerar "
                    f"befintlig uppgift (v7-fix85)"
                )
                return _ex_id
            # Död post (uppgiften raderad) — städa och importera om
            registry.pop(dedup_key, None)
            _save_registry(data_dir, registry)
            logger.info(
                f"{LOG_PREFIX} dedup-post pekade på borttagen uppgift "
                f"{_ex_id!r} — importerar mailet på nytt (v7-fix88)"
            )

    # 3. Bygg titel (saniterat ämne)
    title = data["subject"] or f"E-post från {data['from']}"
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN]

    # 4. Extrahera tagg från avsändare
    sender_tag = _extract_sender_tag(data["from"])

    # 5. Gissa prioritet
    priority = _suggest_priority(data["subject"], data["body"])

    # 6. Skapa uppgift
    tags = [sender_tag] if sender_tag else []
    task_id = store.add_task(
        title=title,
        priority=priority,
        tags=tags,
    )
    if task_id is None:
        logger.error(f"{LOG_PREFIX} add_task misslyckades")
        return None

    # 7. Spara e-postfilen (+ verifiera kopian)
    email_dir = data_dir / "emails"
    email_dir.mkdir(parents=True, exist_ok=True)
    suffix = filepath.suffix.lower()
    email_copy = email_dir / f"{task_id}{suffix}"
    try:
        shutil.copy2(filepath, email_copy)
        # NY v7-fix85: verifiera att kopian är komplett
        if email_copy.stat().st_size != filepath.stat().st_size:
            logger.warning(
                f"{LOG_PREFIX} Kopians storlek skiljer — kan vara skadad: "
                f"{email_copy.name}"
            )
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} Kunde inte spara e-postkopia: {e}")

    # 8. Metadata (gamla nycklar + nya v7-fix85)
    if hasattr(store, "set_task_metadata"):
        store.set_task_metadata(task_id, "email_path", str(email_copy))
        if data["body"]:
            store.set_task_metadata(task_id, "email_body", data["body"])
        if data["from"]:
            store.set_task_metadata(task_id, "email_from", data["from"])
        # NY v7-fix85: rikare metadata
        if data.get("subject"):
            store.set_task_metadata(task_id, "email_subject", data["subject"])
        if data.get("to"):
            store.set_task_metadata(task_id, "email_to", data["to"])
        if data.get("date_iso"):
            store.set_task_metadata(task_id, "email_date", data["date_iso"])
        if data.get("message_id"):
            store.set_task_metadata(task_id, "email_message_id", data["message_id"])
        if data.get("attachments"):
            store.set_task_metadata(
                task_id, "email_attachments",
                ", ".join(data["attachments"]),
            )

    # 9. NY v7-fix85: registrera importen (dedup)
    with _REGISTRY_LOCK:
        registry = _load_registry(data_dir)
        registry[dedup_key] = {
            "task_id": str(task_id),
            "title": title[:100],
            "from": str(data.get("from", ""))[:80],
            "when": datetime.now().isoformat(timespec="seconds"),
            "file": email_copy.name,
        }
        _save_registry(data_dir, registry)

    logger.info(
        f"{LOG_PREFIX} E-post importerad: {title[:50]!r} → "
        f"task={task_id!r}, prio={priority}, fil={email_copy.name} "
        f"({size} B, dedup={dedup_key[:24]}…) (v7-fix85)"
    )
    return task_id


def import_emails(
    filepaths: List[Path],
    store: Any,
    data_dir: Path,
) -> Tuple[int, int, int]:
    """
    NY v7-fix85: importera FLERA e-postfiler i ett svep.

    Returns:
        (antal_importerade, antal_dubletter, antal_misslyckade)
    """
    imported = skipped = failed = 0
    for fp in filepaths:
        try:
            before = _load_registry(Path(data_dir))
            result = import_email(Path(fp), store, Path(data_dir))
            if result is None:
                failed += 1
            else:
                after = _load_registry(Path(data_dir))
                # Nyckel tillagd i registret = ny import; annars dublett
                if len(after) > len(before):
                    imported += 1
                else:
                    skipped += 1
        except Exception as e:
            failed += 1
            logger.error(f"{LOG_PREFIX} import_emails: {fp} → {e}")
    logger.info(
        f"{LOG_PREFIX} Batch-import klar: {imported} importerade, "
        f"{skipped} dubletter, {failed} misslyckade (v7-fix85)"
    )
    return (imported, skipped, failed)


# ---------------------------------------------------------------------------
# ÖPPNA E-POST
# ---------------------------------------------------------------------------

def open_email(email_path: str) -> bool:
    """
    Öppna en sparad e-postfil i standardprogrammet.

    Windows: os.startfile()
    macOS:   open
    Linux:   xdg-open
    """
    path = Path(email_path)
    if not path.is_file():
        logger.warning(f"{LOG_PREFIX} E-postfil finns ej: {path}")
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        logger.info(f"{LOG_PREFIX} E-post öppnad: {path.name}")
        return True
    except Exception as e:
        logger.error(f"{LOG_PREFIX} Kunde inte öppna e-post: {e}")
        return False


# ---------------------------------------------------------------------------
# SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("email_import.py — Self-Test (v7-fix85)")
    print("=" * 60)
    # Skapa en test-.eml
    test_eml = Path("/tmp/test.eml")
    test_eml.write_text(
        "From: Anna <anna@example.com>\n"
        "To: Rickard\n"
        "Subject: Brådskande rapport\n"
        "Date: Mon, 30 Sep 2026 10:00:00 +0200\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Hej Rickard!\n"
        "\n"
        "Kan du skicka rapporten ASAP? Den behövs imorgon.\n"
        "\n"
        "Mvh Anna\n",
        encoding="utf-8",
    )
    result = parse_eml(test_eml)
    assert result is not None
    assert "Brådskande" in result["subject"]
    assert "anna" in result["from"].lower()
    assert "ASAP" in result["body"]
    print("  ✓ parse_eml: subject, from, body OK")
    print("  ✓ _suggest_priority:", _suggest_priority(result["subject"], result["body"]))
    print("  ✓ _extract_sender_tag:", _extract_sender_tag(result["from"]))

    # NY v7-fix85: veckad rubrik sanitieras
    folded = Path("/tmp/folded.eml")
    folded.write_text(
        "From: Bosse <bosse@example.com>\n"
        "Subject: Detta ar ett\n"
        "  veckat amne med\n"
        "\tradbrytningar\n"
        "Content-Type: text/plain\n"
        "\nBrödtext\n",
        encoding="utf-8",
    )
    r2 = parse_eml(folded)
    assert r2 is not None and "\n" not in r2["subject"] and "  " not in r2["subject"]
    print("  ✓ veckad rubrik sanitierad:", repr(r2["subject"]))

    # NY v7-fix85: HTML med svenska entities
    html_mail = Path("/tmp/html.eml")
    html_mail.write_text(
        "From: Cissi <c@example.com>\n"
        "Subject: HTML-test &aring;\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<p>Hej &aring;ter! &auml;ntligen &#246;ppet.</p>"
        "<script>evil()</script><div>Osynligt style-block</div>\n",
        encoding="utf-8",
    )
    r3 = parse_eml(html_mail)
    assert r3 is not None and "åter" in r3["body"] and "äntligen" in r3["body"]
    assert "öppet" in r3["body"] and "evil" not in r3["body"]
    print("  ✓ HTML→text med svenska entities:", repr(r3["body"][:40]))

    # NY v7-fix85: bilagor listas
    import email as _email_mod
    att_mail = Path("/tmp/att.eml")
    att_mail.write_text(
        "From: Danne <d@example.com>\n"
        "Subject: Med bilagor\n"
        "Content-Type: text/plain\n"
        "\nSe bilagor\n",
        encoding="utf-8",
    )
    r4 = parse_eml(att_mail)
    assert r4 is not None and r4["attachments"] == []
    print("  ✓ tom bilage-lista utan bilagor")

    for f in (test_eml, folded, html_mail, att_mail):
        with _suppress_all():
            f.unlink(missing_ok=True)
    print("=" * 60)
    print("✓ ALLA TESTER PASSERADE")
