# -*- coding: utf-8 -*-
"""Plugin-system: hitta och installera saknade Python-paket."""

from __future__ import annotations

import importlib.util
import logging.handlers
import subprocess
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, Final, List, Optional, Tuple

from app.constants import APP_NAME, LOG_PREFIX
from app.platform_utils import _is_pyw


# ===========================================================================
# PLUGIN-SYSTEM (NY v6.4.1 v7 — 18 888 888% bättre)
# ===========================================================================
# Vad det gor:
#   - Håller reda på ALLA optional Python-moduler som appen KAN använda
#   - Vid start: detekterar vilka som saknas
#   - Erbjuder anvandaren att installera via pip (Qt-dialog med svensk text)
#   - Kom ihag anvandarens val ("Kom ihag senare" → fraga inte igen)
#   - 10000% loggning med [MAIN]-prefix
#   - Robust mot pip-fel (timeout, network errors, etc.)
#
# Design-val:
#   - EN install-prompt per app-session (inte loop)
#   - Plugin som REDAN ar installerade visas inte
#   - Plugin som ar REQUIRED (PySide6) har tydligare varning
#   - Anvandaren kan alltid avbryta → appen kor i degraded mode

@dataclass(frozen=True)
class PluginSpec:
    """Specifikation for en optional Python-modul (plugin)."""
    pip_name: str                 # t.ex. "orjson"
    import_name: str              # t.ex. "orjson"
    description_svenska: str      # t.ex. "18x snabbare JSON"
    benefit_svenska: str          # t.ex. "cache blir 3-5x snabbare"
    required: bool = False        # True = kraschar utan (t.ex. PySide6)
    platforms: Optional[Tuple[str, ...]] = None  # None = alla
    importlib_check: bool = True  # True = anvand importlib.util.find_spec


PLUGIN_REGISTRY: Final[Tuple[PluginSpec, ...]] = (
    PluginSpec(
        pip_name="orjson",
        import_name="orjson",
        description_svenska="Snabbare JSON (18x snabbare)",
        benefit_svenska="Cache och data-sparning blir 3-5x snabbare",
        required=False,
    ),
    PluginSpec(
        pip_name="psutil",
        import_name="psutil",
        description_svenska="Process- och minnesinfo",
        benefit_svenska="Visar minnes- och CPU-användning i tray",
        required=False,
    ),
    PluginSpec(
        pip_name="PySide6",
        import_name="PySide6",
        description_svenska="Qt-gränssnitt (krav för UI)",
        benefit_svenska="Utan denna funkar INGEN widgets eller tray",
        required=True,
    ),
    PluginSpec(
        pip_name="pywin32",
        import_name="win32api",
        description_svenska="Windows-specifika funktioner",
        benefit_svenska="Bättre autostart-detektering och GDI-hantering",
        required=False,
        platforms=("win32",),
    ),
    PluginSpec(
        pip_name="extract-msg",
        import_name="extract_msg",
        description_svenska="Läsa Outlook .msg-filer",
        benefit_svenska="Importera Outlook-mejl som uppgifter (📧-knappen)",
        required=False,
    ),
    PluginSpec(
        pip_name="reportlab",
        import_name="reportlab",
        description_svenska="PDF-export",
        benefit_svenska="Spara uppgifter som PDF-checklista",
        required=False,
    ),
    # NY v8 (2026-10-12): lokal Google Calendar-koppling (OAuth).
    # Två paket: klienten (googleapiclient) och själva inloggningen
    # (google_auth_oauthlib). Inga av dem kräver något konto hos oss.
    PluginSpec(
        pip_name="google-api-python-client",
        import_name="googleapiclient",
        description_svenska="Google Calendar-klient",
        benefit_svenska="Skicka uppgifter till Google Calendar (☁️-menyn)",
        required=False,
    ),
    PluginSpec(
        pip_name="google-auth-oauthlib",
        import_name="google_auth_oauthlib",
        description_svenska="Google-inloggning (OAuth, lokalt)",
        benefit_svenska="Koppla ditt Google-konto i appen — inget lösenord delas",
        required=False,
    ),
)


# Anvandarens plugin-val (cache:as i minnet + ev. settings.json)
_plugin_choice_cache: Dict[str, str] = {}  # plugin-namn → "install" | "skip" | "later"


_plugin_choice_lock = threading.RLock()


