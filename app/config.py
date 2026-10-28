# -*- coding: utf-8 -*-
"""Kommandoradsargument, AppConfig och hjälpare för felsäkra anrop."""

from __future__ import annotations

import argparse
import logging.handlers
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from app.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION_DISPLAY, AppMode, LOG_FILE, LOG_PREFIX, ORG_NAME, T
from app.errors import _categorize_exception, _describe_exception


# ===========================================================================
# SAFE EXECUTION HELPERS
# ===========================================================================

@contextmanager
def error_boundary(
    operation: str,
    *,
    default: Any = None,
    logger: Optional[logging.Logger] = None,
    reraise: bool = False,
):
    """
    NY v6.4.1 v7: Context manager med AI-felsokning 10000%.

    Vad den gor:
      1. Fångar undantag inom with-blocket
      2. Kategoriserar felet (user_input / system / code_bug / external)
      3. Loggar med operation-context + categori + kompakt traceback
      4. Användare kan valja 'reraise=True' for att propagerar felet vidare
    """
    log = logger or logging.getLogger("ErrorBoundary")
    try:
        yield
    except Exception as e:
        category = _categorize_exception(e)
        svensk = _describe_exception(e)
        log.error(
            f"{LOG_PREFIX} Fel i '{operation}' [{category}]: {svensk}",
            exc_info=True,
        )
        log.debug(
            f"{LOG_PREFIX} operation='{operation}', category={category}, "
            f"exc_type={type(e).__name__}"
        )
        if reraise:
            raise


def safe_call(func: Callable[..., T], *args, default: Any = None, **kwargs) -> T:
    """Anropa en funktion säkert med default vid fel."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.getLogger("SafeCall").warning(f"safe_call misslyckades: {e}")
        return default  # type: ignore[return-value]


# ===========================================================================
# GLOBAL CONFIG (immutable)
# ===========================================================================

@dataclass(frozen=True)
class AppConfig:
    """Immutable app-konfiguration (frozen dataclass)."""
    app_name: str = APP_NAME
    app_version: str = APP_VERSION_DISPLAY
    org_name: str = ORG_NAME
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    max_windows: int = 16
    icon_size: int = 64
    glass_styles: Tuple[str, ...] = ("auto", "translucent", "mica", "acrylic", "none")
    cleanup_interval_sec: int = 300
    metrics_interval_sec: int = 30
    backup_check_interval_sec: int = 60
    capabilities_refresh_sec: int = 300
    heartbeat_interval_sec: int = 5
    idle_check_interval_sec: int = 30
    enable_animations: bool = True
    show_splash: bool = True
    enable_stability: bool = True
    enable_async_runner: bool = True
    enable_pwm: bool = True  # NY v6.4 — PWM (adaptive throttle)
    force_show_widget: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: tvinga widget synlig (Rickard 2026-09-22: ska ej behövas)
    no_plugin_install: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: skippa plugin-erbjudande (Rickard: ska ej behövas)
    no_bootstrap: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: skippa requirements.txt auto-install (Rickard: ska ej behövas)


# ===========================================================================
# ARGUMENT PARSING
# ===========================================================================

def parse_args(argv: List[str]) -> Tuple[AppConfig, AppMode]:
    """Parsa CLI-argument och returnera config + mode."""
    parser = argparse.ArgumentParser(
        prog="Ledgebord",
        description=APP_DESCRIPTION,
        add_help=False,
    )
    parser.add_argument("--diagnostics", action="store_true", help="Aktivera diagnostics-läge")
    parser.add_argument("--safe-mode", action="store_true", help="Kör med dummy-Settings/Store")
    parser.add_argument("--no-tray", action="store_true", help="Inaktivera system tray")
    parser.add_argument("--no-splash", action="store_true", help="Inaktivera splash-screen")
    parser.add_argument("--no-stability", action="store_true", help="Inaktivera stability-system")
    parser.add_argument("--autostart", action="store_true",
                        help="Startad med datorn (Windows-inloggning): starta minimerad i systemfältet")
    parser.add_argument("--no-async", action="store_true", help="Inaktivera async runner")
    parser.add_argument("--no-pwm", action="store_true", help="Inaktivera PWM (adaptive throttle)")
    parser.add_argument("--no-force-show", action="store_true", help="INAKTIVERA force-show (default PÅ)")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Tvinga auto-install av requirements.txt (default: SKIPPA — Rickard 2026-09-22)",
    )
    parser.add_argument(
        "--plugin-install",
        action="store_true",
        help="Visa plugin-installations-erbjudande (default: SKIPPA — Rickard 2026-09-22)",
    )
    # Behåll gamla flaggor som no-ops (default = redan skippa/force-show)
    parser.add_argument("--no-bootstrap", action="store_true", help="(no-op, default skippar redan)")
    parser.add_argument("--no-plugin-install", action="store_true", help="(no-op, default skippar redan)")
    parser.add_argument("--reset", action="store_true", help="Återställ inställningar")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging (DEBUG)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logg-nivå (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} v{APP_VERSION_DISPLAY}")

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        return AppConfig(), AppMode.NORMAL

    # Bestäm mode
    if args.diagnostics:
        mode = AppMode.DIAGNOSTICS
    elif args.safe_mode:
        mode = AppMode.SAFE_MODE
    elif args.no_tray:
        mode = AppMode.NO_TRAY
    elif args.reset:
        mode = AppMode.RESET
    elif args.verbose:
        mode = AppMode.VERBOSE
    else:
        mode = AppMode.NORMAL

    # Bestäm log-nivå
    log_level = args.log_level.upper()
    if args.verbose and log_level == "INFO":
        log_level = "DEBUG"
    if mode == AppMode.DIAGNOSTICS:
        log_level = "DEBUG"

    # Log-fil
    log_file = LOG_FILE

    # Skapa config (frozen)
    config = AppConfig(
        log_level=log_level,
        log_file=log_file,
        show_splash=not args.no_splash,
        enable_stability=not args.no_stability,
        enable_async_runner=not args.no_async,
        enable_pwm=not args.no_pwm,  # NY v6.4
        force_show_widget=not args.no_force_show,  # NY v6.4.1 v7 — DEFAULT PÅ (Rickard 2026-09-22)
        # Rickard 2026-09-22: --no-plugin-install / --no-bootstrap ska ej behövas
        no_plugin_install=not args.plugin_install,  # DEFAULT True (skippa)
        no_bootstrap=not args.bootstrap,  # DEFAULT True (skippa)
    )

    return config, mode


# ===========================================================================
# SAFE IMPORTS
# ===========================================================================

# Tolkning av snabbtangenter bor i core/hotkey_combo.py (ren Python, testbar);
# återexporteras här så att befintliga importer fortsätter fungera.
from core.hotkey_combo import parse_hotkey_combo  # noqa: E402,F401
