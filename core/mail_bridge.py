# -*- coding: utf-8 -*-
"""
mail_bridge.py — TaskBord v7-fix90: e-postbrygga (Thunderbird → uppgifter)
=========================================================================
Copyright © Rickard Längkvist, 2025–2026

Rickard 2026-10-11: "importera uppgifter från mail via thunderbird — om man
kan göra tillägg till thunderbird som kan importera uppgift till appen.
Uppgifter ska sparas i json-fil för att finnas kvar efter omstart av appen."

SVARET: ja. Denna modul är appens sida av bryggan. Ett Thunderbird-tillägg
(se katalogen `thunderbird-tillagg/`) skickar mailet hit och en uppgift
skapas — och sparas i JSON på disk direkt (data/active.json), så att den
finns kvar även efter omstart/krasch.

TVÅ VÄGAR IN (båda använder samma kodväg → samma dedup, samma metadata)
======================================================================
1. HTTP-bryggan (live, kräver att TaskBord körs)
     Tillägget POST:ar mailet till http://127.0.0.1:8765
       POST /task   → JSON-payload (ämne, avsändare, brödtext, prioritet ...)
       POST /eml    → RÅ .eml (hela originalmailet sparas som bilaga)
     Servern lyssnar BARA på localhost (127.0.0.1) och kräver token.

2. Inkorgsmappen `data/inbox/` (fungerar även om appen var avstängd)
     Lägg/spara .eml, .msg eller .json i data/inbox/ → import sker
     automatiskt inom några sekunder, filen flyttas till inbox/imported/.
     TaskBord importerar allt som ligger där redan vid start.

JSON-FILER (allt överlever omstart)
====================================
    data/active.json                     ← UPPGIFTERNA (schema v5, atomiskt)
    data/mail_bridge/token.txt           ← token (hemlig nyckel) för tillägget
    data/mail_bridge/imported.json       ← dedup-register (Message-ID → task)
    data/mail_bridge/bridge_status.json  ← status: port, antal importer, tid
    data/mail_bridge/tillagg_installningar.json  ← klistra in i tillägget
    data/emails/{task_id}.eml            ← originalmailet (öppnas från kortet)
    data/inbox/imported/                 ← kvittens: dessa filer är importerade

API (allt utom /health kräver token i headern X-TaskBord-Token)
===============================================================
    GET  /                → statussida (HTML, kan testas i webbläsaren)
    GET  /health          → {"ok": true, "app": "TaskBord", ...}
    GET  /tasks           → aktiva uppgifter (id, title, priority, due_date)
    GET  /imported?message_id=<id>  → är mailet redan importerat?
    POST /task            → skapa uppgift från JSON
    POST /eml             → skapa uppgift från rå .eml/.msg-data

DESIGN
======
* Endast stdlib (http.server, json, secrets) — inga nya beroenden.
* Trådsäker: egen lås runt dedup-registret; store har egna lås.
* Robust: token-jämförelse i konstant tid, storleksgränser, CORS för
  tillägget, ALDRIG krasch om store/disk strular (allt loggas).
* Uppgifter sparas DIREKT (store.save()) efter varje import — kravet
  "finnas kvar efter omstart" uppfylls även vid strömavbrott.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("MailBridge")
LOG_PREFIX: str = "[MAILBRIDGE]"

# --- Versioner/namn --------------------------------------------------------
BRIDGE_VERSION: str = "1.0.0 (v7-fix90)"
APP_NAME: str = "TaskBord"

# --- Kataloger/filer -------------------------------------------------------
BRIDGE_DIRNAME: str = "mail_bridge"
INBOX_DIRNAME: str = "inbox"
TOKEN_FILENAME: str = "token.txt"
REGISTRY_FILENAME: str = "imported.json"
STATUS_FILENAME: str = "bridge_status.json"
CONFIG_FILENAME: str = "tillagg_installningar.json"

# --- Nätverk ---------------------------------------------------------------
HOST: str = "127.0.0.1"          # ALDRIG 0.0.0.0 — bara denna dator
DEFAULT_PORT: int = 8765
PORT_SCAN_ATTEMPTS: int = 12     # om 8765 är upptagen → prova 8766, 8767 ...
TOKEN_HEADER: str = "X-TaskBord-Token"
TOKEN_LENGTH: int = 32           # hex-tecken (16 byte entropi)

# --- Gränser ---------------------------------------------------------------
MAX_JSON_BODY: int = 512 * 1024          # 512 kB räcker för ämne+brödtext
MAX_EML_BODY: int = 25 * 1024 * 1024     # samma gräns som email_import
MAX_TITLE_LEN: int = 200
MAX_NOTE_LEN: int = 4000
MAX_TAGS: int = 10
MAX_TAG_LEN: int = 24
DEFAULT_INBOX_POLL_SEC: int = 3
INBOX_MIN_AGE_SEC: float = 0.75          # vänta tills filen slutat växa
INBOX_MAX_ATTEMPTS: int = 3

VALID_PRIORITIES: Tuple[str, ...] = ("low", "medium", "high")

# Register-lås (trådsäkert — HTTP-tråd + watcher-tråd + GUI-tråd)
_REGISTRY_LOCK = threading.Lock()


# ===========================================================================
# SMÅ HJÄLPARE
# ===========================================================================

def _now_iso() -> str:
    """Lokal ISO-tid (sekundupplösning) — mänskligt läsbar i JSON-filerna."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _utc_iso() -> str:
    """UTC ISO-tid (för statusfiler)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_text(value: Any, max_len: int = MAX_TITLE_LEN) -> str:
    """
    Rensa text från kontrolltecken/radbrytningar (veckade rubriker från
    e-post kan annars bryta UI:t) och kapa till maxlängd.
    """
    s = str(value if value is not None else "")
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()[:max_len]


def normalize_message_id(value: Any) -> str:
    """
    Normalisera Message-ID så att samma mail får SAMMA dedup-nyckel.

    NY v7-fix90b (hittad i E2E-test): samma mail kunde komma in både som
    rå .eml (<id@domän> — med vinkelparenteser) och som JSON-payload
    (id@domän — utan) → två olika nycklar → DUBBEL uppgift. Nu strippas
    alltid <>, blanksteg och citattecken.
    """
    s = sanitize_text(value, 300)
    s = s.strip().strip("<>").strip().strip('"').strip()
    return s


def sanitize_multiline(value: Any, max_len: int = MAX_NOTE_LEN) -> str:
    """Rensa brödtext men BEHÅLL radbrytningar (visas som anteckning)."""
    s = str(value if value is not None else "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[^\S\n]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    return s.strip()[:max_len]


def bridge_dir(data_dir: Path) -> Path:
    """`<data>/mail_bridge/` — bryggans egna JSON-filer."""
    return Path(data_dir) / BRIDGE_DIRNAME


def inbox_dir(data_dir: Path) -> Path:
    """`<data>/inbox/` — släpp .eml/.msg/.json här för automatisk import."""
    return Path(data_dir) / INBOX_DIRNAME


def ensure_dirs(data_dir: Path) -> Dict[str, Path]:
    """Skapa alla kataloger bryggan behöver (idempotent)."""
    data_dir = Path(data_dir)
    paths = {
        "data": data_dir,
        "bridge": bridge_dir(data_dir),
        "inbox": inbox_dir(data_dir),
        "inbox_imported": inbox_dir(data_dir) / "imported",
        "inbox_failed": inbox_dir(data_dir) / "failed",
        "emails": data_dir / "emails",
    }
    for p in paths.values():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:      # mycket osannolikt, men appen får ej dö
            logger.warning(f"{LOG_PREFIX} kunde inte skapa {p}: {e}")
    return paths


def _atomic_write_json(path: Path, obj: Any) -> bool:
    """Skriv JSON atomiskt (temp-fil + replace) — tål avbrott mitt i skrivning."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte skriva {path.name}: {e}")
        return False


def _read_json(path: Path, default: Any = None) -> Any:
    """Läs JSON robust (korrupt fil → default)."""
    try:
        path = Path(path)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} kunde inte läsa {Path(path).name} ({e}) — "
            f"använder standardvärde"
        )
    return default


# ===========================================================================
# TOKEN (hemlig nyckel mellan appen och Thunderbird-tillägget)
# ===========================================================================

def load_token(data_dir: Path, create: bool = True) -> str:
    """
    Hämta (eller skapa) bryggans token.

    Token ligger i `data/mail_bridge/token.txt` och överlever omstart.
    Skapas med secrets.token_hex (kryptografiskt slump) — 32 tecken.
    """
    path = bridge_dir(Path(data_dir)) / TOKEN_FILENAME
    try:
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if len(token) >= 16:
                return token
        if not create:
            return ""
        token = secrets.token_hex(TOKEN_LENGTH // 2)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        try:  # bästa möjliga skydd (Windows: ignoreras tyst)
            os.chmod(path, 0o600)
        except Exception:
            pass
        logger.info(
            f"{LOG_PREFIX} ny token skapad: {path} ({len(token)} tecken)"
        )
        return token
    except Exception as e:
        logger.error(f"{LOG_PREFIX} token kunde ej läsas/skapas: {e}")
        return ""


def save_token(data_dir: Path, token: str) -> bool:
    """Spara token (används om användaren vill byta nyckel)."""
    token = sanitize_text(token, 64)
    if len(token) < 8:
        return False
    path = bridge_dir(Path(data_dir)) / TOKEN_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"{LOG_PREFIX} token kunde ej sparas: {e}")
        return False


