# -*- coding: utf-8 -*-
"""Uppstart: signalhanterare, global felhanterare och run()."""

from __future__ import annotations

import atexit
import importlib.util
import logging.handlers
import os
import platform
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List

from app.central_log import add_central_log_listener, format_central_log_stats_swedish, format_event_log_swedish, get_central_log_stats, get_recent_app_events, install_central_log_handler
from app.config import parse_args
from app.constants import APP_NAME, APP_VERSION_DISPLAY, DATA_DIR, JS_DIR, LOG_FILE, LOG_PREFIX, RELEASE_VERSION, SCRIPT_DIR, Timeouts
from app.controller import AppController
from app.errors import _categorize_exception, _describe_exception, _format_compact_traceback, show_error_dialog
from app.formatting import format_uptime
from app.jsonutil import _HAS_ORJSON
from app.logging_setup import StructuredFormatter, setup_logging
from app.module_loader import ImportStatus, import_all_dependencies
from app.performance import AsyncTaskRunner, PerformanceMonitor
from app.platform_utils import _is_double_click_start, _is_pyw, _is_windows
from app.plugins import format_plugin_status_swedish, get_plugin_status
from app.preflight import PreFlightChecker
from app.splash import hide_splash, show_splash
from app.subsystems import SubsystemRegistry


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

def setup_signal_handlers(controller: AppController) -> None:
    """
    NY v6.4.1 v7: Installera signal handlers for graceful shutdown.

    Hanterar SIGINT (Ctrl+C), SIGTERM (avsluta), SIGBREAK (Windows).
    Loggar signal + startar shutdown.
    """
    log = logging.getLogger("Main")

    def handler(signum, frame):
        # Signal-namn for svensk lasbarhet
        signal_names = {
            signal.SIGINT: "Ctrl+C (SIGINT)",
            signal.SIGTERM: "Avsluta (SIGTERM)",
            signal.SIGBREAK: "Windows Ctrl+Break (SIGBREAK)",
        }
        name = signal_names.get(signum, f"signal {signum}")
        log.info(
            f"{LOG_PREFIX} Signal mottagen: {name} — startar graceful shutdown"
        )
        try:
            controller.shutdown()
        except Exception as e:
            log.warning(
                f"{LOG_PREFIX} shutdown efter signal misslyckades: {e}",
                exc_info=True,
            )

    with suppress(Exception):
        signal.signal(signal.SIGINT, handler)
        log.debug(f"{LOG_PREFIX} SIGINT handler installerad")
    with suppress(Exception):
        signal.signal(signal.SIGTERM, handler)
        log.debug(f"{LOG_PREFIX} SIGTERM handler installerad")
    if hasattr(signal, "SIGBREAK"):
        with suppress(Exception):
            signal.signal(signal.SIGBREAK, handler)
            log.debug(f"{LOG_PREFIX} SIGBREAK handler installerad")


def show_pre_flight_error_dialog(error: str) -> None:
    """
    NY v6.4.1 v7: Visa pre-flight error (forbattrad).

    Använder show_error_dialog() for konsistent felhantering.
    Felmeddelandet oversatts till svenska nar mojligt.
    """
    log = logging.getLogger("PreFlight")
    log.critical(f"{LOG_PREFIX} Pre-flight error: {error}")
    # Visa med show_error_dialog (standardiserad)
    show_error_dialog(
        title="Startfel",
        user_message=(
            f"{APP_NAME} kunde inte startas.\n\n"
            f"Orsak: {error}\n\n"
            f"Mer information finns i loggfilen:\n{LOG_FILE}"
        ),
        technical=error,
        category="system",
    )


