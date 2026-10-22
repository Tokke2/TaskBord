# -*- coding: utf-8 -*-
"""Förkontroller före start (Python, PySide6, mappar)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Callable, List, Tuple


# ===========================================================================
# PRE-FLIGHT CHECK
# ===========================================================================

@dataclass
class PreFlightResult:
    """Resultat av pre-flight check."""
    ok: bool
    python_ok: bool = True
    pyside_ok: bool = True
    dependencies_ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PreFlightChecker:
    """Modulär pre-flight check (varje check är en separat metod)."""

    def __init__(self) -> None:
        self._checks: List[Callable[[], Tuple[bool, str, bool]]] = [
            self._check_python_version,
            self._check_pyside6,
            self._check_stdlib,
            self._check_working_directory,
        ]

    def run_all(self) -> PreFlightResult:
        """Kör ALLA pre-flight checks."""
        result = PreFlightResult(ok=True)
        for check_fn in self._checks:
            try:
                ok, msg, is_error = check_fn()
                if not ok and is_error:
                    result.errors.append(msg)
                    result.ok = False
                elif not ok:
                    result.warnings.append(msg)
            except Exception as e:
                result.errors.append(f"Check {check_fn.__name__} misslyckades: {e}")
                result.ok = False
        return result

    def _check_python_version(self) -> Tuple[bool, str, bool]:
        """Kontrollera Python-version (3.9+ krävs)."""
        if sys.version_info < (3, 9):
            return False, (
                f"Python {sys.version_info.major}.{sys.version_info.minor} är för gammal. "
                f"Ledgebord kräver Python 3.9+"
            ), True
        return True, (
            f"Python {sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        ), False

    def _check_pyside6(self) -> Tuple[bool, str, bool]:
        """Kontrollera PySide6-import."""
        try:
            import PySide6  # noqa: F401
            from PySide6 import QtCore  # noqa: F401
            return True, f"PySide6 {PySide6.__version__} OK", False
        except ImportError as e:
            return False, f"PySide6 saknas: {e}", True

    def _check_stdlib(self) -> Tuple[bool, str, bool]:
        """Kontrollera att nödvändiga stdlib-moduler finns."""
        required = ["json", "logging", "threading", "os", "sys", "time"]
        missing = [m for m in required if not _module_exists(m)]
        if missing:
            return False, f"Saknar stdlib-moduler: {missing}", True
        return True, f"stdlib OK ({len(required)} moduler)", False

    def _check_working_directory(self) -> Tuple[bool, str, bool]:
        """Kontrollera att arbetskatalogen är skrivbar."""
        cwd = Path.cwd()
        if not os.access(cwd, os.W_OK):
            return False, f"Cwd {cwd} är inte skrivbar", False
        return True, f"Cwd skrivbar: {cwd}", False


def _module_exists(name: str) -> bool:
    """Kontrollera om en modul kan importeras."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False
