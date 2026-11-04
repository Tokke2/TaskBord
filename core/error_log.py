# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
error_log.py — EN fil med alla fel för snabb felsökning: loggar/fel.log

Varför: felen ligger annars utspridda — todo_app.log (tusentals rader, där felen drunknar), update_watchdog.log
(egen process), window_failure_report.txt (nödrapport) och äldre roterade loggar. Den här filen samlar bara det som
gått fel, i tidsordning, kortfattat och med stacktrace — öppna den först.

Innehåll
  • LIVE: en logg-handler på root-loggern fångar varje WARNING/ERROR/CRITICAL från ALLA moduler (inkl. okända
    undantag via excepthook) och skriver dem direkt. Upprepade, likadana fel samlas ("upprepades N gånger").
  • IMPORT: vid start (och innan filen öppnas) hämtas fel från de andra loggarna: update_watchdog.log (nya rader,
    bara de som gäller fel/återställning), window_failure_report.txt (nödrapporten) samt — första gången —
    ERROR/CRITICAL ur todo_app.log och de roterade dagsfilerna. Positionerna sparas i loggar/fel_import.json så
    samma rad aldrig hamnar två gånger.
  • Token och mailadresser maskas (samma regler som felrapporten). Allt ligger i appmappen (loggar/).
  • Filen roteras vid ~1,5 MB (fel.log → fel.log.1; en säkerhetskopia behålls).

Format (en post):
    2026-10-30 12:01:02 | FEL      | Updater (updates.py:312) | [UPDATE] installation misslyckades: disk full
        Traceback (most recent call last): …
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from core import log_archive as _la
except Exception:  # pragma: no cover - körs som lös fil
    import log_archive as _la  # type: ignore

FILE_NAME = "fel.log"
STATE_NAME = "fel_import.json"
MAX_BYTES = 1_500_000
PLACEHOLDER = ("Inga fel loggade — bra!\n"
               "Här samlas alla varningar/fel från hela appen (och uppdateringsväktaren), nyaste längst ned.\n")
DEDUPE_WINDOW_SEC = 300
MAX_MESSAGE_CHARS = 4000
MAX_TRACE_LINES = 60

_LEVELS = {logging.WARNING: "VARNING", logging.ERROR: "FEL", logging.CRITICAL: "KRASCH"}

# Rader ur update_watchdog.log som är värda att samla (resten är rutinrader som "start:" och "klart:")
_WATCHDOG_KEYWORDS = ("återställer", "avslutades", "uteblev", "kunde inte", "misslyckad")
# Rader/trådar i todo_app.log som markerar fel
_LOG_LINE_RX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.,]\d+ \| (WARNING|ERROR|CRITICAL)\s*\|")
_LOG_LEVEL_FOR_BACKFILL = ("ERROR", "CRITICAL")   # varningar tas med bara live (annars blir historiken brusig)


def _redact(text: str) -> str:
    try:
        from core.bugreport import redact_text
        return redact_text(text)
    except Exception:
        try:
            from bugreport import redact_text  # type: ignore
            return redact_text(text)
        except Exception:
            return text


def _norm_key(level: int, name: str, msg: str) -> Tuple[int, str, str]:
    """Nyckel för att känna igen 'samma fel igen' (siffror/tider/sökvägar skiftar mellan upprepningar)."""
    return (level, name, re.sub(r"\d+", "#", msg)[:160])