def install_global_exception_hook() -> None:
    """
    NY v6.4.1 v7: Global exception hook med AI-felsokning.

    Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det".

    Vad den gor:
      1. Fångar ALLA ohanterade undantag (inte KeyboardInterrupt)
      2. Loggar komplett stacktrace till data/todo_app.log
      3. Visar svensk fel-dialog till anvandaren
      4. Kallar original hook (for Qt-dialog)
      5. NY v7: Installerar Qt-message-handler for Qt-fel (qInstallMessageHandler)
      6. NY v7: Loggar även SystemExit och BaseException (utom KeyboardInterrupt/SystemExit frivillig)
    """
    # Säkerställ att logger finns — vi loggar alltid, även före run() startat
    log = logging.getLogger("Main")
    try:
        # Om root-logger saknar handlers, lägg till en basic file-handler som
        # alltid skriver till data/todo_app.log (även vid tyst crash)
        root = logging.getLogger()
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
            try:
                log_path = SCRIPT_DIR / "data" / "todo_app.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_handler = logging.handlers.RotatingFileHandler(
                    log_path,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                fallback_handler.setLevel(logging.DEBUG)
                fallback_handler.setFormatter(logging.Formatter(
                    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-20s | %(message)s",
                    "%H:%M:%S",
                ))
                root.addHandler(fallback_handler)
                log.info(f"{LOG_PREFIX} fallback file-handler tillagd: {log_path}")
            except Exception as _fh_err:
                log.warning(f"{LOG_PREFIX} kunde inte lägga till fallback-handler: {_fh_err}")
    except Exception as _setup_err:
        # Om vi inte ens kan logga, skriv till stderr som sista utväg
        try:
            print(f"[FATAL] install_global_exception_hook setup: {_setup_err}", file=sys.stderr)
        except Exception:
            pass

    def hook(exc_type, exc_value, exc_traceback):
        # NY v7: Tillåt KeyboardInterrupt + frivillig SystemExit
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        try:
            log.critical(
                f"{LOG_PREFIX} OHANTERAT FEL [{exc_type.__name__}]: "
                f"{_describe_exception(exc_value)}"
            )
            # Skriv ut hela traceback rad-för-rad till ALLA loggers
            import traceback as _tb
            tb_lines = _tb.format_exception(exc_type, exc_value, exc_traceback)
            for line in tb_lines:
                for h in logging.getLogger().handlers:
                    try:
                        h.emit(logging.LogRecord(
                            name="Main", level=logging.CRITICAL,
                            pathname=__file__, lineno=0, msg=line.rstrip(),
                            args=(), exc_info=None,
                        ))
                    except Exception:
                        pass
        except Exception as log_err:
            try:
                print(f"[FATAL] FEL vid loggning av fel: {log_err}", file=sys.stderr)
            except Exception:
                pass
        # Visa dialog sa Rickard vet vad som handde
        try:
            show_error_dialog(
                title="Ohanterat fel",
                user_message=(
                    f"{APP_NAME} rakade ut for ett fel som inte kunde hanteras.\n\n"
                    f"Fel: {_describe_exception(exc_value)}\n\n"
                    f"Loggfil: {LOG_FILE}"
                ),
                technical=_format_compact_traceback(exc_value),
                category="code_bug",
            )
        except Exception:
            pass
        # Anropa original hook (Qt-dialog for debug-builds)
        try:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = hook

    # NY v7: Installera Qt-message-handler — fångar Qt's egna fel-meddelanden
    # (t.ex. "qt.qpa.plugin: Could not load the Qt platform plugin")
    try:
        from PySide6.QtCore import qInstallMessageHandler
        # FIX v7-fix18: skydd mot Qt-meddelande-stormar (CreateWindowEx som
        # misslyckas vid varje expose = tusentals rader/minut).
        #   1. Reentrancy-skydd: meddelanden MEDAN vi loggar släpps tyst
        #      (loggning → Qt → meddelande → loggning → … = RecursionError)
        #   2. Dedupe: identiskt meddelande loggas 1:a, 2:a och 100:e gång
        #      med räknare — loggen förblir läslig men felet syns.
        _qt_msg_counts: Dict[str, int] = {}
        _qt_msg_active: List[bool] = [False]
        _qt_win_fail_logged: List[bool] = [False]
        _qt_win_fail_count: List[int] = [0]
        _qt_icon_remedied: List[bool] = [False]

        def qt_msg_handler(mode, ctx, msg):
            if _qt_msg_active[0]:
                return  # reentrant — släpp tyst (dödar RecursionError-loopen)
            _qt_msg_active[0] = True
            try:
                level_map = {
                    0: logging.DEBUG,    # QtDebugMsg
                    1: logging.WARNING,  # QtInfoMsg
                    2: logging.WARNING,  # QtWarningMsg
                    3: logging.ERROR,    # QtCriticalMsg
                    4: logging.CRITICAL, # QtFatalMsg
                }
                level = level_map.get(mode, logging.WARNING)
                _msg = str(msg)
                if len(_qt_msg_counts) > 256:
                    _qt_msg_counts.clear()
                _n = _qt_msg_counts.get(_msg[:200], 0) + 1
                _qt_msg_counts[_msg[:200]] = _n
                if ("CreateWindowEx failed" in _msg
                        or "Failed to create platform window" in _msg):
                    _qt_win_fail_count[0] += 1
                    _nf = _qt_win_fail_count[0]
                    if not _qt_win_fail_logged[0]:
                        _qt_win_fail_logged[0] = True
                        _thread_txt = "okänd"
                        try:
                            from PySide6.QtCore import (
                                QThread as _QT, QCoreApplication as _QApp,
                            )
                            _app = _QApp.instance()
                            _cur = _QT.currentThread()
                            _main = _app.thread() if _app is not None else None
                            _thread_txt = (
                                f"{_cur.objectName() or 'main'} "
                                f"(rätt tråd={_cur is _main})"
                            )
                        except Exception:
                            pass
                        # FIX v7-fix19: rikare diagnostik — version + skärmar + ikon
                        _ps6_ver = "?"
                        try:
                            import PySide6 as _ps6
                            _ps6_ver = _ps6.__version__
                        except Exception:
                            pass
                        _screens_txt = "?"
                        try:
                            from PySide6.QtGui import QGuiApplication as _QGA
                            _screens_txt = "; ".join(
                                f"{_s.name()}="
                                f"{_s.geometry().width()}x{_s.geometry().height()}"
                                f"@{_s.geometry().x()},{_s.geometry().y()}"
                                f" dpr={_s.devicePixelRatio()}"
                                for _s in _QGA.screens()
                            )
                        except Exception:
                            pass
                        _ico_txt = "ingen"
                        try:
                            _ico_fp = SCRIPT_DIR / "data" / "app.ico"
                            if _ico_fp.is_file():
                                _ico_txt = f"{_ico_fp} ({_ico_fp.stat().st_size}B)"
                        except Exception:
                            pass
                        log.critical(
                            f"{LOG_PREFIX} ★ QT-FEL: Fönster kunde inte "
                            f"skapas (CreateWindowEx 'Felaktig parameter'). "
                            f"Tråd: {_thread_txt}. PySide6: {_ps6_ver}. "
                            f"Skärmar: {_screens_txt}. Ikon: {_ico_txt}. "
                            f"Se data\\todo_app.log + "
                            f"data\\window_failure_report.txt"
                        )
                        # FIX v7-fix20/22: syns även i konsolen (PowerShell)
                        # med DPI-läge + desktop.py-version — en konsol-paste
                        # räcker nu för diagnos!
                        try:
                            _dpi_c = "?"
                            if sys.platform == "win32":
                                import ctypes as _ct2
                                _c = _ct2.windll.user32.GetProcessDpiAwarenessContext(
                                    _ct2.windll.kernel32.GetCurrentProcess()
                                )
                                _cv = int(_c) & 0xFFFFFFFFFFFFFFFF if _c else 0
                                _dpi_c = {
                                    0xFFFFFFFFFFFFFFFE: "SYSTEM (GAMMAL desktop.py KÖRS!)",
                                    0xFFFFFFFFFFFFFFFC: "PER_MONITOR_V2",
                                }.get(_cv, hex(_cv))
                            _desk_ver = "?"
                            try:
                                import desktop as _dm
                                _desk_ver = getattr(
                                    _dm, "DESKTOP_API_VERSION", "SAKNAR v7-fix22!"
                                )
                            except Exception:
                                pass
                            sys.__stderr__.write(
                                "\n★ Fönster-skapande misslyckas!\n"
                                f"  desktop.py: {_desk_ver}\n"
                                f"  DPI: {_dpi_c}\n"
                                "  Detaljer: data\\todo_app.log\n"
                            )
                            sys.__stderr__.flush()
                        except Exception:
                            pass
                    # ---- AUTO-REMEDY 1 (25 fel): rensa ikonen minnet -------
                    if _nf == 25 and not _qt_icon_remedied[0]:
                        _qt_icon_remedied[0] = True
                        try:
                            from PySide6.QtGui import QIcon as _QI
                            from PySide6.QtWidgets import QApplication as _QA
                            _qa = _QA.instance()
                            if _qa is not None:
                                _qa.setWindowIcon(_QI())
                            log.critical(
                                f"{LOG_PREFIX} ★ REMEDY (25 fel): app-ikonen "
                                f"RENSAD — om fönstret nu skapas var KORRUPT "
                                f"app.ico orsaken till stormen!"
                            )
                        except Exception:
                            pass
                    # ---- AUTO-REMEDY 2 (50 fel): byt namn på app.ico -------
                    elif _nf == 50:
                        try:
                            _ico_fp = SCRIPT_DIR / "data" / "app.ico"
                            if _ico_fp.is_file():
                                _suspect = _ico_fp.with_suffix(".ico.suspect")
                                _ico_fp.replace(_suspect)
                                log.critical(
                                    f"{LOG_PREFIX} ★ REMEDY (50 fel): "
                                    f"{_ico_fp.name} → {_suspect.name}. "
                                    f"STARTA OM appen — en ny ikon genereras."
                                )
                        except Exception:
                            pass
                    # ---- NÖDSTOPP (1000 fel): rapport + stoppa CPU-bränna --
                    elif _nf >= 1000:
                        # FIX v7-fix20: skriv nödrapport FÖRE avslut
                        try:
                            _ps6_ver2 = "?"
                            try:
                                import PySide6 as _ps6b
                                _ps6_ver2 = _ps6b.__version__
                            except Exception:
                                pass
                            _rep_dir = SCRIPT_DIR / "data"
                            _rep_dir.mkdir(parents=True, exist_ok=True)
                            _rep = _rep_dir / "window_failure_report.txt"
                            _rep.write_text(
                                "TaskBord — NÖDRAPPORT FÖNSTERSKAPANDE\n"
                                "=" * 60 + "\n"
                                f"Tid: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"Python: {sys.version.split()[0]} "
                                f"(exe: {sys.executable})\n"
                                f"PySide6: {_ps6_ver2}\n"
                                f"DESKTOP_API: {getattr(__import__('desktop'), 'DESKTOP_API_VERSION', 'OKAND — importera fel?') if sys.platform == 'win32' else 'n/a (icke-Windows)'}\n"
                                f"Antal misslyckade fönster-skapanden: "
                                f"{_qt_win_fail_count[0]}\n"
                                f"Ikon-remedy körd: {_qt_icon_remedied[0]}\n"
                                "\nÅTGÄRDER (i ordning):\n"
                                " 1. pip install --upgrade PySide6 "
                                "(Python 3.14 kräver färsk version!)\n"
                                " 2. Starta om och läs data\todo_app.log —\n"
                                "    sök efter ★ (PROBE-raden berättar om det\n"
                                "    är miljön eller vår widget)\n"
                                " 3. Uppdatera grafikdrivrutin\n"
                                " 4. Skicka ★-raderna + denna fil vid fortsatt fel\n",
                                encoding="utf-8",
                            )
                            log.critical(
                                f"{LOG_PREFIX} ★★ NÖDSTOPP: 1000+ misslyckade "
                                f"fönster-skapanden — nödrapport: {_rep}"
                            )
                        except Exception:
                            pass
                        log.critical(
                            f"{LOG_PREFIX} ★★ NÖDSTOPP — appen avslutas för "
                            f"att skydda CPU:n. ÅTGÄRD: pip install --upgrade "
                            f"PySide6 + läs data\\window_failure_report.txt"
                        )
                        try:
                            sys.__stderr__.write(
                                "\n★★ NÖDSTOPP — cache rensas, avslutar rent...\n"
                            )
                            sys.__stderr__.flush()
                        except Exception:
                            pass
                        # FIX v7-fix25: RENT avslut — INTE os._exit() som
                        # lämnar QThreadStorage-läckor. QApplication.quit()
                        # städar upp Qt:s trådar korrekt.
                        try:
                            from PySide6.QtWidgets import (
                                QApplication as _QA,
                            )
                            _qa = _QA.instance()
                            if _qa is not None:
                                _qa.quit()
                                return
                        except Exception:
                            pass
                        # Fallback: flusha logg + rensa cache + exit
                        try:
                            for _h in logging.getLogger().handlers:
                                with suppress(Exception):
                                    _h.flush()
                        except Exception:
                            pass
                        import os as _os
                        _os._exit(1)
                if _n <= 2 or _n % 100 == 0:
                    _suffix = f" [förekomst {_n}]" if _n > 2 else ""
                    log.log(
                        level,
                        f"{LOG_PREFIX} Qt-meddelande: {msg}{_suffix} "
                        f"(fil={getattr(ctx, 'file', '?')}, "
                        f"rad={getattr(ctx, 'line', '?')})"
                    )
            finally:
                _qt_msg_active[0] = False
        qInstallMessageHandler(qt_msg_handler)
        _ps6_ver_txt = "?"
        try:
            import PySide6 as _ps6
            _ps6_ver_txt = _ps6.__version__
        except Exception:
            pass
        log.info(
            f"{LOG_PREFIX} Qt message handler installerad "
            f"(v7-fix18/19: dedupe + reentrancy + ikon-remedy) — "
            f"PySide6 {_ps6_ver_txt}"
        )
    except Exception as _q_err:
        try:
            log.debug(f"{LOG_PREFIX} qInstallMessageHandler ej tillgängligt: {_q_err}")
        except Exception:
            pass

    # NY v7: Installera thread exception hook (fångar fel i bakgrundstrådar)
    try:
        import threading
        def thread_hook(args):
            log.critical(
                f"{LOG_PREFIX} OHANTERAT FEL i trad "
                f"{getattr(args.thread, 'name', '?')}: {args.exc_value}"
            )
            import traceback as _tb
            tb_lines = "".join(_tb.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            ))
            for line in tb_lines.splitlines():
                log.critical(f"{LOG_PREFIX}   {line}")
        threading.excepthook = thread_hook
        log.info(f"{LOG_PREFIX} thread exception hook installerad")
    except Exception as _t_err:
        try:
            log.debug(f"{LOG_PREFIX} threading.excepthook ej tillgängligt: {_t_err}")
        except Exception:
            pass