def extension_config(data_dir: Path, port: int, token: str) -> Dict[str, Any]:
    """
    Inställningar som Thunderbird-tillägget behöver.

    Skrivs till `data/mail_bridge/tillagg_installningar.json` och visas i
    tray-dialogen (kopiera → klistra in i tilläggets inställningar).
    """
    cfg = {
        "url": f"http://{HOST}:{int(port)}",
        "port": int(port),
        "token": token,
        "app": APP_NAME,
        "bridge_version": BRIDGE_VERSION,
        "generated": _now_iso(),
        "instruktion": (
            "Kopiera hela innehållet och klistra in i TaskBord-tilläggets "
            "inställningar i Thunderbird (fältet 'Klistra in inställningar')."
        ),
    }
    _atomic_write_json(bridge_dir(Path(data_dir)) / CONFIG_FILENAME, cfg)
    return cfg


# ===========================================================================
# DEDUP-REGISTER (JSON: data/mail_bridge/imported.json)
# ===========================================================================

class DedupRegistry:
    """
    Håller reda på importerade mail (Message-ID / innehålls-hash → task-id).

    Registret ligger i JSON på disk och läses/skrivs trådsäkert. En post
    som pekar på en BORTTAGEN uppgift är död och städas automatiskt —
    då kan mailet importeras igen (samma princip som email_import v7-fix88).
    """

    __slots__ = ("_path", "_lock", "_cache", "_store")

    def __init__(self, data_dir: Path, store: Any = None) -> None:
        self._path = bridge_dir(Path(data_dir)) / REGISTRY_FILENAME
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._store = store
        self._load()

    # --- disk ------------------------------------------------------------
    def _load(self) -> None:
        data = _read_json(self._path, {})
        if isinstance(data, dict):
            # Stöd både {"entries": {...}} och platt {"msgid": {...}}
            entries = data.get("entries") if "entries" in data else data
            if isinstance(entries, dict):
                self._cache = entries
        logger.debug(
            f"{LOG_PREFIX} dedup-register laddat: {len(self._cache)} poster"
        )

    def _save(self) -> None:
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "count": len(self._cache),
            "entries": self._cache,
        }
        _atomic_write_json(self._path, payload)

    # --- API -------------------------------------------------------------
    def _task_alive(self, task_id: str) -> bool:
        if not task_id or self._store is None:
            return False
        try:
            if hasattr(self._store, "find_task"):
                return self._store.find_task(task_id) is not None
            if hasattr(self._store, "is_known_task"):
                return bool(self._store.is_known_task(task_id))
        except Exception:
            return False
        return False

    def find_alive(self, key: str) -> Optional[str]:
        """
        Returnera task-id om nyckeln redan är importerad OCH uppgiften
        fortfarande finns. Döda poster städas bort automatiskt.
        """
        if not key:
            return None
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            task_id = str(entry.get("task_id", ""))
            if self._task_alive(task_id):
                return task_id
            self._cache.pop(key, None)
            self._save()
            logger.info(
                f"{LOG_PREFIX} dedup-post {key[:32]}… pekade på borttagen "
                f"uppgift {task_id!r} — importerar på nytt"
            )
            return None

    def register(self, key: str, task_id: str, info: Dict[str, Any]) -> None:
        """Registrera en ny import (skrivs till JSON direkt)."""
        if not key:
            return
        with self._lock:
            self._cache[key] = {
                "task_id": str(task_id),
                "title": sanitize_text(info.get("title", ""), 100),
                "from": sanitize_text(info.get("from", ""), 80),
                "source": sanitize_text(info.get("source", ""), 40),
                "when": _now_iso(),
                "file": sanitize_text(info.get("file", ""), 80),
            }
            # Håll registret litet (max 5000 poster, äldst först ut)
            if len(self._cache) > 5000:
                for old_key in list(self._cache.keys())[:1000]:
                    self._cache.pop(old_key, None)
            self._save()

    def count(self) -> int:
        with self._lock:
            return len(self._cache)

    def all_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._cache.values()]


# ===========================================================================
# SKAPA UPPGIFT FRÅN MAILDATA (delas av HTTP, inkorgsmapp och självtest)
# ===========================================================================

def _import_email_helpers() -> Dict[str, Any]:
    """
    Hämta hjälpare från core.email_import (prioritetsgissning, tagg, HTML).

    Importeras lazy eftersom email_import importerar store-relaterade saker
    och för att undvika cirkulära importer under appstart.
    """
    helpers: Dict[str, Any] = {}
    try:
        from core import email_import as _ei  # typ: ignore
        helpers = {
            "suggest_priority": getattr(_ei, "_suggest_priority", None),
            "sender_tag": getattr(_ei, "_extract_sender_tag", None),
            "strip_html": getattr(_ei, "_strip_html", None),
            "import_email": getattr(_ei, "import_email", None),
            "open_email": getattr(_ei, "open_email", None),
            "max_title": getattr(_ei, "MAX_TITLE_LEN", MAX_TITLE_LEN),
        }
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} email_import ej tillgänglig ({e}) — "
            f"använder enkla inbyggda hjälpare"
        )
    return helpers


def _fallback_priority(subject: str, body: str) -> str:
    """Enkel prioritetsgissning om email_import saknas."""
    text = f"{subject} {body}".lower()
    if any(w in text for w in ("asap", "brådskande", "urgent", "viktigt", "deadline")):
        return "high"
    if any(w in text for w in ("senare", "vänta", "maybe", "ingen brådska")):
        return "low"
    return "medium"


def _fallback_sender_tag(from_addr: str) -> str:
    """'Anna <a@b.se>' → 'Anna' (annars lokal-delen)."""
    if not from_addr:
        return ""
    m = re.search(r'^"?([^"<]+)"?\s*<', from_addr)
    if m:
        return m.group(1).strip()[:20]
    return str(from_addr).split("@")[0].strip()[:20]


def _coerce_priority(value: Any, subject: str = "", body: str = "") -> str:
    """Prioritet från payload ('high'/'medium'/'low') eller gissning."""
    p = sanitize_text(value, 12).lower()
    if p in VALID_PRIORITIES:
        return p
    if p in ("hög", "hog", "urgent", "1", "p1"):
        return "high"
    if p in ("låg", "lag", "low", "3", "p3"):
        return "low"
    helpers = _import_email_helpers()
    fn = helpers.get("suggest_priority")
    if callable(fn):
        try:
            return str(fn(subject, body)) or "medium"
        except Exception:
            pass
    return _fallback_priority(subject, body)


def _coerce_due_date(value: Any) -> Optional[str]:
    """
    Acceptera '2026-10-15', '2026-10-15T10:00', 'imorgon', 'idag'.

    Returnerar 'YYYY-MM-DD' eller None (okänt format ignoreras tyst —
    uppgiften skapas ändå, vilket är viktigare än förfallodatumet).
    """
    s = sanitize_text(value, 40)
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    low = s.lower()
    try:
        from datetime import date, timedelta
        today = date.today()
        if low in ("idag", "today"):
            return today.isoformat()
        if low in ("imorgon", "i morgon", "tomorrow"):
            return (today + timedelta(days=1)).isoformat()
        if low in ("övermorgon", "overmorgon"):
            return (today + timedelta(days=2)).isoformat()
        if low in ("nästa vecka", "nasta vecka"):
            return (today + timedelta(days=7)).isoformat()
        # svenska veckodagar: "fredag"
        weekdays = {
            "måndag": 0, "tisdag": 1, "onsdag": 2, "torsdag": 3,
            "fredag": 4, "lördag": 5, "söndag": 6,
        }
        if low in weekdays:
            delta = (weekdays[low] - today.weekday()) % 7
            delta = delta or 7   # "fredag" på en fredag = nästa fredag
            return (today + timedelta(days=delta)).isoformat()
    except Exception:
        pass
    return None


def _coerce_tags(payload: Dict[str, Any], sender_tag: str) -> List[str]:
    """Bygg tagg-lista: avsändartagg + payload-taggar (max 10, unika)."""
    tags: List[str] = []
    raw = payload.get("tags")
    extra: List[str] = []
    if isinstance(raw, (list, tuple)):
        extra = [str(t) for t in raw]
    elif isinstance(raw, str):
        extra = re.split(r"[,;]", raw)
    for cand in ([sender_tag] + extra):
        tag = sanitize_text(cand, MAX_TAG_LEN).strip()
        if not tag:
            continue
        if tag.lower() in ("none", "null", "-"):
            continue
        if all(tag.lower() != t.lower() for t in tags):
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def _body_from_payload(payload: Dict[str, Any]) -> str:
    """Brödtext/anteckning: 'note' → 'body' → 'text' (HTML rensas)."""
    raw = (
        payload.get("note")
        or payload.get("body")
        or payload.get("text")
        or payload.get("preview")
        or ""
    )
    text = sanitize_multiline(raw)
    if "<" in text and ">" in text:
        helpers = _import_email_helpers()
        fn = helpers.get("strip_html")
        if callable(fn):
            try:
                text = sanitize_multiline(fn(text))
            except Exception:
                pass
    return text