class ErrorLogWriter:
    """Skriver poster till fel.log. Trådsäker, aldrig undantag utåt, loggar aldrig själv (ingen rekursion)."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / FILE_NAME
        self._lock = threading.RLock()
        self._session_written = False
        self._last_tidy = 0.0
        self._seen: Dict[Tuple[int, str, str], List[float]] = {}   # nyckel → [första/senaste skrivna ts, tyst antal, senaste ts]
        self.written = 0

    # -- låg nivå ------------------------------------------------------------------------------------------------
    def _rotate_if_needed(self) -> None:
        """Filen blir stor: gamla VARNINGAR arkiveras. Felposter ligger kvar tills de markerats som åtgärdade."""
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES and time.time() - self._last_tidy > 60:
                self._last_tidy = time.time()
                tidy(self.path.parent, cap_bytes=MAX_BYTES * 4, placeholder=False)
        except OSError:
            pass

    def _append(self, text: str) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            if not self._session_written:
                try:       # platshållartexten "Inga fel loggade" ska inte ligga kvar när det kommer ett fel
                    if self.path.exists() and self.path.stat().st_size == len(PLACEHOLDER.encode("utf-8")) \
                            and self.path.read_text(encoding="utf-8") == PLACEHOLDER:
                        self.path.unlink()
                except OSError:
                    pass
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                if not self._session_written:
                    f.write(f"\n═══ Ledgebord startad {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) ═══\n")
                    self._session_written = True
                f.write(text if text.endswith("\n") else text + "\n")
            self.written += 1
            return True
        except OSError:
            return False

    @staticmethod
    def format_entry(ts: float, level_label: str, where: str, message: str, trace: str = "") -> str:
        head = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))} | {level_label:<8} | {where} | "
        lines = _redact(message[:MAX_MESSAGE_CHARS]).splitlines() or [""]
        out = head + lines[0] + "\n" + "".join(f"    {l}\n" for l in lines[1:])
        if trace:
            tl = _redact(trace).rstrip().splitlines()
            if len(tl) > MAX_TRACE_LINES:
                tl = tl[:10] + [f"… ({len(tl) - MAX_TRACE_LINES} rader utelämnade) …"] + tl[-(MAX_TRACE_LINES - 10):]
            out += "".join(f"    {l}\n" for l in tl)
        return out

    # -- live ----------------------------------------------------------------------------------------------------
    def write_record(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelno if record.levelno in _LEVELS else (logging.CRITICAL if record.levelno > logging.CRITICAL else logging.ERROR if record.levelno > logging.WARNING else logging.WARNING)
            msg = record.getMessage()
            trace = ""
            if record.exc_info and record.exc_info[0] is not None:
                import traceback
                trace = "".join(traceback.format_exception(*record.exc_info))
            elif record.exc_text:
                trace = record.exc_text
            where = f"{record.name} ({record.filename}:{record.lineno})"
            now = record.created or time.time()
            with self._lock:
                key = _norm_key(level, record.name, msg)
                slot = self._seen.get(key)
                if slot is not None and now - slot[0] < DEDUPE_WINDOW_SEC:
                    slot[1] += 1
                    slot[2] = now
                    return
                if slot is not None and slot[1] > 0:
                    self._append(self._summary_line(slot, key))
                self._seen[key] = [now, 0, now]
                if len(self._seen) > 500:               # håll minnet nere
                    for k in sorted(self._seen, key=lambda x: self._seen[x][0])[:250]:
                        s = self._seen.pop(k)
                        if s[1] > 0:
                            self._append(self._summary_line(s, k))
                self._append(self.format_entry(now, _LEVELS[level], where, msg, trace))
        except Exception:
            pass

    @staticmethod
    def _summary_line(slot: List[float], key: Tuple[int, str, str]) -> str:
        return (f"    ↳ ovanstående upprepades {int(slot[1])} gång(er) till, senast "
                f"{time.strftime('%H:%M:%S', time.localtime(slot[2]))}\n")

    def flush_summaries(self) -> None:
        with self._lock:
            for key, slot in list(self._seen.items()):
                if slot[1] > 0:
                    self._append(self._summary_line(slot, key))
                    slot[1] = 0

    # -- import --------------------------------------------------------------------------------------------------
    def write_imported(self, ts: float, source: str, message: str, trace: str = "") -> None:
        with self._lock:
            self._append(self.format_entry(ts, "IMPORT", source, message, trace))


class ErrorLogHandler(logging.Handler):
    def __init__(self, writer: ErrorLogWriter):
        super().__init__(level=logging.WARNING)
        self.writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.writer.write_record(record)


_writer: Optional[ErrorLogWriter] = None
_handler: Optional[ErrorLogHandler] = None


def install(data_dir: Path, root: Optional[logging.Logger] = None) -> Optional[ErrorLogWriter]:
    """Lägger handlern på root-loggern (en gång). Anropas efter att övrig loggning ställts in."""
    global _writer, _handler
    try:
        root = root or logging.getLogger()
        if _handler is not None and _handler in root.handlers:
            return _writer
        _writer = ErrorLogWriter(Path(data_dir))
        _handler = ErrorLogHandler(_writer)
        root.addHandler(_handler)
        atexit.register(_writer.flush_summaries)
        return _writer
    except Exception:
        return None


def log_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


# ============================================================================================================
# IMPORT från andra loggar
# ============================================================================================================
def _load_state(data_dir: Path) -> dict:
    try:
        return json.loads((Path(data_dir) / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(data_dir: Path, state: dict) -> None:
    try:
        (Path(data_dir) / STATE_NAME).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _read_text(path: Path, start: int = 0, limit: int = 8 * 1024 * 1024) -> Tuple[str, int]:
    """Läser från byte `start` (max `limit`); returnerar (text, ny position)."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size - start > limit:
            start = size - limit
        f.seek(start)
        data = f.read()
    return data.decode("utf-8", errors="replace"), size