def _bootstrap_requirements_txt() -> bool:
    """
    NY v6.4.1 v7-fix: Auto-installera + ta bort requirements.txt vid start.

    Design:
      - Körs FÖRST i run() — innan nån annan import
      - Om requirements.txt finns i samma mapp som main.pyw:
          1. Parsa den (enkel rad-för-rad)
          2. Testa varje modul med importlib.util.find_spec()
          3. Om alla finns: ta bort filen (clean state)
          4. Om något saknas: install via pip, sen ta bort filen

    Returnerar True om filen togs bort (eller inte fanns från början).
    Returnerar False om installationen misslyckades (Rickard får felmeddelande).

    Loggar med [BOOT]-prefix.
    """
    BOOT_PREFIX = "[BOOT]"
    req_path = SCRIPT_DIR / "requirements.txt"
    if not req_path.is_file():
        # Ingen fil → inget att göra (redan bootstrappad)
        return True
    log = logging.getLogger("Bootstrap")
    if not log.handlers and not log.parent.handlers:
        # Säkerställ att vi har en handler
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(StructuredFormatter())
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    log.info(
        f"{BOOT_PREFIX} requirements.txt hittad — kontrollerar beroenden..."
    )
    # 1. Parsa filen (enkel parser, hoppa över kommentarer + tomma rader)
    required: List[str] = []
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                # Hantera "PySide6>=6.5.0" → "PySide6"
                # Hantera "pywin32>=306; sys_platform == 'win32'" → skippa om ej match
                if ";" in line:
                    # Krav: t.ex. "; sys_platform == 'win32'"
                    pkg_part, marker = line.split(";", 1)
                    marker = marker.strip()
                    if "sys_platform" in marker:
                        # Enkel parser: "sys_platform == 'win32'" eller "!= 'win32'"
                        if "win32" in marker:
                            # Kräver win32 — kolla om vi är på Windows
                            if not _is_windows():
                                log.debug(
                                    f"{BOOT_PREFIX} skippar {pkg_part.strip()} "
                                    f"({marker}, vi är {sys.platform})"
                                )
                                continue
                            else:
                                pkg = pkg_part.strip()
                        else:
                            # Skippa (vi matchar inte)
                            continue
                    else:
                        pkg = pkg_part.strip()
                else:
                    pkg = line
                # Ta bort versionsspec
                for sep in (">=", "<=", "==", "!=", ">", "<", "~="):
                    if sep in pkg:
                        pkg = pkg.split(sep, 1)[0].strip()
                        break
                if pkg:
                    required.append(pkg)
    except Exception as e:
        log.error(
            f"{BOOT_PREFIX} kunde inte läsa requirements.txt: {e}"
        )
        return False
    log.info(
        f"{BOOT_PREFIX} requirements.txt: {len(required)} paket "
        f"({', '.join(required)})"
    )
    # 2. Testa vilka som redan finns
    missing: List[str] = []
    for pkg in required:
        # Mappa pip-namn → import-namn (specialfall)
        import_name = {
            "PySide6": "PySide6",
            "psutil": "psutil",
            "pywin32": "win32api",
            "orjson": "orjson",
        }.get(pkg, pkg)
        try:
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pkg)
        except (ImportError, ValueError, ModuleNotFoundError):
            missing.append(pkg)
    if not missing:
        log.info(
            f"{BOOT_PREFIX} alla {len(required)} paket redan installerade ✓ "
            f"— tar bort requirements.txt"
        )
        with suppress(Exception):
            req_path.unlink()
        log.info(
            f"{BOOT_PREFIX} requirements.txt borttagen "
            f"(ren bootstrap-state)"
        )
        return True
    log.warning(
        f"{BOOT_PREFIX} saknar {len(missing)} paket: {', '.join(missing)}"
    )
    log.info(
        f"{BOOT_PREFIX} installerar via pip (kan ta 30-60s)..."
    )
    # 3. Installera via pip (sekventiellt — säkrare)
    failed: List[str] = []
    for pkg in missing:
        log.info(f"{BOOT_PREFIX} pip install {pkg}...")
        try:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--quiet", "--disable-pip-version-check",
                pkg,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                log.info(
                    f"{BOOT_PREFIX} ✓ {pkg} installerades"
                )
            else:
                err = (proc.stderr or proc.stdout).strip()
                if len(err) > 200:
                    err = err[:197] + "..."
                log.error(
                    f"{BOOT_PREFIX} ✗ {pkg} misslyckades: {err}"
                )
                failed.append(pkg)
        except subprocess.TimeoutExpired:
            log.error(f"{BOOT_PREFIX} ✗ {pkg} tog för lång tid (>120s)")
            failed.append(pkg)
        except Exception as e:
            log.error(f"{BOOT_PREFIX} ✗ {pkg} kraschade: {e}")
            failed.append(pkg)
    if failed:
        log.error(
            f"{BOOT_PREFIX} misslyckades installera: {', '.join(failed)} "
            f"— lämnar requirements.txt kvar"
        )
        return False
    log.info(
        f"{BOOT_PREFIX} ✓ alla paket installerade — tar bort "
        f"requirements.txt"
    )
    with suppress(Exception):
        req_path.unlink()
    log.info(
        f"{BOOT_PREFIX} requirements.txt borttagen "
        f"(ren bootstrap-state). Starta om appen for att ladda moduler."
    )
    return True