def dedup_key_for(payload: Dict[str, Any], fallback_raw: bytes = b"") -> str:
    """
    Dedup-nyckel: Message-ID om det finns, annars hash av
    avsändare + ämne + datum + brödtext (stabil mellan importer).
    """
    mid = normalize_message_id(
        payload.get("message_id") or payload.get("messageId")
    )
    if mid:
        return mid
    basis = "|".join(
        [
            sanitize_text(payload.get("from"), 120).lower(),
            sanitize_text(payload.get("subject") or payload.get("title"), 200).lower(),
            sanitize_text(payload.get("date"), 60),
            sanitize_multiline(payload.get("body") or payload.get("note"), 500)[:300],
        ]
    ).encode("utf-8")
    if fallback_raw:
        basis = basis + b"|" + fallback_raw[:4096]
    return "hash:" + hashlib.md5(basis).hexdigest()


def create_task_from_payload(
    store: Any,
    data_dir: Path,
    payload: Dict[str, Any],
    *,
    registry: Optional[DedupRegistry] = None,
    source: str = "bridge",
    save: bool = True,
) -> Dict[str, Any]:
    """
    Skapa EN uppgift från maildata (JSON-dict).

    Detta är kärnan som BÅDE HTTP-endpointen `/task`, inkorgsmappens
    .json-filer och självtestet använder — samma beteende överallt.

    Args:
        store:    TaskStore-instans
        data_dir: data/-katalogen
        payload:  {"subject"/"title", "from", "body"/"note", "priority",
                   "due_date", "tags", "message_id", "date", "folder",
                   "account", "url", "attachments", "source", ...}
        registry: delad DedupRegistry (skapas vid behov)
        source:   "bridge" | "inbox" | "tray" | ...
        save:     spara store till disk direkt (JSON!) — default True

    Returns:
        {"ok": bool, "task_id": str|None, "duplicate": bool,
         "title": str, "priority": str, "error": str|None,
         "saved": bool, "count": int}
    """
    data_dir = Path(data_dir)
    ensure_dirs(data_dir)
    registry = registry or DedupRegistry(data_dir, store)

    subject = sanitize_text(
        payload.get("subject") or payload.get("title"), MAX_TITLE_LEN
    )
    sender = sanitize_text(
        payload.get("from") or payload.get("author") or payload.get("sender"), 200
    )
    body = _body_from_payload(payload)

    title = subject or (
        f"E-post från {sender}" if sender else "Uppgift från e-post"
    )
    title = sanitize_text(title, MAX_TITLE_LEN)

    result: Dict[str, Any] = {
        "ok": False,
        "task_id": None,
        "duplicate": False,
        "title": title,
        "priority": "medium",
        "error": None,
        "saved": False,
        "count": 0,
    }

    if store is None or not hasattr(store, "add_task"):
        result["error"] = "Store är inte tillgänglig"
        logger.error(f"{LOG_PREFIX} create_task: ingen store")
        return result

    # --- DEDUP: samma mail importeras aldrig två gånger ------------------
    key = dedup_key_for(payload, body.encode("utf-8", "replace"))
    existing = registry.find_alive(key)
    if existing:
        result.update(ok=True, task_id=existing, duplicate=True)
        # NY v7-fix90b: användarens EXPLICITA val i Thunderbird-popupen
        # (prioritet/förfallodatum/taggar) ska gälla även när mailet redan
        # är importerat — annars "händer inget" när man t.ex. väljer hög
        # prioritet på ett mail som redan finns i listan.
        explicit = {
            k: payload.get(k)
            for k in ("priority", "due_date", "tags", "title", "note")
            if payload.get(k)
        }
        if explicit:
            apply_extras(store, existing, explicit)
            if save and hasattr(store, "save"):
                with suppress(Exception):
                    result["saved"] = bool(store.save())
        logger.info(
            f"{LOG_PREFIX} DUBLETT: '{title[:40]}' är redan uppgift {existing!r}"
            + (f" (uppdaterade: {', '.join(explicit)})" if explicit else "")
        )
        return result

    # --- Prioritet + taggar ---------------------------------------------
    priority = _coerce_priority(payload.get("priority"), subject, body)
    helpers = _import_email_helpers()
    sender_tag = ""
    tag_fn = helpers.get("sender_tag")
    if callable(tag_fn) and sender:
        try:
            sender_tag = str(tag_fn(sender) or "")
        except Exception:
            sender_tag = ""
    if not sender_tag and sender:
        sender_tag = _fallback_sender_tag(sender)
    tags = _coerce_tags(payload, sender_tag)
    due = _coerce_due_date(payload.get("due_date") or payload.get("due"))

    # --- Skapa uppgiften -------------------------------------------------
    try:
        task_id = store.add_task(
            title=title,
            priority=priority,
            due_date=due,
            tags=tags,
        )
    except Exception as e:
        result["error"] = f"add_task misslyckades: {e}"
        logger.error(f"{LOG_PREFIX} add_task kraschade: {e}", exc_info=True)
        return result

    if not task_id:
        result["error"] = "add_task returnerade inget id"
        logger.error(f"{LOG_PREFIX} add_task gav inget id för '{title[:40]}'")
        return result

    result.update(ok=True, task_id=task_id, priority=priority)

    # --- Metadata på kortet (så originalmailet kan öppnas) ---------------
    attachments = payload.get("attachments")
    if isinstance(attachments, (list, tuple)):
        attachments = ", ".join(str(a) for a in attachments)
    meta = {
        "email_subject": subject,
        "email_from": sender,
        "email_date": sanitize_text(payload.get("date"), 60),
        "email_message_id": sanitize_text(
            payload.get("message_id") or payload.get("messageId"), 300
        ),
        "email_body": body,
        "email_to": sanitize_text(payload.get("to"), 200),
        "email_cc": sanitize_text(payload.get("cc"), 200),
        "email_folder": sanitize_text(payload.get("folder"), 120),
        "email_account": sanitize_text(payload.get("account"), 120),
        "email_attachments": sanitize_text(attachments, 300),
        "email_source": sanitize_text(payload.get("source") or source, 40),
        "email_imported_at": _now_iso(),
    }
    if hasattr(store, "set_task_metadata"):
        for k, v in meta.items():
            if v:
                try:
                    store.set_task_metadata(task_id, k, v)
                except Exception as e:
                    logger.debug(f"{LOG_PREFIX} metadata {k} misslyckades: {e}")

    # --- Dedup-registret (JSON) -----------------------------------------
    registry.register(
        key,
        task_id,
        {
            "title": title,
            "from": sender,
            "source": sanitize_text(payload.get("source") or source, 40),
        },
    )

    # --- SPARA TILL JSON DIREKT (kravet: kvar efter omstart) ------------
    if save and hasattr(store, "save"):
        try:
            result["saved"] = bool(store.save())
            logger.info(
                f"{LOG_PREFIX} uppgift {task_id!r} sparad till JSON: "
                f"{'OK' if result['saved'] else 'MISSLYCKADES'}"
            )
        except Exception as e:
            logger.error(f"{LOG_PREFIX} save misslyckades: {e}", exc_info=True)

    try:
        result["count"] = int(store.count()[0]) if hasattr(store, "count") else 0
    except Exception:
        pass

    logger.info(
        f"{LOG_PREFIX} ✓ uppgift skapad från mail: {task_id!r} "
        f"'{title[:50]}' (prio={priority}, taggar={tags}, "
        f"källa={payload.get('source') or source}, dedup={key[:24]}…)"
    )
    return result


def peek_message_id(filepath: Path, max_bytes: int = 65536) -> str:
    """
    Läs Message-ID ur en .eml-fil utan att parsa hela mailet.

    NY v7-fix90b: används för att upptäcka dubbletter mellan den råa
    .eml-vägen (Thunderbird-tillägget) och JSON-vägen. Returnerar
    normaliserat id (utan <>) eller "".
    """
    try:
        with open(filepath, "rb") as fh:
            head = fh.read(max_bytes)
    except Exception:
        return ""
    m = re.search(
        rb"^message-id:[ \t]*(.+?)[ \t]*\r?$", head, re.MULTILINE | re.IGNORECASE
    )
    if not m:
        return ""
    try:
        raw = m.group(1).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return normalize_message_id(raw)


def apply_extras(store: Any, task_id: str, extras: Optional[Dict[str, Any]]) -> None:
    """
    NY v7-fix90b: applicera användarens val (prioritet, datum, taggar, titel)
    på en uppgift som skapats från ett rå-mail.

    Bakgrund (hittad i E2E-test): tillägget skickar originalmailet (.eml)
    för bästa kvalitet — men då tappades prioritet/förfallodatum/taggar som
    användaren valt i popupen. Tidigare gjordes ett extra /task-anrop som
    skapade en DUBBEL uppgift. Nu appliceras extras på den befintliga.
    """
    if not extras or not task_id:
        return
    try:
        priority = sanitize_text(extras.get("priority"), 12).lower()
        if priority in VALID_PRIORITIES and hasattr(store, "set_priority"):
            store.set_priority(task_id, priority)
        due = _coerce_due_date(extras.get("due_date") or extras.get("due"))
        if due and hasattr(store, "set_due_date"):
            store.set_due_date(task_id, due)
        title = sanitize_text(extras.get("title"), MAX_TITLE_LEN)
        if title and hasattr(store, "update_task_title"):
            store.update_task_title(task_id, title)
        note = sanitize_multiline(extras.get("note"), MAX_NOTE_LEN)
        if note and hasattr(store, "set_task_metadata"):
            store.set_task_metadata(task_id, "email_body", note)
        raw_tags = extras.get("tags")
        tags: List[str] = []
        if isinstance(raw_tags, (list, tuple)):
            tags = [str(t) for t in raw_tags]
        elif isinstance(raw_tags, str):
            tags = re.split(r"[,;]", raw_tags)
        if tags and hasattr(store, "add_tag"):
            for tag in tags:
                clean = sanitize_text(tag, MAX_TAG_LEN)
                if clean:
                    store.add_tag(task_id, clean)
        logger.info(
            f"{LOG_PREFIX} extras applicerade på {task_id!r}: "
            f"prio={priority or '-'}, datum={due or '-'}, taggar={tags}"
        )
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte applicera extras: {e}")


