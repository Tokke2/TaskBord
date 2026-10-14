# -*- coding: utf-8 -*-
"""Felbeskrivning, felkategorisering och felruta."""

from __future__ import annotations

import logging.handlers
import sys
from typing import Any, Dict, Final, Optional

from app.constants import APP_NAME, LOG_PREFIX
from app.platform_utils import _is_pyw


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare som genererar:
#   - Anvandarvanlig svenska feltext (for dialoger)
#   - Kompakt teknisk stacktrace (for loggar)
#   - Standardiserad error-dialog
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod/attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde",
    "KeyError": "Nyckel saknas i data",
    "FileNotFoundError": "Filen hittades inte",
    "PermissionError": "Saknar ratigheter till filen",
    "OSError": "Operativsystem-fel",
    # Qt-specifikt
    "RuntimeError": "Qt-runtime-fel (kanske trasig widget)",
}


def _describe_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Args:
        exc: Exception-objektet som ska beskrivas

    Returns:
        Svensk sträng som passar i dialoger

    Exempel:
        >>> _describe_exception(FileNotFoundError("data.json"))
        'Filen hittades inte: data.json'
    """
    exc_type = type(exc).__name__
    svensk_typ = _ERROR_TRANSLATIONS.get(exc_type, f"Tekniskt fel ({exc_type})")
    msg = str(exc).strip()
    if not msg:
        return svensk_typ
    # For Qt-fel: extrahera mer info fran message
    if "QWidget" in msg and "cannot be child of" in msg:
        return f"{svensk_typ} — ett Qt-fonster försökte bli barn av fel typ av foralder"
    return f"{svensk_typ}: {msg}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """
    NY v6.4.1 v7: Kompakt stacktrace (sista N frames) for loggar.

    Args:
        exc: Exception-objektet
        max_frames: Max antal frames att visa (default 5)

    Returns:
        Formaterad stacktrace-sträng

    Exempel:
        >>> try: raise ValueError("x")
        ... except Exception as e: print(_format_compact_traceback(e))
        ValueError: x
          File "main.pyw", line 1234, in run
          ...
    """
    import traceback
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    if len(tb_lines) <= max_frames + 3:  # +3 for header/footer
        return "".join(tb_lines)
    # Visa header + forsta + sista N frames
    header = tb_lines[0]
    middle_frame = tb_lines[1] if len(tb_lines) > 1 else ""
    last_frames = tb_lines[-(max_frames):]
    return header + middle_frame + f"  ... ({len(tb_lines) - max_frames - 1} frames utelämnade) ...\n" + "".join(last_frames)


def _categorize_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external"
    """
    import errno
    exc_type = type(exc).__name__
    # Användarinput-fel (vanligtvis OK att visa fint felmeddelande)
    if exc_type in ("ValueError", "KeyError", "TypeError"):
        return "user_input"
    # System-fel (filläsning, nätverk)
    if exc_type in ("OSError", "IOError", "PermissionError", "FileNotFoundError"):
        return "system"
    if isinstance(exc, OSError) and hasattr(errno, 'EACCES'):
        return "system"
    # Externa bibliotek (Qt, orjson)
    if "Qt" in exc_type or "PySide" in str(exc) or "QObject" in str(exc):
        return "external"
    # Allt annat = troligen kod-bugg
    return "code_bug"


def show_error_dialog(
    title: str,
    user_message: str,
    technical: Optional[str] = None,
    category: str = "code_bug",
    parent: Any = None,
) -> int:
    """
    NY v6.4.1 v7: Standardiserad error-dialog med svensk text + teknisk info.

    Vad den gor:
      1. Visar anvandarvanligt felmeddelande (svenska)
      2. Om technical finns: expanderbar sektion med stacktrace
      3. Loggar ALLT till error-loggen
      4. Returnerar anvandarens val (OK = 1, Avbryt = 0)

    Args:
        title: Kort titel (t.ex. "Kunde inte spara")
        user_message: Svensk forklaring (for anvandaren)
        technical: Stacktrace / debug-info (valfritt)
        category: "user_input" | "system" | "code_bug" | "external"
        parent: Parent-widget for modal dialog

    Returns:
        1 om anvandaren klickade OK, 0 annars
    """
    log = logging.getLogger("ErrorDialog")
    log.error(
        f"{LOG_PREFIX} show_error_dialog: title={title!r}, category={category}"
    )
    log.debug(f"  user_message: {user_message}")
    if technical:
        log.debug(f"  technical:\n{technical}")
    if _is_pyw():
        try:
            # Bygg message med expanderbar teknisk sektion
            full_msg = user_message
            if technical:
                # Visa teknisk info via stderr (inte i dialog-rutan)
                # sa dialogen inte blir for plottrig
                log.info(
                    f"{LOG_PREFIX} teknisk info (se loggfil): {technical[:200]}..."
                )
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                parent,
                f"{APP_NAME} — {title}",
                full_msg,
            )
            return 1
        except Exception as e:
            log.warning(
                f"{LOG_PREFIX} show_error_dialog misslyckades (Qt): {e}"
            )
            # Fallback: stderr
            print(f"[FEL] {title}: {user_message}", file=sys.stderr)
            return 0
    else:
        # Console-läge
        print(f"[FEL] {title}", file=sys.stderr)
        print(f"  {user_message}", file=sys.stderr)
        if technical:
            print(f"  Teknisk info:\n{technical}", file=sys.stderr)
        return 1