def run() -> int:
    """Entry point med 8000% bättre struktur (PWM + orjson + bättre autostart)."""
    # 0. NY v6.4.1 v7-fix: Bootstrap requirements.txt
    # Rickard 2026-09-22: --bootstrap ska EJ behövas → SKIPPA om flagga saknas.
    # Opt-in: kör bara med explicit `--bootstrap` på kommandoraden.
    # Om installation misslyckas (vid opt-in) → QMessageBox + avsluta.
    if "--bootstrap" not in sys.argv:
        bootstrap_ok = True  # DEFAULT: skippa (inga oväntade pip-anrop)
    else:
        try:
            bootstrap_ok = _bootstrap_requirements_txt()
        except Exception as _bst_err:
            bootstrap_ok = False
            # Fortsätt ändå — kanske Qt/PySide6 redan är installerat
            try:
                print(
                    f"[BOOT] bootstrap-fel: {_bst_err}",
                    file=sys.stderr,
                )
            except Exception:
                pass
    if not bootstrap_ok:
        # Försök visa QMessageBox (om Qt redan finns — annars stderr)
        try:
            msg = (
                "Kunde inte installera alla beroenden fran requirements.txt.\n\n"
                "Kor manuellt:\n"
                f"  {sys.executable} -m pip install -r requirements.txt\n\n"
                "Nar det ar klart, starta appen igen."
            )
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Bootstrap misslyckades", msg)
        except Exception:
            try:
                print(
                    "[BOOT] Bootstrap misslyckades — installera manuellt:\n"
                    f"  {sys.executable} -m pip install -r requirements.txt",
                    file=sys.stderr,
                )
            except Exception:
                pass
        return 1

    # 0. NY v6.4: Bättre dubbelklick-detektering
    is_pyw = _is_pyw()
    is_double_click = _is_double_click_start()

    # 1. Parsa argument
    config, mode = parse_args(sys.argv)

    # 2. NY v6.4: Setup full logging (logger_setup → data/logs/)
    # Importera logger_setup dynamiskt (för att undvika cirkulär import)
    try:
        from logger_setup import setup_full_logging
        logs_dir = setup_full_logging(
            data_dir=SCRIPT_DIR / "data",
            debug=(config.log_level == "DEBUG"),
            capture_stdout=True,
            capture_exceptions=True,
            capture_threads=True,
        )
        log = logging.getLogger("Main")
        log.info(f"{LOG_PREFIX} Data dir: {logs_dir}")
        log.info(f"{LOG_PREFIX} Log-fil: {logs_dir / 'todo_app.log'}")
    except ImportError as e:
        # Fallback till inbyggd setup_logging
        setup_logging(config.log_level, config.log_file)
        log = logging.getLogger("Main")
        log.warning(f"{LOG_PREFIX} logger_setup ej tillgängligt: {e}, använder fallback")
    # 3. Installera global exception hook (extra Qt-specifik)
    try:
        install_global_exception_hook()
    except Exception as e:
        log.debug(f"{LOG_PREFIX} install_global_exception_hook: {e}")

    # 4. NY v6.4: Förbättrad startlog (inkl dubblklick-info)
    log.info("=" * 60)
    log.info(f"--- Programstart ({APP_NAME} v{APP_VERSION_DISPLAY}, mode={mode.name}) ---")
    log.info(f"{LOG_PREFIX} Release: v{RELEASE_VERSION}")
    log.info(f"{LOG_PREFIX} Python: {sys.version.split()[0]}")
    log.info(f"{LOG_PREFIX} Plattform: {sys.platform}")
    log.info(f"{LOG_PREFIX} Arbetskatalog: {Path.cwd()}")
    log.info(f"{LOG_PREFIX} Script: {SCRIPT_DIR.joinpath('main.pyw')}")
    log.info(f"{LOG_PREFIX} pythonw.exe: {is_pyw} (dubbelklick: {is_double_click})")
    log.info(f"{LOG_PREFIX} orjson: {_HAS_ORJSON} (cache)")
    log.info(f"{LOG_PREFIX} PWM: {config.enable_pwm} (95-98% CPU-besparing vid idle)")
    log.info("=" * 60)

    preflight = PreFlightChecker()
    result = preflight.run_all()
    if not result.ok:
        error_msg = "Pre-flight misslyckades:\n  - " + "\n  - ".join(result.errors)
        log.critical(f"{LOG_PREFIX} {error_msg}")
        show_pre_flight_error_dialog(error_msg)
        return 1
    for warning in result.warnings:
        log.warning(f"{LOG_PREFIX} Pre-flight: {warning}")

    # 5. Visa splash (om aktiverat)
    splash_start = time.time()
    if config.show_splash and not is_pyw:
        with suppress(Exception):
            show_splash()

    # 6. Skapa subsystem-infrastruktur
    registry = SubsystemRegistry()
    performance = PerformanceMonitor()
    async_runner = (
        AsyncTaskRunner(max_workers=4) if config.enable_async_runner else None
    )
    if async_runner:
        async_runner.start()

    # 7. Importera dependencies
    log.info(f"{LOG_PREFIX} Importerar dependencies...")
    imports = import_all_dependencies()

    # Kontrollera kritiska imports
    critical = ["PySide6.QtCore", "PySide6.QtWidgets"]
    for mod in critical:
        if not imports[mod].ok:
            error_msg = (
                f"Kritiskt beroende saknas: {mod}\n  {imports[mod].error}"
            )
            log.critical(f"{LOG_PREFIX} {error_msg}")
            show_pre_flight_error_dialog(error_msg)
            return 1

    # 8. Validera stability-system
    if config.enable_stability:
        stab_status = imports.get("stability")
        if stab_status and stab_status.ok:
            with suppress(Exception):
                from stability import validate_startup
                ok, errors = validate_startup()
                if not ok:
                    log.warning(
                        f"{LOG_PREFIX} Stability-validation hittade {len(errors)} problem"
                    )
                    for err in errors:
                        log.warning(f"{LOG_PREFIX}   - {err}")
                else:
                    log.info(f"{LOG_PREFIX} ✓ Stability-validation OK")

    # 9. Säkerställ data-mapp
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log.debug(f"{LOG_PREFIX} Data-mapp: {DATA_DIR}")
    except OSError as e:
        log.warning(f"{LOG_PREFIX} Kunde inte skapa data-mapp: {e}")

    # 10. NY v6.4: Bättre autostart-detektering (använd utils om tillgängligt)
    autostart_status = "unknown"
    if _is_windows():
        utils_status = imports.get("utils")
        if utils_status and utils_status.ok:
            utils_inst = utils_status.instance
            is_autostart = getattr(utils_inst, "is_autostart_enabled", None)
            if is_autostart:
                with suppress(Exception):
                    autostart_status = "enabled" if is_autostart() else "disabled"
                    log.info(f"{LOG_PREFIX} Autostart: {autostart_status}")
    if autostart_status == "unknown" and is_pyw:
        # Försök basic registry-check om utils ej tillgängligt
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            ) as key:
                try:
                    winreg.QueryValueEx(key, APP_NAME)
                    autostart_status = "enabled"
                except FileNotFoundError:
                    autostart_status = "disabled"
        except Exception:
            autostart_status = "check_failed"
        log.info(f"{LOG_PREFIX} Autostart (basic check): {autostart_status}")

    # 10b. FIX v8: kör redan en TaskBord (valfri version/mapp)? Mail-bryggan svarar på /health.
    # Fångar även äldre kopior utan lås. Då startas INGEN ny instans — den körande visas.
    try:
        from core.single_instance import find_running_taskbord, InstanceMessenger, default_key
        _running_port = find_running_taskbord(8765, 12)
        # liten respit: användaren kan ha stängt appen och startat om direkt
        for _ in range(3):
            if _running_port is None:
                break
            time.sleep(0.5)
            _running_port = find_running_taskbord(8765, 12)
        if _running_port is not None:
            log.warning(
                f"{LOG_PREFIX} TaskBord kör redan (bryggan svarar på port {_running_port}) "
                f"— startar ingen ny instans"
            )
            _shown = False
            with suppress(Exception):
                _shown = InstanceMessenger().notify(default_key(), "SHOW")
            if not _shown and is_pyw:
                with suppress(Exception):
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(
                        None,
                        "TaskBord körs redan.\n\nEn andra instans startas inte.",
                        APP_NAME,
                        0x00000040,
                    )
            return 0
    except Exception as _rp_e:
        log.debug(f"{LOG_PREFIX} kontroll av körande instans misslyckades: {_rp_e}")

    # 11. Single Instance Lock (med retry)
    utils_status = imports.get("utils", ImportStatus(module="utils", ok=False))
    if utils_status.ok:
        utils_inst = utils_status.instance
        SingleInstanceLock = getattr(utils_inst, "SingleInstanceLock", None)
        if SingleInstanceLock:
            lock = SingleInstanceLock()
            acquired = False
            for attempt in range(Timeouts.LOCK_MAX_ATTEMPTS):
                if lock.acquire():
                    acquired = True
                    break
                log.info(
                    f"{LOG_PREFIX} Lock upptaget (försök {attempt+1}/"
                    f"{Timeouts.LOCK_MAX_ATTEMPTS}), väntar..."
                )
                time.sleep(Timeouts.LOCK_RETRY)
            if not acquired:
                log.warning(f"{LOG_PREFIX} En annan instans körs redan — avslutar")
                # NY v7-fix87: signalera den befintliga instansen att VISA
                # sitt fönster (mycket bättre än bara en ruta "körs redan").
                # Lyckas det → AVSLUTA TYST (fönstret dyker upp hos den
                # befintliga instansen). Misslyckas det → gamla rutan kvar.
                _notified = False
                with suppress(Exception):
                    from core.single_instance import (
                        InstanceMessenger, default_key,
                    )
                    _notified = InstanceMessenger().notify(
                        default_key(), "SHOW"
                    )
                if _notified:
                    log.info(
                        f"{LOG_PREFIX} befintlig instans signalerad — "
                        f"dess fönster visas nu. Avslutar tyst (v7-fix87)"
                    )
                elif is_pyw:
                    with suppress(Exception):
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(
                            None,
                            "En instans av TaskBord körs redan.\n\nAvslutar.",
                            APP_NAME,
                            0x00000040,  # MB_ICONINFORMATION
                        )
                return 0
            atexit.register(lock.release)
            log.info(f"{LOG_PREFIX} ✓ Single Instance Lock acquired")

    # 11b. FIX v8: fillås per datamapp — stoppar två processer mot samma uppgiftsfiler
    try:
        from core.single_instance import DataDirLock
        _data_lock = DataDirLock(JS_DIR)
        if not _data_lock.acquire():
            log.warning(
                f"{LOG_PREFIX} datamappen {JS_DIR} används redan av en annan TaskBord-process "
                f"— avslutar (annars skriver två processer över varandras uppgifter)"
            )
            _notified2 = False
            with suppress(Exception):
                from core.single_instance import InstanceMessenger, default_key
                _notified2 = InstanceMessenger().notify(default_key(), "SHOW")
            if not _notified2 and is_pyw:
                with suppress(Exception):
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(
                        None,
                        "TaskBord körs redan med samma uppgifter.\n\n"
                        "Kolla att inte en äldre kopia ligger kvar (Aktivitetshanteraren → "
                        "pythonw.exe) och att Autostart bara pekar på EN mapp.",
                        APP_NAME,
                        0x00000040,
                    )
            return 0
        atexit.register(_data_lock.release)
        log.info(f"{LOG_PREFIX} ✓ Datamapps-lås taget ({JS_DIR})")
    except Exception as _dl_e:
        log.debug(f"{LOG_PREFIX} datamapps-lås ej aktivt: {_dl_e}")

    # 12. Skapa AppController
    try:
        controller = AppController(
            config=config,
            mode=mode,
            imports=imports,
            registry=registry,
            performance=performance,
            async_runner=async_runner,
        )
        # NY v6.4: Logga PWM-status
        if config.enable_pwm and hasattr(controller, "_widgets"):
            for w in controller._widgets.values():
                if hasattr(w, "_throttle"):
                    log.debug(
                        f"{LOG_PREFIX} PWM aktiverat på widget {w.win_id!r}"
                    )
    except Exception as e:
        log.critical(f"{LOG_PREFIX} AppController-init misslyckades: {e}", exc_info=True)
        show_pre_flight_error_dialog(f"Kunde inte initiera app:\n\n{e}")
        return 1

    # 13. Setup signal handlers
    setup_signal_handlers(controller)
    atexit.register(controller.shutdown)

    # NY v7-fix87: lyssna efter ANDRA instanser → visa vårt fönster.
    # (Det hårda låset i steg 11 stoppar dem; detta gör att start av
    # appen en gång till = "visa mig" i stället för en ruta.)
    try:
        from core.single_instance import InstanceMessenger, default_key
        _messenger = InstanceMessenger()
        if _messenger.acquire(default_key()):
            _messenger.message_received.connect(
                controller._on_second_instance
            )
            controller._instance_messenger = _messenger
            log.info(
                f"{LOG_PREFIX} Instans-kanal aktiv: nästa start av "
                f"TaskBord visar detta fönster (v7-fix87)"
            )
        # kunde ej lyssna (t.ex. QLocalServer saknas) — låset i steg 11
        # skyddar fortfarande mot dubbla instanser
    except Exception as _si_e:
        log.debug(f"{LOG_PREFIX} instans-kanal ej aktiv: {_si_e}")

    # 14. Vänta på splash minimum-tid (UX)
    elapsed = time.time() - splash_start
    if elapsed < Timeouts.SPLASH_MIN_DURATION:
        time.sleep(Timeouts.SPLASH_MIN_DURATION - elapsed)
    hide_splash()

    # 15. Kör event loop (NY v6.4.1 v7: forbattrade svenska meddelanden)
    start_time = time.time()
    log.info(
        f"{LOG_PREFIX} App startad: {len(imports)} moduler, "
        f"{len(controller._widgets)} fönster, mode={mode.name}, "
        f"pwm={config.enable_pwm}, orjson={_HAS_ORJSON}"
    )
    # FIX 2026-09-24: komplett start-summary (Rickard 199999% AI-läsbart)
    _qapp_widgets = []
    _qt_ver = "?"
    _platform_info = (
        f"{platform.system()} {platform.release()}"  # typ = global 'platform'
        if "platform" in dir()
        else sys.platform
    )
    with suppress(Exception):
        if hasattr(controller, "_app") and controller._app is not None:
            _qt_ver = controller._app.applicationVersion() or "?"
            _qapp_widgets = [
                w for w in controller._app.topLevelWidgets()
                if w.__class__.__name__ not in ("QWidget", "QApplication")
            ]
            _ = QWidget  # säkerställ importerad
    log.info(
        f"{LOG_PREFIX} ╔═══════════════════════ START-SUMMARY "
        f"═══════════════════════╗"
    )
    log.info(
        f"{LOG_PREFIX} ║ Användare     : {os.environ.get('USERNAME', '?')}\n"
        f"{LOG_PREFIX} ║ OS            : {_platform_info}\n"
        f"{LOG_PREFIX} ║ Python        : {sys.version.split()[0]}\n"
        f"{LOG_PREFIX} ║ App-version   : {_qt_ver}\n"
        f"{LOG_PREFIX} ║ Moduler laddade: {len(imports)} "
        f"({sum(1 for v in imports.values() if v.ok)} OK, "
        f"{sum(1 for v in imports.values() if not v.ok)} fel)\n"
        f"{LOG_PREFIX} ║ PWM           : {'PÅ' if config.enable_pwm else 'AV'}\n"
        f"{LOG_PREFIX} ║ orjson        : {_HAS_ORJSON}\n"
        f"{LOG_PREFIX} ║ Mode          : {mode.name}\n"
        f"{LOG_PREFIX} ║ Force-show    : "
        f"{'PÅ' if config.force_show_widget else 'AV'}\n"
        f"{LOG_PREFIX} ║ Bootstrap     : "
        f"{'PÅ' if not config.no_bootstrap else 'AV'}\n"
        f"{LOG_PREFIX} ║ Plugin-install: "
        f"{'PÅ' if not config.no_plugin_install else 'AV'}\n"
        f"{LOG_PREFIX} ║ Widgets (i Qt): {len(_qapp_widgets)} top-level\n"
        f"{LOG_PREFIX} ║   typer: "
        f"{[type(w).__name__ for w in _qapp_widgets[:10]]}\n"
        f"{LOG_PREFIX} ║ Widgets-i-AppController: {len(controller._widgets)}\n"
        f"{LOG_PREFIX} ║   listor: {list(controller._widgets.keys())}\n"
        f"{LOG_PREFIX} ║ Window-configs (settings): "
        f"{[c.get('id') for c in controller.settings.window_configs() if hasattr(controller.settings, 'window_configs')]}"
    )
    log.info(
        f"{LOG_PREFIX} ╚═════════════════════════════════════════════"
        f"════════════════╝"
    )
    log.info(
        f"{LOG_PREFIX} Event loop startar. "
        f"Avsluta med: Ctrl+C, tray → Avsluta, eller signal."
    )

    try:
        exit_code = controller.run()
        # Logga hur lange appen kordes
        runtime_sec = time.time() - start_time
        log.info(
            f"{LOG_PREFIX} Event loop avslutades efter {format_uptime(runtime_sec)} "
            f"(exit_code={exit_code})"
        )
        return exit_code
    except KeyboardInterrupt:
        log.info(f"{LOG_PREFIX} KeyboardInterrupt — stänger ner...")
        controller.shutdown()
        return 0
    except Exception as e:
        # NY v6.4.1 v7: AI-felsokning — kategorisera + visa dialog
        category = _categorize_exception(e)
        svensk = _describe_exception(e)
        tb = _format_compact_traceback(e, max_frames=10)
        log.critical(
            f"{LOG_PREFIX} FATAL under event loop [{category}]: {svensk}"
        )
        log.critical(f"{LOG_PREFIX} Traceback:\n{tb}")
        # Visa dialog for Rickard
        show_error_dialog(
            title="Event loop kraschade",
            user_message=(
                f"{APP_NAME} kunde inte fortsätta:\n\n{svensk}\n\n"
                f"App avslutas med felkod 1."
            ),
            technical=tb,
            category=category,
        )
        return 1
    finally:
        hide_splash()
        log.info(f"{LOG_PREFIX} Program avslutat.")