def import_email_file(
    store: Any,
    data_dir: Path,
    filepath: Path,
    *,
    registry: Optional[DedupRegistry] = None,
    source: str = "inbox",
    save: bool = True,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Importera en .eml/.msg-fil (använder core.email_import — samma kod som
    fil-dialogen och dra-och-släpp i widgeten).

    Originalfilen sparas i data/emails/{task_id}.eml och uppgiften får
    📧-metadata så att mailet kan öppnas från kortet.

    NY v7-fix90b:
      * DEDUP mot bryggans register redan här (samma Telegram-ID kan ha
        kommit in via JSON-vägen först) — Message-ID normaliseras.
      * `extras` (prioritet/datum/taggar/titel från Thunderbird-popupen)
        appliceras på den skapade uppgiften.
    """
    data_dir = Path(data_dir)
    filepath = Path(filepath)
    ensure_dirs(data_dir)
    helpers = _import_email_helpers()
    import_email = helpers.get("import_email")
    registry = registry or DedupRegistry(data_dir, store)

    result: Dict[str, Any] = {
        "ok": False, "task_id": None, "duplicate": False,
        "title": filepath.name, "priority": "medium",
        "error": None, "saved": False, "count": 0,
    }
    if not callable(import_email):
        result["error"] = "core.email_import kunde inte laddas"
        return result
    if not filepath.is_file():
        result["error"] = f"filen finns inte: {filepath}"
        return result

    # --- NY v7-fix90b: dubblett-koll FÖRE import (Message-ID i filen) ----
    mid = peek_message_id(filepath) if filepath.suffix.lower() == ".eml" else ""
    if mid:
        existing = registry.find_alive(mid)
        if existing:
            title = ""
            with suppress(Exception):
                task = store.find_task(existing) if hasattr(store, "find_task") else None
                title = str((task or {}).get("title", ""))
            result.update(ok=True, task_id=existing, duplicate=True, title=title)
            # NY v7-fix90b: applicera popupens val även vid dubblett
            if extras:
                apply_extras(store, existing, extras)
                if save and hasattr(store, "save"):
                    with suppress(Exception):
                        result["saved"] = bool(store.save())
            logger.info(
                f"{LOG_PREFIX} DUBLETT (.eml): {mid} är redan importerad som "
                f"{existing!r} — ingen ny uppgift"
                + (f" (uppdaterade: {', '.join(extras)})" if extras else "")
            )
            return result

    info: Dict[str, Any] = {}
    try:
        task_id = import_email(filepath, store, data_dir, info=info)
    except Exception as e:
        result["error"] = f"import_email kraschade: {e}"
        logger.error(f"{LOG_PREFIX} import_email-fel: {e}", exc_info=True)
        return result

    if not task_id:
        result["error"] = "import_email misslyckades (format/storlek?)"
        return result

    duplicate = bool(info.get("duplicate"))
    result.update(
        ok=True, task_id=task_id, duplicate=duplicate,
        title=(store.find_task(task_id) or {}).get("title", filepath.name)
        if hasattr(store, "find_task") else filepath.name,
    )

    # NY v7-fix90b: användarens val från Thunderbird-popupen
    if not duplicate:
        apply_extras(store, task_id, extras)

    # Registrera i bryggans dedup (message_id från kortets metadata)
    try:
        task = store.find_task(task_id) if hasattr(store, "find_task") else None
        task = task or {}
        key = normalize_message_id(task.get("email_message_id", "")) or mid
        if not key:
            key = f"hash:{hashlib.md5(filepath.read_bytes()[:65536]).hexdigest()}"
        if not duplicate:
            registry.register(
                key, task_id,
                {"title": task.get("title", filepath.name),
                 "from": task.get("email_from", ""), "source": source,
                 "file": filepath.name},
            )
        result["title"] = str(task.get("title", filepath.name))
        result["priority"] = str(task.get("priority", "medium"))
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} dedup-registrering misslyckades: {e}")

    if save and not duplicate and hasattr(store, "save"):
        try:
            result["saved"] = bool(store.save())
        except Exception as e:
            logger.error(f"{LOG_PREFIX} save misslyckades: {e}")

    try:
        result["count"] = int(store.count()[0]) if hasattr(store, "count") else 0
    except Exception:
        pass
    return result


def import_eml_bytes(
    store: Any,
    data_dir: Path,
    raw: bytes,
    filename: str = "thunderbird-meddelande.eml",
    *,
    registry: Optional[DedupRegistry] = None,
    source: str = "thunderbird",
    save: bool = True,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Importera RÅ e-postdata (.eml) som skickats från Thunderbird-tillägget.

    Skriver till en temp-fil, kör samma import som allt annat (original
    sparas i data/emails/) och städar temp-filen.
    """
    data_dir = Path(data_dir)
    ensure_dirs(data_dir)
    tmp_path: Optional[Path] = None
    try:
        if not raw:
            return {"ok": False, "task_id": None, "duplicate": False,
                    "title": "", "priority": "medium", "saved": False,
                    "count": 0, "error": "tom e-postdata"}
        if len(raw) > MAX_EML_BODY:
            return {"ok": False, "task_id": None, "duplicate": False,
                    "title": "", "priority": "medium", "saved": False,
                    "count": 0,
                    "error": f"mailet är för stort ({len(raw) // 1024} kB)"}
        suffix = Path(filename).suffix.lower()
        if suffix not in (".eml", ".msg"):
            suffix = ".eml"
        tmp_dir = bridge_dir(data_dir) / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=suffix, dir=str(tmp_dir))
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        tmp_path = Path(tmp_name)
        logger.info(
            f"{LOG_PREFIX} tog emot {len(raw)} byte rå-e-post från "
            f"Thunderbird ({filename!r})"
        )
        return import_email_file(
            store, data_dir, tmp_path,
            registry=registry, source=source, save=save, extras=extras,
        )
    except Exception as e:
        logger.error(f"{LOG_PREFIX} import_eml_bytes misslyckades: {e}",
                     exc_info=True)
        return {"ok": False, "task_id": None, "duplicate": False,
                "title": "", "priority": "medium", "saved": False,
                "count": 0, "error": str(e)}
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


# ===========================================================================
# HTTP-BRYGGAN (localhost-server för Thunderbird-tillägget)
# ===========================================================================

