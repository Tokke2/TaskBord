# -*- coding: utf-8 -*-
"""Diagnostik, hälsostatus, doktor-dialog, statistik och om-ruta."""

from __future__ import annotations

import json as _stdlib_json
import platform
import sys
import time
from contextlib import suppress
from typing import Any, Dict, List

from app.central_log import get_central_log_stats
from app.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION, APP_VERSION_DISPLAY, COPYRIGHT_YEARS, LOG_PREFIX, ORG_NAME
from app.errors import _describe_exception, _format_compact_traceback, show_error_dialog
from app.formatting import format_bytes, format_uptime
from app.jsonutil import _HAS_ORJSON, _json_dumps
from app.module_loader import ImportStatus
from app.platform_utils import _is_windows


class DiagnosticsMixin:
    """Diagnostik, hälsostatus, doktor-dialog, statistik och om-ruta."""

    # -----------------------------------------------------------------------
    # DIAGNOSTIK (NY v6.4.1)
    # -----------------------------------------------------------------------

    def _run_diagnostics_on_startup(self) -> None:
        """
        NY v6.4.1: Kör diagnostik vid app-start.

        Vad den gör:
          1. validate_startup() — kolla att alla dependencies OK
          2. diagnose_app_health() — komplett app-hälsa
          3. attempt_widget_window_recovery() — flytta widget-fönster vid behov
          4. archive_old_backups() — arkivera gamla backuper

        Loggar resultat men visar inget UI.
        """
        self._log.info(
            f"{LOG_PREFIX} === DIAGNOSTIK VID STARTUP ==="
        )
        # NY v7-fix37: Autostart-självreparation
        with suppress(Exception):
            self._autostart_health_check()
        # 1. validate_startup
        try:
            from stability import validate_startup
            success, errors = validate_startup()
            if not success:
                self._log.warning(
                    f"{LOG_PREFIX} validate_startup: {len(errors)} fel"
                )
                for err in errors[:3]:  # Första 3
                    self._log.warning(f"{LOG_PREFIX}   - {err}")
            else:
                self._log.info(f"{LOG_PREFIX} validate_startup: OK")
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} stability ej importerbar — skippar validate_startup"
            )
        # 2. diagnose_app_health
        try:
            from stability import diagnose_app_health
            diag = diagnose_app_health()
            self._log.info(
                f"{LOG_PREFIX} diagnose_app_health: "
                f"errors={diag['total_errors']}, "
                f"breakers_open={diag['circuit_breakers_open']}, "
                f"issues={len(diag['issues'])}, "
                f"critical_ok={diag['critical_systems_ok']}"
            )
            for issue in diag["issues"]:
                self._log.warning(f"{LOG_PREFIX}   issue: {issue}")
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} diagnose_app_health: stability ej importerbar"
            )
        # 3. attempt_widget_window_recovery
        try:
            from stability import attempt_widget_window_recovery
            rec = attempt_widget_window_recovery()
            if rec["attempted"] > 0:
                self._log.info(
                    f"{LOG_PREFIX} widget recovery: "
                    f"attempted={rec['attempted']}, "
                    f"recovered={rec['recovered']}, "
                    f"failed={rec['failed']}"
                )
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} widget recovery: stability ej importerbar"
            )
        # 4. archive_old_backups (max 10 dagar → års/mån-mapp)
        try:
            from backup import BackupManager
            mgr = BackupManager()
            result = mgr.archive_old_backups(max_age_days=10)
            if result["archived"] > 0:
                self._log.info(
                    f"{LOG_PREFIX} backup-arkivering: {result['archived']} "
                    f"flyttade till års/mån-mapp"
                )
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} backup-arkivering: backup ej importerbar"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} backup-arkivering misslyckades: {e}"
            )
        self._log.info(
            f"{LOG_PREFIX} === DIAGNOSTIK KLAR ==="
        )
        # NY 2026-09-23: Smart cache — rensa __pycache__ varje fredag
        # NY 2026-09-25: Smart log-cleanup — rensa ALLA gamla loggar (behåll dagens)
        with suppress(Exception):
            self._run_friday_pycache_cleanup(at_startup=True)
        with suppress(Exception):
            self._run_friday_log_cleanup(at_startup=True)

    def _get_app_health_status(self) -> Dict[str, Any]:
        """
        NY v6.4.1: Hämta komplett app-hälsa (för UI + diagnostik).
        """
        issues: List[str] = []
        widget_count = len(self._widgets) if hasattr(self, "_widgets") else 0
        task_count = 0
        if self.store is not None and hasattr(self.store, "count"):
            try:
                active, _archive = self.store.count()
                task_count = active
            except Exception:
                pass
        autostart_status: Dict[str, Any] = {"enabled": False}
        if self.settings is not None and hasattr(
            self.settings, "get_autostart_status"
        ):
            try:
                autostart_status = self.settings.get_autostart_status()
                if not autostart_status.get("consistent"):
                    issues.append("Autostart: settings vs OS inkonsistent")
            except Exception:
                pass
        stability_health: Dict[str, Any] = {"total_errors": 0, "issues": []}
        try:
            from stability import diagnose_app_health
            stability_health = diagnose_app_health()
            issues.extend(stability_health.get("issues", []))
        except ImportError:
            pass
        # NY v6.4.1 v7: Logg-stats med svensk evaluering
        log_stats: Dict[str, Any] = {"total_lines": 0, "by_level": {}, "total_size_bytes": 0}
        try:
            from logger_setup import get_log_stats
            log_stats = get_log_stats()
            by_level = log_stats.get("by_level", {})
            err_count = by_level.get("ERROR", 0)
            critical_count = by_level.get("CRITICAL", 0)
            warning_count = by_level.get("WARNING", 0)
            # Bygg svenska issues
            if err_count > 10:
                issues.append(
                    f"Manga errors i loggar: {err_count} "
                    f"(kolla data/logs/session_*.log)"
                )
            if critical_count > 0:
                issues.append(
                    f"Kritiska fel i loggar: {critical_count} "
                    f"(bor undersökas omedelbart)"
                )
            if warning_count > 50:
                issues.append(
                    f"Manga varningar: {warning_count} "
                    f"(kan indikera instabilitet)"
                )
        except ImportError:
            pass
        uptime_sec = 0.0
        if hasattr(self, "_start_time"):
            uptime_sec = time.time() - self._start_time
        # Logga health-snapshot for felsokning
        self._log.debug(
            f"{LOG_PREFIX} _get_app_health_status: "
            f"widgets={widget_count}, tasks={task_count}, "
            f"uptime={uptime_sec:.0f}s, issues={len(issues)}"
        )
        return {
            "app_version": APP_VERSION,
            "uptime_sec": uptime_sec,
            "widget_count": widget_count,
            "task_count": task_count,
            "autostart_status": autostart_status,
            "stability_health": stability_health,
            "log_stats": log_stats,
            "issues": issues,
            "uptime_human": format_uptime(uptime_sec),
        }

    def show_doctor_dialog(self) -> None:
        """
        NY v6.4.1 v7: 🔧 Visa Doctor-dialog (188888888% bättre design).

        Vad den visar (svenska, lasbart format):
          - App-version + uptime (formaterad som "X timmar, Y minuter")
          - Widget-antal + task-antal
          - Autostart-status (enabled + konsistens)
          - Stability-health (errors + breakers)
          - Log-statistik (total lines + per level)
          - Issues-lista (om problem finns)
        """
        try:
            health = self._get_app_health_status()
            n_issues = len(health["issues"])
            self._log.info(
                f"{LOG_PREFIX} Doctor-dialog: {n_issues} issues"
            )
            # Formatera uptime svenskt
            uptime_sv = format_uptime(health["uptime_sec"])
            # Formatera logg-bytes
            total_bytes = health["log_stats"].get("total_size_bytes", 0)
            log_size = format_bytes(total_bytes)
            # Bygg issues-text
            issues_text = (
                "\n".join(f"  - {i}" for i in health["issues"])
                if health["issues"]
                else "  - Inga problem!"
            )
            # Status-emoji baserat pa issues
            if n_issues == 0:
                status_icon = "✅"
                status_text = "Allt ser bra ut!"
            else:
                status_icon = "⚠️"
                status_text = f"{n_issues} problem behöver atgärd"
            # Bygg dialog-text
            summary = (
                f"=== APP HEALTH v{health['app_version']} ===\n\n"
                f"{status_icon} Status: {status_text}\n\n"
                f"Widgets: {health['widget_count']} "
                f"(uppgifter i minnet)\n"
                f"Tasks: {health['task_count']} aktiva\n"
                f"Uptime: {uptime_sv}\n"
                f"Autostart: "
                f"{'✅ aktiverad' if health['autostart_status'].get('enabled') else '⚪ avstängd'} "
                f"({'konsistent' if health['autostart_status'].get('consistent') else 'INKONSISTENT — kolla!'})\n\n"
                f"=== STABILITY ===\n"
                f"Errors totalt: {health['stability_health'].get('total_errors', 0)}\n"
                f"Circuit breakers öppna: "
                f"{health['stability_health'].get('circuit_breakers_open', 0)}\n\n"
                f"=== LOGGAR ===\n"
                f"Totalt antal rader: {health['log_stats'].get('total_lines', 0)}\n"
                f"Storlek: {log_size}\n"
                f"Per nivå: {health['log_stats'].get('by_level', {})}\n"
            )

            # NY v6.4.1 v7: Lägg till central log-statistik
            try:
                central_stats = get_central_log_stats()
                summary += (
                    f"\n=== CENTRAL LOGG (NY v7) ===\n"
                    f"Events i minnet: {central_stats['total_events']}/"
                    f"{central_stats['max_events']}\n"
                    f"Per nivå: {central_stats['by_level']}\n"
                    f"Per modul (top 5): "
                    f"{dict(list(central_stats['by_module'].items())[:5])}\n"
                    f"Aktiva lyssnare: {central_stats['listener_count']}\n"
                )
            except Exception as central_err:
                summary += f"\n=== CENTRAL LOGG ===\n(kunde inte ladda: {central_err})\n"

            summary += f"\n=== PROBLEM ===\n{issues_text}\n"
            self._show_simple_error(
                f"🔧 Doctor — App Health (v{health['app_version']})",
                summary,
            )
            self._log.info(
                f"{LOG_PREFIX} Doctor-dialog stängd (visade {n_issues} issues)"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Doctor-dialog misslyckades: {e}",
                exc_info=True,
            )
            show_error_dialog(
                title="Doctor misslyckades",
                user_message=_describe_exception(e),
                technical=_format_compact_traceback(e),
                category="code_bug",
            )

    def _refresh_metrics(self) -> None:
        """Uppdatera performance-metrics + tooltip."""
        try:
            self._performance.take_snapshot()
            self._update_tray_tooltip()
        except Exception as e:
            self._log.debug(f"refresh_metrics misslyckades: {e}")

    def _refresh_capabilities(self) -> None:
        """Uppdatera capabilities-cache (Win32 features, HWND-stöd, etc.)."""
        try:
            caps: Dict[str, Any] = {
                "platform": sys.platform,
                "is_windows": _is_windows(),
                "python_version": sys.version.split()[0],
                "pyside6_available": False,
                "mica_supported": False,
                "acrylic_supported": False,
                "tray_available": False,
            }
            if self._imports.get("PySide6.QtWidgets", ImportStatus("", False)).ok:
                caps["pyside6_available"] = True
                if self._QSystemTrayIcon:
                    caps["tray_available"] = self._QSystemTrayIcon.isSystemTrayAvailable()
            # Mica/acrylic kräver Win10+ vissa builds
            if _is_windows():
                try:
                    import platform as _p
                    win_ver = _p.win32_ver()
                    caps["win_version"] = win_ver
                    major, _, _ = (int(x) if x.isdigit() else 0 for x in win_ver[1].split("."))
                    caps["mica_supported"] = major >= 10
                    caps["acrylic_supported"] = major >= 10
                except Exception:
                    pass
            self._capabilities = caps
            self._log.debug(f"Capabilities: {caps}")
        except Exception as e:
            self._log.debug(f"refresh_capabilities misslyckades: {e}")

    def show_statistics(self) -> None:
        """Visa statistik-dialog (med subsystem-status)."""
        if not self._app or self._QMessageBox is None:
            return
        try:
            active, archived = (0, 0)
            if hasattr(self.store, "count"):
                active, archived = self.store.count()
            perf_snap = self._performance.take_snapshot()
            uptime = self._performance.format_uptime()
            subsystem_status = self._registry.get_all_status()

            lines = [
                f"📊  Statistik — {APP_NAME} v{APP_VERSION_DISPLAY}",
                "─" * 50,
                f"Aktiva uppgifter:    {active}",
                f"Arkiverade:          {archived}",
                f"Fönster:             {len(self._widgets)}",
                "─" * 50,
                f"Uptime:              {uptime}",
                f"Minne (RSS):         {perf_snap.memory_mb:.1f} MB",
                f"Trådar:              {perf_snap.thread_count}",
                f"GC-obj:            {perf_snap.gc_objects}",
                "─" * 50,
                f"Subsystems:          {len(subsystem_status)}",
            ]
            for name, info in subsystem_status.items():
                status_icon = "✓" if info["status"] == "HEALTHY" else "✗"
                hr_pct = int(info.get("health_ratio", 1.0) * 100)
                lines.append(
                    f"  {status_icon} {name:<15} {info['status']:<10} "
                    f"({hr_pct}% health)"
                )

            lines.append("─" * 50)
            lines.append(f"Python:     {platform.python_version()}")
            lines.append(f"Plattform:  {platform.system()} {platform.release()}")
            if self._capabilities:
                lines.append(f"Capabilities: {len(self._capabilities)} st")

            self._QMessageBox.information(
                None,
                f"{APP_NAME} — Statistik",
                "\n".join(lines),
            )
        except Exception as e:
            self._log.error(f"show_statistics misslyckades: {e}")

    def show_about(self) -> None:
        """Visa Om-dialog."""
        if not self._app or self._QMessageBox is None:
            return
        try:
            msg = (
                f"{APP_NAME} v{APP_VERSION_DISPLAY}\n"
                f"Copyright {ORG_NAME}, {COPYRIGHT_YEARS}\n"
                f"\n"
                f"{APP_DESCRIPTION}\n"
                f"\n"
                f"Funktioner:\n"
                f"  • Pin-funktion för viktiga uppgifter\n"
                f"  • Glasmorphism med mica/acrylic\n"
                f"  • Stability-system med auto-recovery\n"
                f"  • Backup med auto-restore\n"
                f"  • Multi-window + tray-icon\n"
                f"  • BUGG 19/26-fix: widget alltid synlig, aldrig över ikoner\n"
                f"\n"
                f"Donation: inaktiverad (R4 pausad 2026-08-11)\n"
            )
            self._QMessageBox.about(None, f"Om {APP_NAME}", msg)
        except Exception as e:
            self._log.error(f"show_about misslyckades: {e}")

    def _dump_subsystem_status(self) -> None:
        """Dump subsystem-status till logg (diagnostics-läge, NY v6.4: orjson)."""
        try:
            status = self._registry.get_all_status()
            # NY v6.4: använd orjson om tillgängligt (18× snabbare)
            json_str = _json_dumps(status).decode("utf-8") if _HAS_ORJSON else _stdlib_json.dumps(status, indent=2, default=str)
            self._log.info(f"=== SUBSYSTEM-DUMP ===\n{json_str}")
        except Exception as e:
            self._log.error(f"dump_subsystem_status misslyckades: {e}")