def parse_log_errors(text: str, levels: Tuple[str, ...] = _LOG_LEVEL_FOR_BACKFILL) -> List[Tuple[float, str, str, str]]:
    """Plockar poster (ts, nivå, rubrik, efterföljande rader/stacktrace) ur en todo_app.log-text."""
    out: List[Tuple[float, str, str, str]] = []
    cur: Optional[List] = None
    for line in text.splitlines():
        m = _LOG_LINE_RX.match(line)
        if m:
            if cur:
                out.append(tuple(cur))  # type: ignore[arg-type]
            cur = None
            if m.group(2) in levels:
                try:
                    ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    ts = time.time()
                head = line.split(" | ", 5)[-1].strip() if line.count(" | ") >= 5 else line
                cur = [ts, m.group(2), head, ""]
        elif re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", line):
            # någon annan loggrad (t.ex. INFO) avslutar posten
            if cur:
                out.append(tuple(cur))  # type: ignore[arg-type]
                cur = None
        elif cur is not None:
            cur[3] += line + "\n"          # stacktrace / flerradsmeddelande hör till posten
    if cur:
        out.append(tuple(cur))  # type: ignore[arg-type]
    return out


def import_other_logs(data_dir: Path, writer: Optional[ErrorLogWriter] = None) -> int:
    """
    Hämtar fel ur de andra loggarna till fel.log. Idempotent (positioner i fel_import.json). Returnerar antal poster.
    Anropas i bakgrunden en stund efter start och innan filen öppnas.
    """
    data_dir = Path(data_dir)
    writer = writer or _writer or ErrorLogWriter(data_dir)
    state = _load_state(data_dir)
    n = 0
    entries: List[Tuple[float, str, str, str]] = []

    # 1. update_watchdog.log — egen process, hamnar aldrig i todo_app.log
    wl = data_dir / "update_watchdog.log"
    if wl.is_file():
        try:
            pos = int(state.get("update_watchdog", 0))
            if pos > wl.stat().st_size:
                pos = 0
            text, new_pos = _read_text(wl, pos)
            for line in text.splitlines():
                low = line.lower()
                if any(k in low for k in _WATCHDOG_KEYWORDS):
                    try:
                        ts = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
                        body = line[22:] if line[19:22] == " | " else line
                    except ValueError:
                        ts, body = time.time(), line
                    entries.append((ts, "update_watchdog.log", body, ""))
            state["update_watchdog"] = new_pos
        except OSError:
            pass

    # 2. nödrapporten vid fönsterfel
    fr = data_dir / "window_failure_report.txt"
    if fr.is_file():
        try:
            mt = int(fr.stat().st_mtime)
            if int(state.get("window_failure_mtime", 0)) != mt:
                text, _ = _read_text(fr, 0, 20_000)
                lines = [l for l in text.splitlines() if l.strip() and not set(l) <= {"="}]
                entries.append((float(mt), "window_failure_report.txt", "Nödrapport: fönster kunde inte skapas (se data\\window_failure_report.txt)",
                                "\n".join(lines[:25])))
                state["window_failure_mtime"] = mt
        except OSError:
            pass

    # 3. todo_app.log + roterade dagsfiler: ERROR/CRITICAL, första gången (därefter fångas allt live)
    if not state.get("main_log_done"):
        files = sorted(data_dir.glob("todo_app.log.*"), key=lambda p: p.name)
        cur = data_dir / "todo_app.log"
        if cur.is_file():
            files.append(cur)
        for p in files:
            try:
                text, size = _read_text(p, 0)
            except OSError:
                continue
            for ts, lvl, head, trace in parse_log_errors(text):
                entries.append((ts, f"{p.name}", f"{lvl}: {head}", trace))
        state["main_log_done"] = True

    entries.sort(key=lambda e: e[0])
    seen = set()
    for ts, src, msg, trace in entries:
        k = (int(ts), src, msg[:200])
        if k in seen:
            continue
        seen.add(k)
        writer.write_imported(ts, src, msg, trace)
        n += 1
    _save_state(data_dir, state)
    return n