class _BridgeHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer med daemon-trådar + delad state."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: Tuple[str, int], handler: type, service: "MailBridgeServer"):
        self.service = service
        super().__init__(addr, handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Undertryck tysta traceback-stormar (t.ex. när klienten klipper av)."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            logger.debug(f"{LOG_PREFIX} klient avbröt anslutningen: {exc}")
            return
        logger.warning(f"{LOG_PREFIX} HTTP-fel: {exc}")


class _BridgeHandler(BaseHTTPRequestHandler):
    """Hanterar alla bryggans endpointar. Se modulens docstring för API:t."""

    server_version = f"TaskBord-MailBridge/{BRIDGE_VERSION.split()[0]}"
    protocol_version = "HTTP/1.1"

    # -------------------------------------------------------------- utils
    @property
    def service(self) -> "MailBridgeServer":
        return self.server.service        # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Skicka HTTP-loggen till appens logger (inte till stderr)."""
        logger.debug(f"{LOG_PREFIX} {self.address_string()} {fmt % args}")

    def _cors_headers(self) -> None:
        """CORS så att Thunderbird-tillägget kan prata med bryggan."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, {TOKEN_HEADER}, X-TaskBord-Extra, X-Requested-With",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _send_empty(self, status: int = 204) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self._cors_headers()
        self.end_headers()

    def _query(self) -> Dict[str, str]:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        self._path_only = parsed.path.rstrip("/") or "/"
        return {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def _token_from_request(self, query: Dict[str, str]) -> str:
        tok = self.headers.get(TOKEN_HEADER, "")
        if not tok:
            tok = query.get("token", "")
        return tok.strip()

    def _auth_ok(self, query: Dict[str, str]) -> bool:
        expected = self.service.token
        got = self._token_from_request(query)
        if not expected:
            return False
        try:
            return secrets.compare_digest(expected, got)
        except Exception:
            return False

    def _drain_unread_body(self) -> None:
        """
        Läs bort en POST-kropp som handlern inte läste (t.ex. vid 401 fel token).
        Annars tolkas kroppen som nästa förfrågan på samma keep-alive-anslutning och
        nästa (korrekta) anrop får ett kryptiskt HTTP 400.
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return
        if length > MAX_EML_BODY:
            self.close_connection = True
            return
        remaining = length
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except Exception:
            self.close_connection = True

    def _read_body(self, limit: int) -> bytes:
        self._body_read = True
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        if length > limit:
            raise ValueError(
                f"för stor förfrågan ({length} byte > {limit} byte)"
            )
        chunks: List[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    # ---------------------------------------------------------- HTTP verbs
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_empty(204)

    def do_GET(self) -> None:  # noqa: N802
        query = self._query()
        path = self._path_only
        try:
            if path in ("/", "/status"):
                self._send_html(self.service.status_page_html())
                return
            if path == "/health":
                # Ingen token: används för att upptäcka att appen körs
                self._send_json(self.service.health_payload())
                return
            if path == "/favicon.ico":
                self._send_empty(204)
                return
            if path == "/tasks":
                if not self._auth_ok(query):
                    self._send_json({"ok": False, "error": "ogiltig token"}, 401)
                    return
                self._send_json(self.service.tasks_payload(query))
                return
            if path == "/imported":
                if not self._auth_ok(query):
                    self._send_json({"ok": False, "error": "ogiltig token"}, 401)
                    return
                mid = sanitize_text(
                    query.get("message_id") or query.get("id"), 300
                )
                task_id = (
                    self.service.registry.find_alive(mid.strip("<>"))
                    if mid else None
                )
                self._send_json(
                    {"ok": True, "imported": bool(task_id), "task_id": task_id}
                )
                return
            if path == "/settings":
                if not self._auth_ok(query):
                    self._send_json({"ok": False, "error": "ogiltig token"}, 401)
                    return
                self._send_json(
                    {"ok": True, "config": self.service.config_payload()}
                )
                return
            self._send_json({"ok": False, "error": f"okänd sökväg: {path}"}, 404)
        except Exception as e:
            logger.error(f"{LOG_PREFIX} GET {path} misslyckades: {e}",
                         exc_info=True)
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        self._body_read = False
        try:
            self._do_post()
        finally:
            if not self._body_read:
                self._drain_unread_body()

    def _do_post(self) -> None:
        query = self._query()
        path = self._path_only
        try:
            if not self._auth_ok(query):
                logger.warning(
                    f"{LOG_PREFIX} nekad förfrågan ({path}) — fel/saknad token"
                )
                self._send_json(
                    {
                        "ok": False,
                        "error": (
                            "Ogiltig token. Kopiera inställningarna från "
                            "TaskBord: tray-menyn → 📧 E-post & Thunderbird."
                        ),
                    },
                    401,
                )
                return

            if path == "/task":
                raw = self._read_body(MAX_JSON_BODY)
                payload = self._parse_payload(raw)
                if payload is None:
                    self._send_json(
                        {"ok": False, "error": "ogiltig JSON-payload"}, 400
                    )
                    return
                result = self.service.create_tasks(payload, source="bridge")
                self._send_json(result, 200 if result.get("ok") else 500)
                return

            if path == "/eml":
                raw = self._read_body(MAX_EML_BODY)
                if not raw:
                    self._send_json(
                        {"ok": False, "error": "tom e-postdata"}, 400
                    )
                    return
                result = self.service.import_raw_email(
                    raw,
                    filename="thunderbird-meddelande.eml",
                    extras=self._extras_from_request(query),
                )
                self._send_json(result, 200 if result.get("ok") else 500)
                return

            self._send_json({"ok": False, "error": f"okänd sökväg: {path}"}, 404)
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 413)
        except Exception as e:
            logger.error(f"{LOG_PREFIX} POST {path} misslyckades: {e}",
                         exc_info=True)
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _extras_from_request(self, query: Dict[str, str]) -> Dict[str, Any]:
        """
        Extraval vid POST /eml: prioritet, förfallodatum, taggar, titel, note.

        Kan komma som query-parametrar (?priority=high&due_date=imorgon) eller
        som JSON i headern X-TaskBord-Extra (headern vinner).
        """
        extras: Dict[str, Any] = {}
        for key in ("priority", "due_date", "tags", "title", "note"):
            if query.get(key):
                extras[key] = query[key]
        header = self.headers.get("X-TaskBord-Extra", "").strip()
        if header:
            try:
                data = json.loads(header)
                if isinstance(data, dict):
                    extras.update(data)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} X-TaskBord-Extra ogiltig: {e}")
        return extras

    @staticmethod
    def _parse_payload(raw: bytes) -> Optional[Dict[str, Any]]:
        """JSON-body → dict. Tillåter även en lista (batch)."""
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} JSON-fel: {e}")
            return None
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"_batch": data}
        return None


