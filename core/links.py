# -*- coding: utf-8 -*-
"""
links.py — länkar på uppgifter: hitta URL:er i text och hämta sidans titel. Ingen Qt behövs.

``fetch_title`` gör ETT anrop (http/https, timeout, högst 256 kB) och körs av GUI:t i en
bakgrundstråd. Ingenting skickas utom själva sidförfrågan.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[LINKS]"

MAX_URL_LEN = 2000
MAX_TITLE_LEN = 200
MAX_READ_BYTES = 256 * 1024
FETCH_TIMEOUT = 6.0
USER_AGENT = "Mozilla/5.0 (compatible; TaskBord link preview)"

_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'`]+")
_TRAIL = ".,;:!?)]}»”’'\""
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.I | re.S)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I | re.S)
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.S)
_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w.:-]+)""", re.I)
_CT_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([\w.:-]+)", re.I)


def normalize(url: str) -> Optional[str]:
    """Gör om en träff till en giltig http(s)-URL, annars None. 'www.x.se' → 'https://www.x.se'."""
    u = str(url or "").strip()
    while u and u[-1] in _TRAIL:
        # behåll avslutande ')' om URL:en har en matchande '(' (t.ex. Wikipedia)
        if u[-1] == ")" and u.count("(") >= u.count(")"):
            break
        u = u[:-1]
    if not u:
        return None
    if u.lower().startswith("www."):
        u = "https://" + u
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or len(u) > MAX_URL_LEN:
        return None
    if "." not in p.hostname and p.hostname.lower() != "localhost":
        return None
    return u


def extract_urls(text: str) -> List[str]:
    """Alla URL:er i texten (i ordning, utan dubbletter)."""
    out: List[str] = []
    for m in _URL_RE.finditer(str(text or "")):
        u = normalize(m.group(0))
        if u and u not in out:
            out.append(u)
    return out


def strip_urls(text: str) -> str:
    """Texten utan URL:erna (mellanrummen städas)."""
    def _rep(m: "re.Match[str]") -> str:
        raw = m.group(0)
        return "" if normalize(raw) else raw
    s = _URL_RE.sub(_rep, str(text or ""))
    return re.sub(r"\s{2,}", " ", s).strip()


def display_title(url: str) -> str:
    """Titel att visa innan/utan sidtitel: värdnamnet (utan www.)."""
    try:
        host = urllib.parse.urlsplit(url).hostname or url
    except ValueError:
        host = url
    host = host.lower()
    return (host[4:] if host.startswith("www.") else host)[:MAX_TITLE_LEN] or url[:MAX_TITLE_LEN]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()[:MAX_TITLE_LEN]


def parse_title(raw: bytes, content_type: str = "") -> str:
    """Plocka ut sidans titel (``<title>`` eller og:title) ur HTML-bytes."""
    enc = ""
    m = _CT_CHARSET_RE.search(content_type or "")
    if m:
        enc = m.group(1)
    else:
        m2 = _CHARSET_RE.search(raw[:4096])
        if m2:
            enc = m2.group(1).decode("ascii", "ignore")
    text = ""
    for cand in ([enc] if enc else []) + ["utf-8", "cp1252"]:
        try:
            text = raw.decode(cand, errors="strict" if cand != "cp1252" else "replace")
            break
        except (LookupError, UnicodeDecodeError):
            continue
    if not text:
        text = raw.decode("utf-8", errors="replace")
    og = ""
    for tag in _META_RE.findall(text):
        attrs = {a.lower(): (b or c or d) for a, b, c, d in _ATTR_RE.findall(tag)}
        if attrs.get("property", "").lower() == "og:title" and attrs.get("content"):
            og = _clean(attrs["content"])
            break
    m3 = _TITLE_RE.search(text)
    title = _clean(m3.group(1)) if m3 else ""
    return title or og


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_title(url: str, timeout: float = FETCH_TIMEOUT) -> str:
    """Hämta sidans titel. Tom sträng vid fel, offline, icke-HTML eller utan titel. Kastar aldrig."""
    u = normalize(url)
    if not u:
        return ""
    try:
        req = urllib.request.Request(
            u, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                        "Accept-Language": "sv,en;q=0.8"},
        )
        opener = urllib.request.build_opener(_SafeRedirect())
        with opener.open(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "") or ""
            if ctype and "html" not in ctype.lower():
                return ""
            raw = resp.read(MAX_READ_BYTES)
        return parse_title(raw, ctype)
    except Exception as e:  # nätverk, SSL, timeout, trasig HTML …
        logger.debug(f"{LOG_PREFIX} ingen titel för {u[:80]}: {e}")
        return ""