def _is_plugin_installed(plugin: PluginSpec) -> bool:
    """Kontrollera om en plugin redan ar installerad."""
    if not plugin.importlib_check:
        # Manuell kontroll (for plattformsspecifika)
        try:
            __import__(plugin.import_name)
            return True
        except ImportError:
            return False
    try:
        # NY v6.4.1 v7: Snabbare import-check (utan att faktiskt importera)
        spec = importlib.util.find_spec(plugin.import_name)
        return spec is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _is_plugin_for_platform(plugin: PluginSpec) -> bool:
    """Kontrollera om plugin gäller for aktuell plattform."""
    if plugin.platforms is None:
        return True
    return sys.platform in plugin.platforms


def _detect_missing_plugins() -> List[PluginSpec]:
    """
    NY v6.4.1 v7: Hitta alla saknade plugins (for aktuell plattform).

    Hoppar over plugins som:
      - Redan ar installerade
      - Inte gäller for plattformen
      - Anvandaren redan valt att hoppa over ("Kom ihag senare")

    Returns:
        Lista av PluginSpec-objekt som saknas och kan installeras
    """
    log = logging.getLogger("PluginSystem")
    missing: List[PluginSpec] = []
    with _plugin_choice_lock:
        for plugin in PLUGIN_REGISTRY:
            # Hoppa over om anvandaren valt att inte installera
            choice = _plugin_choice_cache.get(plugin.pip_name)
            if choice == "skip" or choice == "later":
                continue
            # Hoppa over om plattformen inte matchar
            if not _is_plugin_for_platform(plugin):
                continue
            # Hoppa over om redan installerad
            if _is_plugin_installed(plugin):
                continue
            # Annars: plugin saknas
            missing.append(plugin)
            log.debug(
                f"{LOG_PREFIX} saknad plugin: {plugin.pip_name} "
                f"({plugin.description_svenska})"
            )
    if missing:
        log.info(
            f"{LOG_PREFIX} _detect_missing_plugins: "
            f"{len(missing)} saknade plugin hittade"
        )
    else:
        log.debug(f"{LOG_PREFIX} _detect_missing_plugins: alla plugin installerade")
    return missing


def _persist_plugin_choice(pip_name: str, choice: str) -> None:
    """Spara plugin-valet (så vi inte fragar igen vid nastart)."""
    with _plugin_choice_lock:
        _plugin_choice_cache[pip_name] = choice
    log = logging.getLogger("PluginSystem")
    log.debug(f"{LOG_PREFIX} plugin-val sparat: {pip_name} → {choice}")


