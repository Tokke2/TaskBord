# -*- coding: utf-8 -*-
"""
error_log.py — EN fil med alla fel för snabb felsökning: data/fel.log

Varför: felen ligger annars utspridda — todo_app.log (tusentals rader, där felen drunknar), update_watchdog.log
(egen process), window_failure_report.txt (nödrapport) och äldre roterade loggar. Den här filen samlar bara det som
gått fel, i tidsordning, kortfattat och med stacktrace — öppna den först.

Innehåll
  • LIVE: en logg-handler på root-loggern fångar varje WARNING/ERROR/CRITICAL från ALLA moduler (inkl. okända
    undantag via excepthook) och skriver dem direkt. Upprepade, likadana fel samlas ("upprepades N gånger").
  • IMPORT: vid start (och innan filen öppnas) hämtas fel från de andra loggarna: update_watchdog.log (nya rader,
    bara de som gäller fel/återställning), window_failure_report.txt (nödrapporten) samt — första gången —
    ERROR/CRITICAL ur todo_app.log och de roterade dagsfilerna. Positionerna sparas i data/fel_import.json så
    samma rad aldrig hamnar två gånger.
  • Token och mailadresser maskas (samma regler som felrapporten). Allt ligger i appmappen (data/).
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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
        self._seen: Dict[Tuple[int, str, str], List[float]] = {}   # nyckel → [första/senaste skrivna ts, tyst antal, senaste ts]
        self.written = 0

    # -- låg nivå ------------------------------------------------------------------------------------------------
    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                bak = self.path.with_name(self.path.name + ".1")
                try:
                    bak.unlink()
                except OSError:
                    pass
                os.replace(self.path, bak)
                self._session_written = False       # ny fil → nytt sessionshuvud
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


def prepare_for_open(data_dir: Path) -> Path:
    """Importerar det nya, skriver sammanfattningar och ser till att filen finns (med en trevlig rad om den är tom)."""
    data_dir = Path(data_dir)
    w = _writer or ErrorLogWriter(data_dir)
    try:
        import_other_logs(data_dir, w)
    except Exception:
        pass
    w.flush_summaries()
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