class MailBridgeServer:
    """
    Lokal HTTP-server som tar emot mail från Thunderbird-tillägget.

    Anropas av main.pyw (via MailBridgeService). Lyssnar på 127.0.0.1,
    kräver token, och skapar uppgifter via create_task_from_payload() —
    som sparar till JSON direkt.
    """

    def __init__(
        self,
        store: Any,
        data_dir: Path,
        *,
        port: int = DEFAULT_PORT,
        token: str = "",
        version: str = "",
        on_import: Optional[Callable[[Dict[str, Any]], None]] = None,
        allow_port_scan: bool = True,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.requested_port = int(port or DEFAULT_PORT)
        self.port = 0
        self.version = version
        self.on_import = on_import
        self.allow_port_scan = allow_port_scan
        ensure_dirs(self.data_dir)
        self.token = token or load_token(self.data_dir)
        self.registry = DedupRegistry(self.data_dir, store)

        self._httpd: Optional[_BridgeHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Statistik (sparas i bridge_status.json)
        self.started_at: str = ""
        self.imports: int = 0
        self.duplicates: int = 0
        self.errors: int = 0
        self.last_import: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- start
    def start(self) -> bool:
        """Starta servern. Returnerar True om den kör."""
        if self._running:
            return True
        try:
            self._httpd = self._bind_server()
            if self._httpd is None:
                self.errors += 1
                return False
            self._running = True
            self.started_at = _now_iso()
            self._thread = threading.Thread(
                target=self._serve_forever,
                name="MailBridgeHTTP",
                daemon=True,
            )
            self._thread.start()
            self._write_status()
            logger.info(
                f"{LOG_PREFIX} ✓ bryggan lyssnar på http://{HOST}:{self.port} "
                f"(token: {self.token[:6]}…{self.token[-4:]}, "
                f"tillägg: {len(self.registry.all_entries())} tidigare mail)"
            )
            return True
        except Exception as e:
            self.errors += 1
            logger.error(f"{LOG_PREFIX} kunde inte starta bryggan: {e}",
                         exc_info=True)
            return False

    def _bind_server(self) -> Optional[_BridgeHTTPServer]:
        """Binda porten (provar nästa port om den är upptagen)."""
        attempts = PORT_SCAN_ATTEMPTS if self.allow_port_scan else 1
        # FIX v8: är porten upptagen av en ANNAN TaskBord ska vi inte starta en andra brygga
        # på nästa port — då finns två appar som tävlar om mailen. Den som kör först äger den.
        try:
            from core.single_instance import probe_taskbord
        except Exception:
            try:
                from single_instance import probe_taskbord  # type: ignore
            except Exception:
                probe_taskbord = None  # type: ignore
        if probe_taskbord is not None and self.requested_port and probe_taskbord(self.requested_port):
            logger.error(
                f"{LOG_PREFIX} port {self.requested_port} används redan av en annan körande "
                f"TaskBord — startar ingen andra brygga (en instans åt gången)"
            )
            return None
        for offset in range(attempts):
            port = self.requested_port + offset
            if port > 65535:
                break
            if offset and not _port_is_free(port):
                continue
            try:
                srv = _BridgeHTTPServer((HOST, port), _BridgeHandler, self)
            except OSError as e:
                logger.debug(
                    f"{LOG_PREFIX} port {port} upptagen ({e}) — provar nästa"
                )
                continue
            self.port = int(srv.server_address[1])
            if offset:
                logger.warning(
                    f"{LOG_PREFIX} port {self.requested_port} var upptagen — "
                    f"bryggan använder {self.port} i stället"
                )
            return srv
        logger.error(
            f"{LOG_PREFIX} hittade ingen ledig port "
            f"({self.requested_port}–{self.requested_port + attempts - 1})"
        )
        return None

    def _serve_forever(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        try:
            httpd.serve_forever(poll_interval=0.5)
        except Exception as e:
            if self._running:
                logger.error(f"{LOG_PREFIX} server-loop avslutades: {e}",
                             exc_info=True)
                self.errors += 1
        finally:
            logger.info(f"{LOG_PREFIX} server-loop stoppad")

    def stop(self) -> None:
        """Stäng servern (idempotent)."""
        self._running = False
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} stängning: {e}")
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._write_status()
        logger.info(f"{LOG_PREFIX} bryggan stoppad")

    @property
    def running(self) -> bool:
        return bool(self._running and self._httpd is not None)

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port or self.requested_port}"

    # ------------------------------------------------------------- endpointar
    def health_payload(self) -> Dict[str, Any]:
        """GET /health — ingen token behövs (används för att hitta appen)."""
        tasks = 0
        try:
            if hasattr(self.store, "count"):
                tasks = int(self.store.count()[0])
        except Exception:
            pass
        return {
            "ok": True,
            "app": APP_NAME,
            "bridge_version": BRIDGE_VERSION,
            "app_version": self.version,
            "port": self.port or self.requested_port,
            "url": self.url,
            "needs_token": True,
            "tasks": tasks,
            "imports": self.imports,
            "uptime_since": self.started_at,
        }

    def tasks_payload(self, query: Dict[str, str]) -> Dict[str, Any]:
        """GET /tasks — aktiva uppgifter (för dedup/sök i tillägget)."""
        limit = 50
        try:
            limit = max(1, min(500, int(query.get("limit", "50"))))
        except Exception:
            pass
        out: List[Dict[str, Any]] = []
        try:
            for task in (self.store.active_tasks() if hasattr(self.store, "active_tasks") else []):
                out.append(
                    {
                        "id": task.get("id"),
                        "title": task.get("title"),
                        "priority": task.get("priority"),
                        "due_date": task.get("due_date"),
                        "tags": task.get("tags", []),
                        "done": task.get("done", False),
                    }
                )
                if len(out) >= limit:
                    break
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} tasks_payload: {e}")
        return {"ok": True, "count": len(out), "tasks": out}

    def config_payload(self) -> Dict[str, Any]:
        """Inställningar till tillägget (url + token)."""
        return extension_config(self.data_dir, self.port or self.requested_port,
                               self.token)

    def create_tasks(self, payload: Dict[str, Any], source: str = "bridge") -> Dict[str, Any]:
        """
        Skapa en (eller flera, vid '_batch') uppgifter av en payload.
        Anropas av POST /task och av inkorgsmappen (.json-filer).
        """
        batch = payload.get("_batch")
        if isinstance(batch, list):
            results = [
                create_task_from_payload(
                    self.store, self.data_dir, item, registry=self.registry,
                    source=source,
                )
                for item in batch
                if isinstance(item, dict)
            ]
            created = [r for r in results if r.get("ok") and not r.get("duplicate")]
            dupes = [r for r in results if r.get("duplicate")]
            failed = [r for r in results if not r.get("ok")]
            self._register_stats(results)
            return {
                "ok": bool(created) or not failed,
                "batch": True,
                "created": len(created),
                "duplicates": len(dupes),
                "failed": len(failed),
                "task_ids": [r.get("task_id") for r in results if r.get("task_id")],
                "results": results,
            }
        result = create_task_from_payload(
            self.store, self.data_dir, payload,
            registry=self.registry, source=source,
        )
        self._register_stats([result])
        return result

    def import_raw_email(
        self,
        raw: bytes,
        filename: str = "meddelande.eml",
        extras: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Skapa uppgift av RÅ e-postdata (POST /eml)."""
        result = import_eml_bytes(
            self.store, self.data_dir, raw, filename=filename,
            registry=self.registry, source="thunderbird", extras=extras,
        )
        self._register_stats([result])
        return result

    # -------------------------------------------------------------- statistik
    def _register_stats(self, results: List[Dict[str, Any]]) -> None:
        """Uppdatera räknare + skriv status-JSON + notifiera GUI:t."""
        for res in results:
            if res.get("ok") and res.get("duplicate"):
                self.duplicates += 1
            elif res.get("ok"):
                self.imports += 1
                self.last_import = {
                    "task_id": res.get("task_id"),
                    "title": res.get("title", ""),
                    "priority": res.get("priority", ""),
                    "when": _now_iso(),
                }
            else:
                self.errors += 1
        self._write_status()
        if self.on_import is not None:
            try:
                self.on_import(
                    {
                        "source": "bridge",
                        "results": [
                            {
                                "ok": r.get("ok"),
                                "task_id": r.get("task_id"),
                                "title": r.get("title", ""),
                                "duplicate": bool(r.get("duplicate")),
                                "error": r.get("error"),
                            }
                            for r in results
                        ],
                    }
                )
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} on_import-callback: {e}")

    def _write_status(self) -> None:
        """Skriv data/mail_bridge/bridge_status.json (för support/diagnostik)."""
        _atomic_write_json(
            bridge_dir(self.data_dir) / STATUS_FILENAME,
            {
                "app": APP_NAME,
                "bridge_version": BRIDGE_VERSION,
                "running": self.running,
                "host": HOST,
                "port": self.port or self.requested_port,
                "url": self.url,
                "started_at": self.started_at,
                "updated_at": _now_iso(),
                "imports": self.imports,
                "duplicates": self.duplicates,
                "errors": self.errors,
                "last_import": self.last_import,
                "dedup_entries": self.registry.count(),
            },
        )

    # ------------------------------------------------------------ statussida
    def status_page_html(self) -> str:
        """Enkel svensk statussida (kan öppnas i webbläsaren för test)."""
        h = self.health_payload()
        latest = self.last_import or {}
        rows = "".join(
            f"<tr><td>{k}</td><td><b>{v}</b></td></tr>"
            for k, v in (
                ("Status", "🟢 körs" if self.running else "🔴 stoppad"),
                ("Adress", h["url"]),
                ("Port", h["port"]),
                ("TaskBord-version", h["app_version"] or "?"),
                ("Brygga", BRIDGE_VERSION),
                ("Aktiva uppgifter", h["tasks"]),
                ("Importerade mail (denna körning)", self.imports),
                ("Dubletter stoppade", self.duplicates),
                ("Fel", self.errors),
                ("Startad", self.started_at or "-"),
                ("Senaste import", f"{latest.get('title', '-')} {latest.get('when', '')}"),
                ("Dedup-register (JSON)", f"{self.registry.count()} poster"),
            )
        )
        return f"""<!DOCTYPE html>
<html lang="sv"><head><meta charset="utf-8">
<title>TaskBord e-postbrygga</title>
<style>
 body{{font-family:Segoe UI,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:32px}}
 .card{{max-width:720px;margin:auto;background:#1e293b;border-radius:14px;padding:24px;
        box-shadow:0 10px 40px rgba(0,0,0,.45)}}
 h1{{margin:0 0 4px;font-size:22px}} p.sub{{margin:0 0 18px;color:#94a3b8}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 td{{padding:6px 8px;border-bottom:1px solid #334155}} td:first-child{{color:#94a3b8;width:45%}}
 code{{background:#0f172a;padding:2px 6px;border-radius:6px}}
 .hint{{margin-top:18px;font-size:13px;color:#94a3b8;line-height:1.5}}
</style></head><body><div class="card">
<h1>📧 TaskBord — e-postbrygga</h1>
<p class="sub">Bryggan tar emot mail från Thunderbird-tillägget och skapar uppgifter.
Uppgifterna sparas i <code>data/active.json</code> och finns kvar efter omstart.</p>
<table>{rows}</table>
<div class="hint">
<b>Testa utan Thunderbird:</b> kör i PowerShell<br>
<code>$t = Get-Content .\\data\\mail_bridge\\token.txt</code><br>
<code>Invoke-RestMethod -Method Post -Uri {h['url']}/task -Headers @{{"{TOKEN_HEADER}"=$t}} -ContentType "application/json" -Body '{{"title":"Test från bryggan","note":"Fungerar!","priority":"high"}}'</code>
</div>
</div></body></html>"""


def _port_is_free(port: int) -> bool:
    """Snabb koll om porten är ledig (innan vi försöker binda)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.2)
        return s.connect_ex((HOST, port)) != 0
    except Exception:
        return True
    finally:
        try:
            s.close()
        except Exception:
            pass


# ===========================================================================
# INKORGSMAPPEN (data/inbox/) — fungerar även om appen varit avstängd
# ===========================================================================

class InboxWatcher(threading.Thread):
    """
    Bevakar `data/inbox/` och importerar .eml/.msg/.json automatiskt.

    Filer flyttas till `inbox/imported/` när de är importerade och till
    `inbox/failed/` om de inte gick att läsa (så att inget tappas bort
    eller importeras i en evig loop).
    """

    def __init__(
        self,
        store: Any,
        data_dir: Path,
        *,
        poll_seconds: int = DEFAULT_INBOX_POLL_SEC,
        registry: Optional[DedupRegistry] = None,
        on_import: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        super().__init__(name="MailInboxWatcher", daemon=True)
        self.store = store
        self.data_dir = Path(data_dir)
        self.poll_seconds = max(1, int(poll_seconds or DEFAULT_INBOX_POLL_SEC))
        self.registry = registry or DedupRegistry(self.data_dir, store)
        self.on_import = on_import
        self.paths = ensure_dirs(self.data_dir)
        self.imports = 0
        self.duplicates = 0
        self.failures = 0
        self.last_check: str = ""
        self.last_error: str = ""
        self._stop_event = threading.Event()
        self._attempts: Dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- livscykel
    def stop(self) -> None:
        self._stop_event.set()

    @property
    def running(self) -> bool:
        return self.is_alive() and not self._stop_event.is_set()

    def run(self) -> None:
        logger.info(
            f"{LOG_PREFIX} inkorgsbevakning startad: {self.paths['inbox']} "
            f"(var {self.poll_seconds}:e sekund)"
        )
        # Vid start: importera allt som redan ligger där (appen var avstängd)
        self.scan_once()
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self.scan_once()
            except Exception as e:
                self.failures += 1
                self.last_error = str(e)
                logger.error(f"{LOG_PREFIX} scan-fel: {e}", exc_info=True)
        self._write_status()
        logger.info(f"{LOG_PREFIX} inkorgsbevakning stoppad")

    # ----------------------------------------------------------------- skanning
    def scan_once(self) -> int:
        """En genomsökning av inkorgsmappen. Returnerar antal importerade."""
        inbox = self.paths["inbox"]
        self.last_check = _now_iso()
        imported = 0
        candidates: List[Path] = []
        for pattern in ("*.eml", "*.msg", "*.json", "*.EML", "*.MSG"):
            try:
                candidates.extend(sorted(inbox.glob(pattern)))
            except Exception:
                pass
        for path in candidates:
            with self._lock:
                if path.name in self._attempts:
                    tries = self._attempts[path.name]
                else:
                    tries = 0
            if tries >= INBOX_MAX_ATTEMPTS:
                self._move(path, "failed")
                with self._lock:
                    self._attempts.pop(path.name, None)
                continue
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if age < INBOX_MIN_AGE_SEC:
                continue   # filen skrivs fortfarande — vänta en runda
            ok = self._process(path)
            if ok:
                self._move(path, "imported")
                with self._lock:
                    self._attempts.pop(path.name, None)
                imported += 1
            else:
                with self._lock:
                    self._attempts[path.name] = tries + 1
                if self._attempts[path.name] >= INBOX_MAX_ATTEMPTS:
                    self._move(path, "failed")
                    with self._lock:
                        self._attempts.pop(path.name, None)
        if imported:
            self._write_status()
        return imported

    def _process(self, path: Path) -> bool:
        """Importera en fil. True = klar (även dublett räknas som klar)."""
        suffix = path.suffix.lower()
        try:
            if suffix in (".eml", ".msg"):
                res = import_email_file(
                    self.store, self.data_dir, path,
                    registry=self.registry, source="inbox", save=True,
                )
            elif suffix == ".json":
                data = _read_json(path, None)
                if data is None:
                    logger.warning(
                        f"{LOG_PREFIX} inkorg: {path.name} är inte giltig JSON"
                    )
                    return False
                payload = data if isinstance(data, dict) else {"_batch": data}
                res = self._service_create(payload)
            else:
                return False
        except Exception as e:
            self.last_error = str(e)
            logger.error(
                f"{LOG_PREFIX} inkorg: {path.name} kunde inte importeras: {e}",
                exc_info=True,
            )
            return False

        if res.get("ok") and res.get("duplicate"):
            self.duplicates += 1
        elif res.get("ok"):
            self.imports += 1
        else:
            self.failures += 1
            self.last_error = str(res.get("error"))
            logger.warning(
                f"{LOG_PREFIX} inkorg: {path.name} misslyckades: "
                f"{res.get('error')}"
            )
            return False
        if self.on_import is not None:
            try:
                self.on_import(
                    {"source": "inbox", "file": path.name, "results": [res]}
                )
            except Exception:
                pass
        return True

    def _service_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Skapa uppgifter från en .json-fil i inkorgen (samma kodväg)."""
        batch = payload.get("_batch")
        if isinstance(batch, list):
            results = [
                create_task_from_payload(
                    self.store, self.data_dir, item,
                    registry=self.registry, source="inbox",
                )
                for item in batch
                if isinstance(item, dict)
            ]
            ok = all(r.get("ok") for r in results) and bool(results)
            return {
                "ok": ok, "duplicate": all(r.get("duplicate") for r in results),
                "task_id": results[0].get("task_id") if results else None,
                "title": results[0].get("title", "") if results else "",
                "error": None if ok else "några uppgifter misslyckades",
            }
        return create_task_from_payload(
            self.store, self.data_dir, payload,
            registry=self.registry, source="inbox",
        )

    def _move(self, path: Path, kind: str) -> None:
        """Flytta filen till imported/ eller failed/ (kvittens)."""
        target_dir = self.paths["inbox_imported" if kind == "imported" else "inbox_failed"]
        try:
            target = target_dir / path.name
            if target.exists():
                stamp = datetime.now().strftime("%H%M%S")
                target = target_dir / f"{path.stem}_{stamp}{path.suffix}"
            shutil.move(str(path), str(target))
            logger.info(
                f"{LOG_PREFIX} inkorg: {path.name} → {target_dir.name}/"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} kunde inte flytta {path.name}: {e}"
            )

    def _write_status(self) -> None:
        _atomic_write_json(
            self.paths["bridge"] / "inbox_status.json",
            {
                "running": self.running,
                "watched": str(self.paths["inbox"]),
                "poll_seconds": self.poll_seconds,
                "imports": self.imports,
                "duplicates": self.duplicates,
                "failures": self.failures,
                "last_check": self.last_check,
                "last_error": self.last_error,
                "updated_at": _now_iso(),
            },
        )

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "watched": str(self.paths["inbox"]),
            "poll_seconds": self.poll_seconds,
            "imports": self.imports,
            "duplicates": self.duplicates,
            "failures": self.failures,
            "last_check": self.last_check,
            "last_error": self.last_error,
        }


# ===========================================================================
# SERVICE (det main.pyw använder — brygga + inkorg i ett paket)
# ===========================================================================

class MailBridgeService:
    """
    Samlad tjänst: HTTP-brygga (tillägget) + inkorgsbevakning (mappen).

    Exempel (main.pyw):
        svc = MailBridgeService(store, Path(settings.data_dir()),
                                port=8765, version=APP_VERSION,
                                on_event=self._mail_bridge_notify)
        svc.start()
        ...
        svc.stop()
    """

    def __init__(
        self,
        store: Any,
        data_dir: Path,
        *,
        port: int = DEFAULT_PORT,
        token: str = "",
        version: str = "",
        http_enabled: bool = True,
        watch_enabled: bool = True,
        poll_seconds: int = DEFAULT_INBOX_POLL_SEC,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.port = int(port or DEFAULT_PORT)
        self.version = version
        self.http_enabled = bool(http_enabled)
        self.watch_enabled = bool(watch_enabled)
        self.poll_seconds = int(poll_seconds or DEFAULT_INBOX_POLL_SEC)
        self.on_event = on_event

        self.paths = ensure_dirs(self.data_dir)
        self.token = token or load_token(self.data_dir)
        self.registry = DedupRegistry(self.data_dir, store)
        self.server = MailBridgeServer(
            store, self.data_dir,
            port=self.port, token=self.token, version=version,
            on_import=on_event,
        )
        self.watcher: Optional[InboxWatcher] = None

    # ------------------------------------------------------------- livscykel
    def start(self) -> Dict[str, Any]:
        """Starta brygga och/eller inkorgsbevakning enligt inställningarna."""
        started_http = False
        if self.http_enabled:
            started_http = self.server.start()
            if started_http:
                self.port = self.server.port
                extension_config(self.data_dir, self.port, self.token)
        if self.watch_enabled:
            self.start_watcher()
        status = self.status()
        logger.info(
            f"{LOG_PREFIX} tjänst startad: http={'ja' if started_http else 'nej'} "
            f"(port {self.port}), inkorg="
            f"{'ja' if (self.watcher and self.watcher.running) else 'nej'}"
        )
        return status

    def stop(self) -> None:
        """Stoppa allt (idempotent) — anropas vid avslut."""
        self.stop_watcher()
        try:
            self.server.stop()
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} server-stop: {e}")

    def start_watcher(self) -> bool:
        """Starta inkorgsbevakningen."""
        if self.watcher is not None and self.watcher.running:
            return True
        try:
            self.watcher = InboxWatcher(
                self.store, self.data_dir,
                poll_seconds=self.poll_seconds,
                registry=self.registry,
                on_import=self.on_event,
            )
            self.watcher.start()
            return True
        except Exception as e:
            logger.error(f"{LOG_PREFIX} inkorgsbevakning kunde ej startas: {e}",
                         exc_info=True)
            return False

    def stop_watcher(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None

    # --------------------------------------------------------------- status
    @property
    def http_running(self) -> bool:
        return self.server.running

    @property
    def watch_running(self) -> bool:
        return bool(self.watcher is not None and self.watcher.running)

    @property
    def url(self) -> str:
        return self.server.url

    def config_payload(self) -> Dict[str, Any]:
        """Inställningar för tillägget (skrivs även till JSON-fil)."""
        return extension_config(self.data_dir, self.server.port or self.port,
                                self.token)

    def rotate_token(self) -> str:
        """Skapa en ny token (tillägget måste uppdateras efteråt)."""
        self.token = secrets.token_hex(TOKEN_LENGTH // 2)
        save_token(self.data_dir, self.token)
        self.server.token = self.token
        self.config_payload()
        logger.info(f"{LOG_PREFIX} token roterad (ny nyckel skapad)")
        return self.token

    def status(self) -> Dict[str, Any]:
        """Komplett status för tray-menyn/dialogen."""
        health = self.server.health_payload()
        return {
            "http_enabled": self.http_enabled,
            "http_running": self.http_running,
            "watch_enabled": self.watch_enabled,
            "watch_running": self.watch_running,
            "port": self.server.port or self.port,
            "url": self.url,
            "token": self.token,
            "imports": self.server.imports + (
                self.watcher.imports if self.watcher else 0
            ),
            "duplicates": self.server.duplicates + (
                self.watcher.duplicates if self.watcher else 0
            ),
            "errors": self.server.errors + (
                self.watcher.failures if self.watcher else 0
            ),
            "task_count": health.get("tasks", 0),
            "inbox": str(self.paths["inbox"]),
            "data_dir": str(self.data_dir),
            "token_file": str(bridge_dir(self.data_dir) / TOKEN_FILENAME),
            "registry_file": str(
                bridge_dir(self.data_dir) / REGISTRY_FILENAME
            ),
            "config_file": str(
                bridge_dir(self.data_dir) / CONFIG_FILENAME
            ),
            "last_import": self.server.last_import,
            "dedup_entries": self.registry.count(),
            "watcher": self.watcher.status() if self.watcher else None,
        }

    def status_text(self) -> str:
        """Kort svensk statustext (tray-menyn)."""
        s = self.status()
        dot = "🟢" if s["http_running"] else "🔴"
        inbox = "🟢" if s["watch_running"] else "⚪"
        return (
            f"Brygga: {dot} port {s['port']} • Inkorg: {inbox} • "
            f"{s['imports']} mail importerade"
        )


# ===========================================================================
# SJÄLVTEST — körs: python -m core.mail_bridge  (eller --selftest)
# ===========================================================================

def _selftest() -> int:
    """
    Testar hela kedjan utan Thunderbird: HTTP → uppgift i JSON → dedup →
    rå .eml → inkorgsmapp. Returnerar 0 om allt gick bra.
    """
    import tempfile
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.store import TaskStore

    print("=" * 66)
    print(f"mail_bridge.py — självtest {BRIDGE_VERSION}")
    print("=" * 66)
    tmp = Path(tempfile.mkdtemp(prefix="taskbord_bridge_"))
    data_dir = tmp / "data"
    store = TaskStore(data_dir_override=str(data_dir))
    events: List[Dict[str, Any]] = []
    svc = MailBridgeService(
        store, data_dir, port=8799, version="selftest",
        http_enabled=True, watch_enabled=True, poll_seconds=1,
        on_event=lambda evt: events.append(evt),
    )
    status = svc.start()
    assert svc.http_running, "bryggan startade inte"
    base = svc.url
    token = svc.token
    print(f"  ✓ brygga startad: {base} (token {token[:6]}…)")
    print(f"  ✓ inkorgsbevakning: {status['watch_running']}")

    def post(path: str, data: bytes, ctype: str, tok: str = token) -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(
            base + path, data=data, method="POST",
            headers={"Content-Type": ctype, TOKEN_HEADER: tok},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def get(path: str, tok: str = "") -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(
            base + path, headers={TOKEN_HEADER: tok} if tok else {}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # 1. /health utan token
    code, health = get("/health")
    assert code == 200 and health["ok"] and health["app"] == "TaskBord"
    print(f"  ✓ GET /health: {health['app']} {health['bridge_version']}")

    # 2. POST /task utan token → 401
    code, _ = post("/task", b'{"title":"hack"}', "application/json", tok="fel")
    assert code == 401, f"förväntade 401, fick {code}"
    print("  ✓ POST /task utan giltig token → 401 (skyddat)")

    # 3. POST /task med token → uppgift skapad + sparad i JSON
    payload = {
        "subject": "Brådskande: lämna rapport imorgon",
        "from": "Anna Andersson <anna@example.com>",
        "body": "Hej! Kan du skicka rapporten ASAP? /Anna",
        "message_id": "<selftest-1@example.com>",
        "date": "2026-10-12T09:00:00+02:00",
        "tags": ["jobb"],
        "source": "thunderbird",
    }
    code, res = post("/task", json.dumps(payload).encode("utf-8"),
                     "application/json")
    assert code == 200 and res["ok"], f"import misslyckades: {res}"
    task_id = res["task_id"]
    assert res["priority"] == "high", f"prioritet: {res['priority']}"
    print(f"  ✓ POST /task → uppgift {task_id!r} '{res['title'][:40]}' "
          f"(prio={res['priority']}, sparad={res['saved']})")
    assert res["saved"], "uppgiften sparades inte till JSON direkt!"

    # 4. JSON-filen på disk innehåller uppgiften (kravet!)
    active_json = json.loads((data_dir / "active.json").read_text("utf-8"))
    titles = [t["title"] for t in active_json["tasks"]]
    assert any("Brådskande" in t for t in titles), titles
    print(f"  ✓ data/active.json innehåller uppgiften "
          f"({len(active_json['tasks'])} uppgift(er), schema v"
          f"{active_json.get('version')})")

    # 5. Dublett ska INTE skapa ny uppgift
    code, dup = post("/task", json.dumps(payload).encode("utf-8"),
                     "application/json")
    assert dup["ok"] and dup["duplicate"] and dup["task_id"] == task_id
    assert store.count()[0] == 1, store.count()
    print("  ✓ samma Message-ID igen → dublett, ingen ny uppgift")

    # 6. Dedup-registret ligger i JSON
    reg = json.loads((bridge_dir(data_dir) / REGISTRY_FILENAME).read_text("utf-8"))
    assert reg["count"] == 1 and reg["entries"], reg
    print(f"  ✓ data/mail_bridge/imported.json: {reg['count']} post(er)")

    # 7. POST /eml → original sparas i data/emails/
    eml = (
        "From: Bosse <bosse@example.com>\r\n"
        "To: Rickard <r@example.com>\r\n"
        "Subject: Möte på torsdag\r\n"
        "Message-ID: <selftest-2@example.com>\r\n"
        "Date: Mon, 12 Oct 2026 08:30:00 +0200\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Kan vi flytta mötet till fredag?\r\n"
    ).encode("utf-8")
    code, res2 = post("/eml", eml, "message/rfc822")
    assert code == 200 and res2["ok"], res2
    saved_eml = data_dir / "emails" / f"{res2['task_id']}.eml"
    assert saved_eml.is_file(), f"originalmail saknas: {saved_eml}"
    print(f"  ✓ POST /eml → uppgift {res2['task_id']!r}, original sparad "
          f"({saved_eml.name}, {saved_eml.stat().st_size} B)")

    # 8. GET /tasks + /imported
    code, tasks = get("/tasks", token)
    assert tasks["count"] == 2, tasks
    code, imp = get(f"/imported?message_id={payload['message_id']}", token)
    assert imp["imported"] and imp["task_id"] == task_id
    print(f"  ✓ GET /tasks → {tasks['count']} uppgifter, "
          f"GET /imported → imported={imp['imported']}")

    # 9. Inkorgsmappen: släpp en .eml → importeras + flyttas
    inbox_file = svc.paths["inbox"] / "fran_thunderbird.eml"
    inbox_file.write_bytes(eml.replace(b"selftest-2", b"selftest-3"))
    deadline = time.time() + 15
    moved = svc.paths["inbox_imported"] / inbox_file.name
    while time.time() < deadline and not moved.is_file():
        time.sleep(0.4)
    assert moved.is_file(), "inkorgsfilen importerades inte"
    assert store.count()[0] == 3, store.count()
    print("  ✓ data/inbox/*.eml → automatiskt importerad och flyttad till "
          "inbox/imported/")

    # 10. Status-filer + statustext
    st = json.loads((bridge_dir(data_dir) / STATUS_FILENAME).read_text("utf-8"))
    assert st["running"] and st["url"], st
    print(f"  ✓ bridge_status.json: {st['imports']} import(er), "
          f"{st['duplicates']} dublett(er), url={st['url']}")
    print(f"  ✓ statusrad: {svc.status_text()}")
    print(f"  ✓ notifieringar till GUI:t: {len(events)} st")

    # 11. NY v7-fix90b: extras (popupens prioritet/datum) på /eml
    eml2 = (
        "From: Cissi <cissi@example.com>\r\n"
        "Subject: Extra-test\r\n"
        "Message-ID: <selftest-4@example.com>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\nKropp\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/eml", data=eml2, method="POST",
        headers={
            "Content-Type": "message/rfc822",
            TOKEN_HEADER: token,
            "X-TaskBord-Extra": json.dumps(
                {"priority": "high", "due_date": "imorgon", "tags": ["kund"]}
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        res3 = json.loads(r.read().decode("utf-8"))
    t3 = store.find_task(res3["task_id"])
    assert t3["priority"] == "high" and t3["due_date"] and "kund" in t3["tags"], t3
    print(
        f"  ✓ X-TaskBord-Extra applicerades: prio={t3['priority']}, "
        f"datum={t3['due_date']}, taggar={t3['tags']}"
    )

    # 12. NY v7-fix90b: samma mail via JSON-vägen → DUBLETT (inte ny uppgift)
    before = store.count()[0]
    code, dup2 = post(
        "/task",
        json.dumps(
            {
                "subject": "Extra-test",
                "from": "Cissi <cissi@example.com>",
                "message_id": "selftest-4@example.com",   # utan <>
            }
        ).encode("utf-8"),
        "application/json",
    )
    assert dup2["duplicate"] and store.count()[0] == before, dup2
    print("  ✓ samma mail via JSON (utan <>) → dublett, ingen ny uppgift")

    # 13. Stoppa rent
    svc.stop()
    assert not svc.http_running
    print("  ✓ tjänsten stoppad utan fel")

    shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 66)
    print("✓ ALLA SJÄLVTESTER PASSERADE")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    try:
        sys.exit(_selftest())
    except AssertionError as e:
        print(f"✗ SJÄLVTEST MISSLYCKADES: {e}")
        sys.exit(1)