def import_in_background(data_dir: Path, delay: float = 10.0) -> None:
    def _run() -> None:
        try:
            time.sleep(delay)
            import_other_logs(data_dir)
        except Exception:
            pass
    threading.Thread(target=_run, name="ErrorLogImport", daemon=True).start()


# ============================================================================================================
# NYA FEL (röd prick på tray-ikonen)
# ============================================================================================================
SEEN_NAME = "fel_seen.txt"          # epoch-sekunder för senaste "Öppna felloggen"
_ENTRY_RX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \| (FEL|KRASCH)\s*\|")
_unseen_cache: Dict[Tuple[str, int, int, float], int] = {}


def seen_path(data_dir: Path) -> Path:
    return Path(data_dir) / SEEN_NAME


def read_seen(data_dir: Path) -> Optional[float]:
    """Tidpunkten då felloggen senast öppnades (None = aldrig/okänd)."""
    try:
        return float(seen_path(data_dir).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def mark_seen(data_dir: Path, when: Optional[float] = None) -> None:
    """Markera allt som läst (anropas när användaren öppnar felloggen)."""
    try:
        d = Path(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        seen_path(d).write_text(str(int(time.time() if when is None else when)), encoding="utf-8")
    except OSError:
        pass
    _unseen_cache.clear()


def count_unseen(data_dir: Path, now: Optional[float] = None) -> int:
    """
    Antal FEL/KRASCH-poster i fel.log som är nyare än senaste "Öppna felloggen".
    Varningar (VARNING) och importerade poster (IMPORT) räknas inte — pricken ska betyda något.
    Första gången (ingen fel_seen.txt) sätts baslinjen till nu: gamla fel ger ingen prick.
    Billig att anropa ofta: resultatet cachas på (mtime, storlek, baslinje).
    """
    data_dir = Path(data_dir)
    seen = read_seen(data_dir)
    if seen is None:
        mark_seen(data_dir, now)
        return 0
    p = log_path(data_dir)
    try:
        st = p.stat()
    except OSError:
        return 0
    key = (str(p), int(st.st_mtime_ns // 1_000_000), st.st_size, seen)
    hit = _unseen_cache.get(key)
    if hit is not None:
        return hit
    n = 0
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _ENTRY_RX.match(line)
                if not m:
                    continue
                try:
                    ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                except (ValueError, OverflowError):
                    continue
                if ts > seen:
                    n += 1
    except OSError:
        return 0
    _unseen_cache.clear()
    _unseen_cache[key] = n
    return n


# ============================================================================================================
# FELPOSTER ligger kvar tills de är åtgärdade; VARNINGAR och sessionshuvuden från tidigare dagar arkiveras
# ============================================================================================================
RESOLVED_NAME = "fel_atgardade.log"      # i loggar/arkiv/
OVERFLOW_NAME = "fel_overflod.log"       # i loggar/arkiv/ — bara om fel.log blir orimligt stor
_ANY_ENTRY_RX = re.compile(r"^(\d{4}-\d\d-\d\d) \d\d:\d\d:\d\d \| (\S+)\s*\|")
_HEADER_RX = re.compile(r"^═══ Ledgebord startad (\d{4}-\d\d-\d\d) ")
_open_cache: Dict[Tuple[str, int, int], int] = {}
_tidy_sig: Dict[str, Tuple[int, int, str]] = {}


def parse_blocks(text: str) -> List[Dict[str, str]]:
    """
    Delar fel.log i block: 'entry' (en post med följdrader/stacktrace), 'header' (═══ Ledgebord startad …) och 'other'.
    Förlustfritt: ''.join(block['text']) == text.
    """
    blocks: List[Dict[str, str]] = []
    for line in text.splitlines(keepends=True):
        m = _ANY_ENTRY_RX.match(line)
        if m:
            blocks.append({"kind": "entry", "day": m.group(1), "level": m.group(2), "text": line})
            continue
        h = _HEADER_RX.match(line)
        if h:
            blocks.append({"kind": "header", "day": h.group(1), "level": "", "text": line})
        elif blocks:
            blocks[-1]["text"] += line
        else:
            blocks.append({"kind": "other", "day": "", "level": "", "text": line})
    return blocks


def is_error_block(b: Dict[str, str]) -> bool:
    """FEL, KRASCH och IMPORT (fel hämtade ur andra loggar) är felposter; bara VARNING är en varning."""
    return b["kind"] == "entry" and b["level"] != "VARNING"


def _drop_empty_headers(blocks: List[Dict[str, str]], keep: List[bool], today_iso: str) -> None:
    """Ett sessionshuvud behålls om det är dagens eller om en behållen post följer före nästa huvud."""
    follows_kept = False
    for i in range(len(blocks) - 1, -1, -1):
        b = blocks[i]
        if b["kind"] == "header":
            keep[i] = follows_kept or b["day"] >= today_iso
            follows_kept = False
        elif keep[i] and b["kind"] == "entry":
            follows_kept = True


def _writer_lock():
    w = _writer
    return w._lock if w is not None else threading.RLock()


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def tidy(data_dir: Path, today: Optional[date] = None, cap_bytes: Optional[int] = None, placeholder: bool = True) -> Dict[str, int]:
    """
    Städar fel.log: VARNINGAR från dagar före idag arkiveras (arkiv/ÅÅÅÅ-MM-DD.zip → fel-varningar.log); felposter
    (FEL/KRASCH/IMPORT) ligger kvar tills de markerats som åtgärdade. Skriver bara om filen när något ändrats.
    cap_bytes: blir filen ändå större flyttas de ÄLDSTA felposterna till arkiv/fel_overflod.log (ingen går förlorad).
    """
    res = {"warnings": 0, "overflow": 0}
    data_dir = Path(data_dir)
    p = log_path(data_dir)
    try:
        st = p.stat()
    except OSError:
        return res
    today_iso = (today or date.today()).isoformat()
    sig = (st.st_mtime_ns // 1_000_000, st.st_size, today_iso)
    if _tidy_sig.get(str(p)) == sig:
        return res
    with _writer_lock():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return res
        blocks = parse_blocks(text)
        keep = [True] * len(blocks)
        old_warn: Dict[str, str] = {}
        for i, b in enumerate(blocks):
            if b["kind"] == "entry" and not is_error_block(b) and b["day"] < today_iso:
                keep[i] = False
                old_warn[b["day"]] = old_warn.get(b["day"], "") + b["text"]
                res["warnings"] += 1
        _drop_empty_headers(blocks, keep, today_iso)
        overflow = ""
        if cap_bytes:
            size = sum(len(b["text"].encode("utf-8")) for b, k in zip(blocks, keep) if k)
            for i, b in enumerate(blocks):
                if size <= cap_bytes // 2:
                    break
                if keep[i] and is_error_block(b):
                    keep[i] = False
                    overflow += b["text"]
                    size -= len(b["text"].encode("utf-8"))
                    res["overflow"] += 1
            if overflow:
                _drop_empty_headers(blocks, keep, today_iso)
        if all(keep):
            st2 = p.stat()
            _tidy_sig[str(p)] = (st2.st_mtime_ns // 1_000_000, st2.st_size, today_iso)
            return res
        try:        # arkivera FÖRST — skriv över filen först när arkivet säkert är skrivet
            for d in sorted(old_warn):
                _la.add_to_zip(_la.day_zip(data_dir, d), "fel-varningar.log", old_warn[d].encode("utf-8"))
            if overflow:
                ap = _la.archive_dir(data_dir)
                ap.mkdir(parents=True, exist_ok=True)
                with open(ap / OVERFLOW_NAME, "a", encoding="utf-8") as f:
                    f.write(f"\n═══ För stor fel.log — äldsta felposterna flyttade {time.strftime('%Y-%m-%d %H:%M:%S')} ═══\n{overflow}")
            new_text = "".join(b["text"] for b, k in zip(blocks, keep) if k)
            if placeholder and not new_text.strip():
                new_text = PLACEHOLDER
            _write_atomic(p, new_text)
        except OSError:
            res["warnings"] = res["overflow"] = 0
            return res
        _unseen_cache.clear()
        _open_cache.clear()
        st3 = p.stat()
        _tidy_sig[str(p)] = (st3.st_mtime_ns // 1_000_000, st3.st_size, today_iso)
    return res


def open_error_count(data_dir: Path) -> int:
    """Antal felposter (FEL/KRASCH/IMPORT) som ännu inte markerats som åtgärdade. Cachas på (mtime, storlek)."""
    p = log_path(data_dir)
    try:
        st = p.stat()
    except OSError:
        return 0
    key = (str(p), st.st_mtime_ns // 1_000_000, st.st_size)
    hit = _open_cache.get(key)
    if hit is not None:
        return hit
    try:
        n = sum(1 for b in parse_blocks(p.read_text(encoding="utf-8", errors="replace")) if is_error_block(b))
    except OSError:
        return 0
    _open_cache.clear()
    _open_cache[key] = n
    return n


def resolve_all(data_dir: Path, now: Optional[float] = None) -> int:
    """
    "Markera som åtgärdade": alla felposter flyttas till arkiv/fel_atgardade.log (med datum för markeringen) och
    försvinner ur fel.log. Dagens varningar ligger kvar. Returnerar antal flyttade poster (0 = inget att göra eller
    arkivet gick inte att skriva — då rörs fel.log inte).
    """
    data_dir = Path(data_dir)
    p = log_path(data_dir)
    now = time.time() if now is None else now
    with _writer_lock():
        try:
            blocks = parse_blocks(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return 0
        errs = [b for b in blocks if is_error_block(b)]
        if not errs:
            return 0
        keep = [not is_error_block(b) for b in blocks]
        _drop_empty_headers(blocks, keep, "9999-99-99")      # huvuden utan kvarvarande poster försvinner
        try:
            ap = _la.archive_dir(data_dir)
            ap.mkdir(parents=True, exist_ok=True)
            with open(ap / RESOLVED_NAME, "a", encoding="utf-8") as f:
                f.write(f"\n═══ Markerade som åtgärdade {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))} "
                        f"({len(errs)} fel) ═══\n" + "".join(b["text"] for b in errs))
            rest = "".join(b["text"] for b, k in zip(blocks, keep) if k)
            _write_atomic(p, rest if rest.strip() else PLACEHOLDER)
        except OSError:
            return 0
        w = _writer
        if w is not None:
            w.flush_summaries()
            w._seen.clear()                 # ett fel som kommer tillbaka efter markeringen ska loggas igen
            w._session_written = False      # nytt sessionshuvud vid nästa post
        _unseen_cache.clear()
        _open_cache.clear()
        _tidy_sig.clear()
    mark_seen(data_dir, now)
    return len(errs)


def prepare_for_open(data_dir: Path) -> Path:
    """Importerar det nya, skriver sammanfattningar och ser till att filen finns (med en trevlig rad om den är tom)."""
    data_dir = Path(data_dir)
    w = _writer or ErrorLogWriter(data_dir)
    try:
        import_other_logs(data_dir, w)
    except Exception:
        pass
    w.flush_summaries()
    try:
        tidy(data_dir)               # gamla varningar → arkiv/ (felposter ligger kvar)
    except Exception:
        pass
    p = log_path(data_dir)
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(PLACEHOLDER, encoding="utf-8")
        except OSError:
            pass
    return p


def open_in_viewer(path: Path) -> bool:
    """Öppna filen i standardprogrammet (Anteckningar på Windows)."""
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False