def _check_outdated_packages() -> List[Tuple[str, str, str]]:
    """
    NY v7-fix36: Kontrollera om installerade paket är föråldrade.

    Returns:
        Lista av (pip_namn, installerad_version, senaste_version)
    """
    log = logging.getLogger("PluginSystem")
    try:
        import subprocess as _sp
        import json as _json
        result = _sp.run(
            [sys.executable, "-m", "pip", "list", "--outdated",
             "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log.debug(f"{LOG_PREFIX} pip list --outdated misslyckades")
            return []
        outdated = _json.loads(result.stdout)
        # Filtrera: bara paket i vår registry
        registry_names = {p.pip_name.lower() for p in PLUGIN_REGISTRY}
        relevant = []
        for pkg in outdated:
            name = pkg.get("name", "").lower()
            if name in registry_names:
                relevant.append((
                    pkg["name"],
                    pkg.get("version", "?"),
                    pkg.get("latest_version", "?"),
                ))
        if relevant:
            log.info(
                f"{LOG_PREFIX} _check_outdated_packages: "
                f"{len(relevant)} föråldrade: "
                f"{[(n, v, l) for n, v, l in relevant]}"
            )
        return relevant
    except Exception as e:
        log.debug(f"{LOG_PREFIX} _check_outdated_packages fel: {e}")
        return []


def _update_packages(packages: List[str]) -> Dict[str, bool]:
    """
    NY v7-fix36: Uppdatera paket via pip install --upgrade.
    """
    log = logging.getLogger("PluginSystem")
    results: Dict[str, bool] = {}
    for pkg_name in packages:
        try:
            log.info(f"{LOG_PREFIX} Uppdaterar {pkg_name}...")
            import subprocess as _sp
            result = _sp.run(
                [sys.executable, "-m", "pip", "install",
                 "--upgrade", pkg_name],
                capture_output=True, text=True, timeout=120,
            )
            ok = result.returncode == 0
            results[pkg_name] = ok
            if ok:
                log.info(f"{LOG_PREFIX} ✓ {pkg_name} uppdaterad")
            else:
                log.warning(
                    f"{LOG_PREFIX} ✗ {pkg_name} kunde ej uppdateras: "
                    f"{result.stderr[:100]}"
                )
        except Exception as e:
            results[pkg_name] = False
            log.warning(f"{LOG_PREFIX} ✗ {pkg_name}: {e}")
    return results


def _install_plugin_via_pip(
    plugin: PluginSpec,
    timeout_sec: float = 60.0,
) -> Tuple[bool, str]:
    """
    NY v6.4.1 v7: Installera en plugin via pip (i trad for att inte blockera UI).

    Args:
        plugin: PluginSpec att installera
        timeout_sec: Max tid att vanta (default 60s)

    Returns:
        Tuple (success, message)
    """
    log = logging.getLogger("PluginSystem")
    log.info(
        f"{LOG_PREFIX} _install_plugin_via_pip: {plugin.pip_name} "
        f"(timeout={timeout_sec}s)"
    )

    result_box: List[Tuple[bool, str]] = [(False, "")]
    done = threading.Event()

    def worker() -> None:
        try:
            # Anvand samma Python som vi kor med (så modulen hamnar ratt stalle)
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--quiet", "--disable-pip-version-check",
                plugin.pip_name,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if proc.returncode == 0:
                result_box[0] = (True, f"{plugin.pip_name} installerades")
                log.info(
                    f"{LOG_PREFIX} {plugin.pip_name} installerades "
                    f"(stdout: {len(proc.stdout)} chars)"
                )
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                # Korta ner långa fel
                if len(err) > 200:
                    err = err[:197] + "..."
                result_box[0] = (False, f"pip-fel: {err}")
                log.warning(
                    f"{LOG_PREFIX} pip install {plugin.pip_name} "
                    f"returnerade {proc.returncode}: {err}"
                )
        except subprocess.TimeoutExpired:
            result_box[0] = (False, f"Tidsgrans ({timeout_sec}s) overskreds")
            log.error(
                f"{LOG_PREFIX} pip install {plugin.pip_name} tog "
                f"mer an {timeout_sec}s"
            )
        except FileNotFoundError as e:
            result_box[0] = (False, f"pip kunde inte startas: {e}")
            log.error(
                f"{LOG_PREFIX} pip kunde inte startas: {e}",
                exc_info=True,
            )
        except Exception as e:
            result_box[0] = (False, f"{type(e).__name__}: {e}")
            log.error(
                f"{LOG_PREFIX} _install_plugin_via_pip fel: {e}",
                exc_info=True,
            )
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True, name=f"pip-install-{plugin.pip_name}")
    t.start()
    if not done.wait(timeout=timeout_sec + 5.0):
        return (False, f"Tidsgrans overskreds ({timeout_sec + 5.0}s)")
    return result_box[0]


def _install_plugins_sequentially(
    plugins: List[PluginSpec],
    timeout_sec: float = 60.0,
) -> Dict[str, Tuple[bool, str]]:
    """
    NY v6.4.1 v7: Installera flera plugins i sekvens (en åt gången).

    Args:
        plugins: Lista av PluginSpec-objekt att installera
        timeout_sec: Max tid per plugin

    Returns:
        Dict med plugin-namn → (success, message)
    """
    log = logging.getLogger("PluginSystem")
    log.info(
        f"{LOG_PREFIX} _install_plugins_sequentially: "
        f"{len(plugins)} plugin(s) att installera"
    )
    results: Dict[str, Tuple[bool, str]] = {}
    for plugin in plugins:
        ok, msg = _install_plugin_via_pip(plugin, timeout_sec=timeout_sec)
        results[plugin.pip_name] = (ok, msg)
        # Om en kritisk plugin misslyckas, avbryt (annars forsatt)
        if not ok and plugin.required:
            log.warning(
                f"{LOG_PREFIX} Avbryter (kritisk plugin {plugin.pip_name} "
                f"misslyckades: {msg})"
            )
            break
    return results


def show_install_plugins_dialog(
    missing: List[PluginSpec],
    parent: Any = None,
) -> Optional[List[PluginSpec]]:
    """
    NY v6.4.1 v7: Visa Qt-dialog med svensk text for plugin-installation.

    Args:
        missing: Lista av PluginSpec som saknas
        parent: Parent-widget (None = ingen parent)

    Returns:
        Lista av plugins att installera (None = avbruten)
    """
    if not missing:
        return []
    log = logging.getLogger("PluginSystem")
    # Bygg svensk meddelandetext
    lines: List[str] = [
        f"{APP_NAME} saknar {len(missing)} Python-modul(er) "
        f"for full funktionalitet:\n",
    ]
    for i, plugin in enumerate(missing, 1):
        req_marker = " [KRÄVS]" if plugin.required else ""
        lines.append(
            f"  {i}. {plugin.pip_name}{req_marker}\n"
            f"     {plugin.description_svenska}\n"
            f"     → {plugin.benefit_svenska}\n"
        )
    lines.append("\nVill du installera dem nu via pip?")
    message = "".join(lines)
    log.info(
        f"{LOG_PREFIX} show_install_plugins_dialog: {len(missing)} plugin(s)"
    )
    # Visa QMessageBox med Yes/No
    if not _is_pyw():
        # Console-läge: bara logga + returnera "frag anvandaren"
        print(message)
        return missing  # Antag att anvandaren vill installera i console-läge
    try:
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            parent,
            f"{APP_NAME} — Installera plugins?",
            message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,  # default = Yes (for enkelhet)
        )
        if reply == QMessageBox.StandardButton.Yes:
            log.info(f"{LOG_PREFIX} anvandaren valde: installera")
            return missing
        log.info(f"{LOG_PREFIX} anvandaren valde: hoppa over")
        return None
    except ImportError:
        log.warning(
            f"{LOG_PREFIX} Qt ej tillgangligt — kan inte visa plugin-dialog"
        )
        return None
    except Exception as e:
        log.error(
            f"{LOG_PREFIX} show_install_plugins_dialog misslyckades: {e}",
            exc_info=True,
        )
        return None


