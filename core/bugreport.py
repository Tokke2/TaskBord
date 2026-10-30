# -*- coding: utf-8 -*-
"""
Felrapport med ett klick: en ZIP med det som behövs för att felsöka — utan dina uppgifter.

Innehåll: info.txt (version, Python, Windows, vilka programfiler som körs), loggen (sista raderna,
rensad på token/adresser), inställningarna (hemligheter borttagna), väktarloggen om den finns.
Uppgifter (js/active.json, archive.json), Google-koppling och mailinnehåll tas ALDRIG med.
Allt skrivs i appmappen (data/felrapporter/) — inget utanför den.

Ren Python, ingen Qt.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_TAIL_LINES = 3000
REPORT_DIR_NAME = "felrapporter"
KEEP_REPORTS = 10
SECRET_KEY_RE = re.compile(r"token|secret|password|passwd|client|credential|api[_-]?key|auth", re.I)
PROGRAM_SUFFIXES = {".py", ".pyw", ".bat", ".ps1", ".xpi", ".txt", ".md"}
SKIP_TOP = {"js", "data", ".git", "__pycache__", "node_modules"}

_RX = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:token|secret|password|key|authorization)[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"(?i)(x-taskbord-token\W+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})"), r"***@\1"),
]


def redact_text(text: str) -> str:
    """Maska token och mailadresser (behåller domänen — den kan vara till hjälp)."""
    for rx, rep in _RX:
        text = rx.sub(rep, text)
    return text


def redact_settings(obj: Any) -> Any:
    """Kopia av inställningarna där alla hemliga nycklar ersatts med '***'."""
    if isinstance(obj, dict):
        return {
            k: ("***" if SECRET_KEY_RE.search(str(k)) and v not in ("", None, False, 0) else redact_settings(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_settings(v) for v in obj]
    return obj


def tail_lines(path: Path, n: int = LOG_TAIL_LINES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4 * 1024 * 1024))
            data = f.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def program_files(app_dir: Path) -> List[Path]:
    out = []
    for p in sorted(Path(app_dir).rglob("*")):
        try:
            rel = p.relative_to(app_dir)
        except ValueError:
            continue
        if rel.parts[0] in SKIP_TOP or "__pycache__" in rel.parts or not p.is_file():
            continue
        if p.suffix.lower() in PROGRAM_SUFFIXES or p.name == "main.pyw":
            out.append(p)
    return out


def file_table(app_dir: Path) -> str:
    rows = []
    for p in program_files(app_dir):
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        except OSError:
            h = "?"
        rows.append(f"{h}  {p.relative_to(app_dir).as_posix()}")
    return "\n".join(rows)


def _pyside_version() -> str:
    try:
        import PySide6
        return PySide6.__version__
    except Exception:
        return "saknas"


def info_text(app_dir: Path, extra: Optional[Dict[str, Any]] = None) -> str:
    lines = [
        "Ledgebord felrapport",
        f"Skapad:       {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Python:       {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"System:       {platform.platform()}",
        f"PySide6:      {_pyside_version()}",
        f"Appmapp:      {Path(app_dir).name}  (git-mapp: {'ja' if (Path(app_dir) / '.git').exists() else 'nej'})",
    ]
    for k, v in (extra or {}).items():
        lines.append(f"{k + ':':<13} {v}")
    xpi = Path(app_dir) / "Ledgebord-Thunderbird.xpi"
    if xpi.is_file():
        lines.append(f"xpi sha256:   {hashlib.sha256(xpi.read_bytes()).hexdigest()[:16]}")
    return "\n".join(lines) + "\n"


README = (
    "Den här ZIP-filen innehåller INTE dina uppgifter, din Google-koppling eller dina mail.\n"
    "Den innehåller:\n"
    "  info.txt         version, Python, Windows\n"
    "  filer.txt        kort fingeravtryck för varje programfil (visar exakt vilken kod som körs)\n"
    "  fel.log          alla fel/varningar samlade (börja läsa här)\n"
    "  todo_app.log     de senaste raderna ur loggen (token och mailadresser maskade)\n"
    "  settings.json    inställningar (alla hemligheter ersatta med ***)\n"
    "  update_watchdog.log  om en uppdatering skett\n\n"
    "Loggen kan ändå innehålla uppgiftstitlar och mailämnen — titta igenom den innan du skickar.\n"
)


def create_report(app_dir: Path, settings_file: Optional[Path] = None,
                  extra: Optional[Dict[str, Any]] = None, now: Optional[float] = None) -> Path:
    """Skriv ZIP:en i <app>/data/felrapporter/ och returnera sökvägen."""
    app_dir = Path(app_dir)
    data = app_dir / "data"
    out_dir = data / REPORT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    out = out_dir / f"ledgebord-felrapport-{stamp}.zip"
    n = 1
    while out.exists():
        n += 1
        out = out_dir / f"ledgebord-felrapport-{stamp}-{n}.zip"
    settings_text = ""
    sf = Path(settings_file) if settings_file else app_dir / "js" / "settings.json"
    try:
        settings_text = json.dumps(redact_settings(json.loads(sf.read_text(encoding="utf-8"))),
                                   ensure_ascii=False, indent=1)
    except (OSError, ValueError):
        settings_text = "(inställningarna kunde inte läsas)"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LÄS_MIG.txt", README)
        z.writestr("info.txt", info_text(app_dir, extra))
        z.writestr("filer.txt", file_table(app_dir))
        z.writestr("todo_app.log", redact_text(tail_lines(data / "todo_app.log")))
        fl = data / "fel.log"
        if fl.is_file():
            z.writestr("fel.log", redact_text(tail_lines(fl, 1500)))
        z.writestr("settings.json", settings_text)
        wl = data / "update_watchdog.log"
        if wl.is_file():
            z.writestr("update_watchdog.log", redact_text(tail_lines(wl, 500)))
    # behåll bara de senaste rapporterna
    old = sorted(list(out_dir.glob("taskbord-felrapport-*.zip")) + list(out_dir.glob("ledgebord-felrapport-*.zip")),
                 key=lambda p: p.stat().st_mtime)
    for p in old[:-KEEP_REPORTS]:
        try:
            p.unlink()
        except OSError:
            pass
    return out