# ===========================================================================
# SELF-TEST: CENTRAL LOGGNING (NY v6.4.1 v7)
# ===========================================================================
def _self_test_central_log() -> int:
    """Snabbtest av central-loggning. Returnerar 0 vid success."""
    print("=" * 70)
    print(f"main.pyw {APP_VERSION_DISPLAY} — Central Log Self-Test")
    print("=" * 70)

    # Test 1: Listener
    print("\n[Test 1] Listener installeras...")
    captured: List[Dict[str, Any]] = []
    unsub = add_central_log_listener(lambda ev: captured.append(ev))
    print(f"  ✓ Listener added: 0 events initially")

    # Test 2: Install handler + emit
    print("\n[Test 2] Handler installeras + events emitteras...")
    logging.getLogger().setLevel(logging.INFO)
    install_central_log_handler(logging.getLogger())
    logging.getLogger("TestMod").info("INFO från TestMod")
    logging.getLogger("TestMod").warning("VARNING")
    logging.getLogger("Widget").error("Widget-fel")
    print(f"  ✓ After 3 logs: {len(captured)} events captured (>= 3)")
    assert len(captured) >= 3, f"Förväntade >= 3, fick {len(captured)}"

    # Test 3: get_recent_app_events
    print("\n[Test 3] get_recent_app_events...")
    recent = get_recent_app_events(count=10)
    print(f"  ✓ {len(recent)} events returned")
    for ev in recent[-3:]:
        print(f"    [{ev['level']}] [{ev['module']}] {ev['message'][:50]}")

    # Test 4: get_central_log_stats
    print("\n[Test 4] get_central_log_stats...")
    stats = get_central_log_stats()
    print(f"  ✓ total={stats['total_events']}, "
          f"by_level={stats['by_level']}, "
          f"listeners={stats['listener_count']}")
    assert stats["total_events"] >= 3

    # Test 5: format_event_log_swedish
    print("\n[Test 5] format_event_log_swedish...")
    fmt = format_event_log_swedish(recent, max_items=5)
    print(f"  ✓ Output (första 4 rader):")
    for line in fmt.split("\n")[:4]:
        print(f"    {line}")

    # Test 6: format_central_log_stats_swedish
    print("\n[Test 6] format_central_log_stats_swedish...")
    stats_str = format_central_log_stats_swedish()
    print(f"  ✓ {stats_str!r}")
    assert "Central logg" in stats_str

    # Test 7: Unsubscribe
    print("\n[Test 7] Unsubscribe...")
    unsub()
    n_before = len(captured)
    logging.getLogger("TestMod").info("Efter unsub")
    print(f"  ✓ After unsub + 1 log: {len(captured)} events (oförändrat)")
    assert len(captured) == n_before, "Listener borde inte längre fångas"

    # Test 8: Plugin + central-log integration
    print("\n[Test 8] Plugin-system + central-log integration...")
    plugin_status = get_plugin_status()
    summary_plugin = format_plugin_status_swedish()
    print(f"  ✓ Plugins: {summary_plugin!r}")

    print()
    print("=" * 70)
    print(f"✓ ALLA 8 CENTRAL-LOG TESTER PASSERADE ({APP_VERSION_DISPLAY})")
    print("=" * 70)
    return 0