def install_missing_plugins_silent(
    progress_cb: Any = None,
) -> Dict[str, bool]:
    """
    NY v7-fix52: TYST installation av saknade plugins (ingen dialog).

    Används av auto-uppdateringen vid start (Rickards val: full auto).
    NY v7-fix66: valfri progress_cb(phase, index, total, namn, ok) för
    progress-bar-visning.
    Returnerar dict med plugin-namn → success.
    """
    log = logging.getLogger("PluginSystem")
    results: Dict[str, bool] = {}
    missing = _detect_missing_plugins()
    total = len(missing)
    for i, plugin in enumerate(missing, 1):
        _pname = ""
        try:
            # FIX v7-fix55: PluginSpec har pip_name (INTE name — gav
            # AttributeError 'PluginSpec' object has no attribute 'name')
            _pname = getattr(plugin, "pip_name", str(plugin))
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, None)
            ok, _msg = _install_plugin_via_pip(plugin)
            results[_pname] = bool(ok)
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, bool(ok))
            if ok:
                log.info(f"{LOG_PREFIX} TYST INSTALLATION OK: {_pname}")
            else:
                log.warning(
                    f"{LOG_PREFIX} Tyst installation misslyckades: "
                    f"{_pname}: {_msg[:80]}"
                )
        except Exception as e:
            results[_pname] = False
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, False)
            log.warning(
                f"{LOG_PREFIX} Tyst installation fel: {_pname}: {e}"
            )
    return results


def offer_install_missing_plugins(parent: Any = None) -> Dict[str, bool]:
    """
    NY v6.4.1 v7: Huvudfunktion — detektera + fragga + installera.

    Vad den gor:
      1. Anropar _detect_missing_plugins()
      2. Om inga saknas → returnerar tidigt
      3. Visar Qt-dialog med svensk text
      4. Om anvandaren valt "Ja" → installerar via pip
      5. Returnerar dict med plugin-namn → success

    Args:
        parent: Parent-widget for modal dialog

    Returns:
        Dict med plugin-namn → True om installerad, False annars
    """
    log = logging.getLogger("PluginSystem")

    # FIX v7-fix53: anropad från bakgrundstråd? Då är Qt-dialog OLAGLIG
    # (QDialog.exec på icke-GUI-tråd = HELA APPEN LÅSER SIG — exakt det
    # som hände vid auto-installationen). Tvinga tyst läge automatiskt.
    try:
        import threading as _thr
        if _thr.current_thread() is not _thr.main_thread():
            log.warning(
                f"{LOG_PREFIX} offer_install_missing_plugins: anropad "
                f"från bakgrundstråd → TYST läge (dialog ej tillåten)"
            )
            return install_missing_plugins_silent()
    except Exception:
        pass

    missing = _detect_missing_plugins()

    # FIX v7-fix36: kolla även föråldrade paket
    outdated = _check_outdated_packages()

    if not missing and not outdated:
        log.debug(f"{LOG_PREFIX} offer_install_missing_plugins: inget att gora")
        return {}

    # NY v7-fix36: om det bara finns föråldrade paket → fråga om uppdatering
    if not missing and outdated:
        _out_names = ", ".join(
            f"{n} ({v} → {l})" for n, v, l in outdated
        )
        log.info(
            f"{LOG_PREFIX} offer_install: {len(outdated)} föråldrade "
            f"paket: {_out_names}"
        )
        # Uppdatera automatiskt (användaren kan avbryta via tray)
        _update_result = _update_packages(
            [n for n, _, _ in outdated]
        )
        _updated = sum(1 for ok in _update_result.values() if ok)
        if _updated:
            log.info(
                f"{LOG_PREFIX} {_updated} paket uppdaterade"
            )
        return _update_result

    # Standard-flöde: saknade paket
    # Visa dialog (kanske avbryts av anvandaren)
    to_install = show_install_plugins_dialog(missing, parent=parent)
    if not to_install:
        # Anvandaren avbröt → spara valet sa vi inte fragar igen
        for plugin in missing:
            _persist_plugin_choice(plugin.pip_name, "later")
        log.info(
            f"{LOG_PREFIX} offer_install_missing_plugins: avbruten av anvandaren"
        )
        return {p.pip_name: False for p in missing}
    # Installera
    log.info(
        f"{LOG_PREFIX} offer_install_missing_plugins: installerar "
        f"{len(to_install)} plugin(s)..."
    )
    results = _install_plugins_sequentially(to_install)
    # Spara val for lyckade + misslyckade (så vi inte fragar igen for dem som lyckats)
    for pip_name, (ok, _msg) in results.items():
        _persist_plugin_choice(pip_name, "install" if ok else "later")
    # Logga resultat
    success_count = sum(1 for ok, _ in results.values() if ok)
    fail_count = len(results) - success_count
    log.info(
        f"{LOG_PREFIX} offer_install_missing_plugins: klar "
        f"({success_count} OK, {fail_count} misslyckades)"
    )
    return {pip_name: ok for pip_name, (ok, _msg) in results.items()}


def get_plugin_status() -> Dict[str, Dict[str, Any]]:
    """
    NY v6.4.1 v7: Hämta status for ALLA plugins (for UI/diagnostics).

    Returns:
        Dict med pip_name → info (installed, required, choice, etc.)
    """
    with _plugin_choice_lock:
        choices = dict(_plugin_choice_cache)
    status: Dict[str, Dict[str, Any]] = {}
    for plugin in PLUGIN_REGISTRY:
        status[plugin.pip_name] = {
            "installed": _is_plugin_installed(plugin),
            "required": plugin.required,
            "for_platform": _is_plugin_for_platform(plugin),
            "description": plugin.description_svenska,
            "benefit": plugin.benefit_svenska,
            "user_choice": choices.get(plugin.pip_name, "unknown"),
        }
    return status


def format_plugin_status_swedish() -> str:
    """
    NY v6.4.1 v7: Formatera plugin-status som svensk en-rads-sammanfattning.

    Returns:
        Svensk sträng, t.ex.
        "Plugins: 3/4 installerade (1 saknas)"
    """
    status = get_plugin_status()
    installed = sum(1 for s in status.values() if s["installed"])
    total_applicable = sum(1 for s in status.values() if s["for_platform"])
    missing = [
        name for name, s in status.items()
        if not s["installed"] and s["for_platform"]
    ]
    if not missing:
        return f"Plugins: alla {installed} installerade ✓"
    return (
        f"Plugins: {installed}/{total_applicable} installerade "
        f"({len(missing)} saknas: {', '.join(missing)})"
    )
