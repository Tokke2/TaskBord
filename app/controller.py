# -*- coding: utf-8 -*-
"""AppController: sammanhållaren som äger Qt-appen, tray, fönster och delsystem."""

from __future__ import annotations

import logging.handlers
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from app.config import AppConfig, error_boundary
from app.constants import APP_NAME, AppMode, GlassStyle, LOG_PREFIX, SCRIPT_DIR, StartupError, Timeouts
from app.formatting import format_uptime
from app.mixins.addon_update import AddonUpdateMixin
from app.mixins.app_icon import AppIconMixin
from app.mixins.autostart import AutostartMixin
from app.mixins.backup_sync import BackupSyncMixin
from app.mixins.clip_task import ClipTaskMixin
from app.mixins.desktop_shell import DesktopShellMixin
from app.mixins.diagnostics import DiagnosticsMixin
from app.mixins.exports import ExportsMixin
from app.mixins.hotkeys import HotkeysMixin
from app.mixins.mail_bridge_ctl import MailBridgeMixin
from app.mixins.maintenance import MaintenanceMixin
from app.mixins.plugin_updates import PluginUpdateMixin
from app.mixins.reminders import RemindersMixin
from app.mixins.top_toggle import TopToggleMixin
from app.mixins.tray import TrayMixin
from app.mixins.updates import UpdateMixin
from app.mixins.windows import WindowsMixin
from app.module_loader import ImportStatus
from app.performance import AsyncTaskRunner, PerformanceMonitor
from app.plugins import offer_install_missing_plugins
from app.splash import hide_splash
from app.subsystems import SubsystemRegistry


class AppController(
    DesktopShellMixin,
    AppIconMixin,
    DiagnosticsMixin,
    WindowsMixin,
    HotkeysMixin,
    ClipTaskMixin,
    TopToggleMixin,
    RemindersMixin,
    BackupSyncMixin,
    MailBridgeMixin,
    UpdateMixin,
    AddonUpdateMixin,
    PluginUpdateMixin,
    TrayMixin,
    AutostartMixin,
    MaintenanceMixin,
    ExportsMixin,
):
    """
    Huvudkontroll med dependency injection + subsystem-registry.

    Ansvar:
        1. Initiera QApplication + alla subsystems
        2. Skapa + underhålla TodoWidget-fönster (BUGG 19/26)
        3. System tray (med populate_tray_menu, dynamisk tooltip)
        4. Input-dialoger (ask_new_task, ask_rename_task, ask_confirm_delete)
        5. Backup-integration (auto-restore, periodic status-check)
        6. Stability (heartbeat, recovery, idle-detection)
        7. Shutdown (graceful, trådsäker)
    """

    # Timing-konstanter (millisekunder)
    CLEANUP_INTERVAL_MS: ClassVar[int] = 5 * 60 * 1000

    METRICS_REFRESH_MS: ClassVar[int] = 30 * 1000

    BACKUP_CHECK_INTERVAL_MS: ClassVar[int] = 60 * 1000

    CAPABILITIES_REFRESH_MS: ClassVar[int] = 5 * 60 * 1000

    HEARTBEAT_INTERVAL_MS: ClassVar[int] = 5 * 1000

    IDLE_CHECK_INTERVAL_MS: ClassVar[int] = 30 * 1000

    def __init__(
        self,
        config: AppConfig,
        mode: AppMode,
        imports: Dict[str, ImportStatus],
        registry: SubsystemRegistry,
        performance: PerformanceMonitor,
        async_runner: AsyncTaskRunner,
    ) -> None:
        self._log = logging.getLogger("AppController")
        self._config = config
        self._mode = mode
        self._imports = imports
        self._registry = registry
        self._performance = performance
        self._async_runner = async_runner

        self._app: Optional[Any] = None
        self._widgets: Dict[str, Any] = {}
        self._widget_lock = threading.RLock()
        self._shutdown_initiated = False
        self._start_time = time.time()

        # State
        self._glass_style: str = GlassStyle.AUTO.value
        self._tray: Any = None
        self._tray_menu: Any = None
        self._tray_initialized = threading.Event()
        self._icon_cache: Dict[str, Any] = {}
        self._icon_cache_lock = threading.Lock()
        self._last_tooltip_update: float = 0.0
        self._capabilities: Dict[str, Any] = {}

        # Initiera i ordning
        self._init_qt_application()
        self._init_subsystems()
        self._init_timers()
        self._init_signals()
        self._refresh_capabilities()

        self._log.info(
            f"AppController klar (fönster={len(self._widgets)}, "
            f"mode={mode.name})"
        )

    # -----------------------------------------------------------------------
    # INIT — QApplication
    # -----------------------------------------------------------------------

    def _init_qt_application(self) -> None:
        """Initiera QApplication (eller skapa dummy)."""
        QtWidgets = self._imports.get("PySide6.QtWidgets")
        if QtWidgets is None or not QtWidgets.ok:
            raise StartupError("QApplication kan inte skapas (QtWidgets saknas)")

        QApplicationCls = QtWidgets.instance["QApplication"]
        self._set_app_user_model_id()  # egen identitet i aktivitetsfältet (inte Pythons) — före första fönstret
        self._app = QApplicationCls(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName(self._config.app_name)
        self._app.setApplicationVersion(self._config.app_version)
        self._app.setOrganizationName(self._config.org_name)

        # FIX 2026-09-23: App-ikon → aktivitetsfält + Aktivitetshanterare
        # FIX v7-fix22: INGEN ikon sätts FÖRE det första fönstret!
        # Qt registrerar fönsterklassen vid första CreateWindowEx — om
        # ikonen då är förgiftad misslyckas ALLA efterföljande skapanden
        # ('Felaktig parameter'). Ikonerna sätts i _populate_windows
        # EFTER att fönstret faktiskt skapats.
        self._app_icon = None
        self._app_icon_path: Optional[Path] = None
        self._app_icon_set_on_first_window: bool = False
        with suppress(Exception):
            # ENDAST validera/förbered filen — sätt den INTE på appen än
            self._app_icon_path = self._ensure_app_icon_file()
            if self._app_icon_path is not None:
                self._log.info(
                    f"{LOG_PREFIX} App-ikon förberedd (sätts efter första "
                    f"fönstret, v7-fix22): {self._app_icon_path}"
                )

        # Installera global exception hook (Qt-specifik)
        with suppress(Exception):
            self._app.aboutToQuit.connect(self._on_about_to_quit)
        try:
            sys.excepthook = self._qt_exception_hook
        except Exception as e:
            self._log.debug(f"Kunde inte installera Qt exception hook: {e}")

        # Hämta Qt-klasser (snabbare access)
        self._Qt = self._imports["PySide6.QtCore"].instance["Qt"]
        self._QTimer = self._imports["PySide6.QtCore"].instance["QTimer"]
        self._Signal = self._imports["PySide6.QtCore"].instance["Signal"]
        self._Slot = self._imports["PySide6.QtCore"].instance["Slot"]
        self._QAction = self._imports["PySide6.QtGui"].instance["QAction"]
        self._QFont = self._imports["PySide6.QtGui"].instance["QFont"]
        self._QIcon = self._imports["PySide6.QtGui"].instance["QIcon"]
        self._QPainter = self._imports["PySide6.QtGui"].instance["QPainter"]
        self._QColor = self._imports["PySide6.QtGui"].instance["QColor"]
        self._QPixmap = self._imports["PySide6.QtGui"].instance["QPixmap"]
        self._QPen = self._imports["PySide6.QtGui"].instance["QPen"]
        self._QBrush = self._imports["PySide6.QtGui"].instance["QBrush"]
        self._QApplication = self._imports["PySide6.QtWidgets"].instance["QApplication"]
        self._QSystemTrayIcon = self._imports["PySide6.QtWidgets"].instance["QSystemTrayIcon"]
        self._QMenu = self._imports["PySide6.QtWidgets"].instance["QMenu"]
        self._QMessageBox = self._imports["PySide6.QtWidgets"].instance["QMessageBox"]
        self._QInputDialog = self._imports["PySide6.QtWidgets"].instance["QInputDialog"]
        self._QWidget = self._imports["PySide6.QtWidgets"].instance["QWidget"]

        # FIX v7-fix22: fortfarande INGEN ikon på appen — bara förbered.
        # (Sätts i _populate_windows efter att fönstret skapats.)
        with suppress(Exception):
            if self._app_icon_path is None:
                self._app_icon_path = self._ensure_app_icon_file()
            if self._app_icon_path is not None and self._QIcon is not None:
                self._app_icon = self._QIcon(str(self._app_icon_path))
                self._log.info(
                    f"{LOG_PREFIX} App-ikon förberedd (ej satt ännu, v7-fix22)"
                )

        # ============================================================
        # FIX v7-fix22: STARTPANEL I KONSOLEN — syns i PowerShell!
        # Avslöjar direkt: körs rätt desktop.py? Fungerade DPI-fixen?
        # ============================================================
        try:
            _dpi_txt = "?"
            if sys.platform == "win32":
                import ctypes as _ct
                _ctx = _ct.windll.user32.GetProcessDpiAwarenessContext(
                    _ct.windll.kernel32.GetCurrentProcess()
                )
                _v = int(_ctx) & 0xFFFFFFFFFFFFFFFF if _ctx else 0
                _dpi_map = {
                    0xFFFFFFFFFFFFFFFF: "UNAWARE",
                    0xFFFFFFFFFFFFFFFE: "SYSTEM (FEL! gammal desktop.py?)",
                    0xFFFFFFFFFFFFFFFD: "PER_MONITOR",
                    0xFFFFFFFFFFFFFFFC: "PER_MONITOR_V2 (RÄTT!)",
                }
                _dpi_txt = _dpi_map.get(_v, hex(_v))
            _ver_txt = "?"
            try:
                import PySide6 as _ps6
                _ver_txt = _ps6.__version__
            except Exception:
                pass
            _start_panel = (
                "=" * 58 + "\n"
                "Ledgebord v6.4.1 v7 — startpanel (v7-fix22)\n"
                f"  PySide6:        {_ver_txt}\n"
                f"  DPI-medvetenhet: {_dpi_txt}\n"
                "  Ikon: uppskjuten tills efter första fönstret\n"
                + "=" * 58
            )
            self._log.info(f"{LOG_PREFIX}\n{_start_panel}")
            sys.__stderr__.write(_start_panel + "\n")
            sys.__stderr__.flush()
        except Exception:
            pass

    def _cleanup_all_caches(self) -> int:
        """
        NY v7-fix25: Rensa ALL cache när appen avslutas.

        Rickard 2026-09-29: "tömma all cache efter att appen avslutas".

        Rensar:
          1. __pycache__-mappar i hela projektet
          2. .pyc-filer
          3. Qt:s pixmap-cache
          4. Python:s import-cache (sys.path_importer_cache)

        Returnerar antal borttagna objekt.
        """
        removed = 0
        try:
            import shutil as _shutil

            root = SCRIPT_DIR

            # 1. __pycache__-mappar
            for pycache in root.rglob("__pycache__"):
                if pycache.is_dir():
                    with suppress(Exception):
                        _shutil.rmtree(pycache, ignore_errors=True)
                        removed += 1

            # 2. .pyc-filer (från root, core/, ui/)
            for pyc in root.rglob("*.pyc"):
                with suppress(Exception):
                    pyc.unlink()
                    removed += 1

            # 3. Qt pixmap-cache
            with suppress(Exception):
                from PySide6.QtGui import QPixmapCache
                QPixmapCache.clear()

            # 4. Python import-cache
            with suppress(Exception):
                sys.path_importer_cache.clear()

            if removed:
                self._log.info(
                    f"{LOG_PREFIX} Cache-rensning: {removed} objekt "
                    f"borttagna (__pycache__ + .pyc)"
                )
            else:
                self._log.debug(
                    f"{LOG_PREFIX} Cache-rensning: inget att rensa"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} cache-rensning fel: {e}")
        return removed

    def _qt_exception_hook(self, exc_type, exc_value, exc_traceback) -> None:
        """Qt-specifik exception hook (visar QMessageBox + loggar UTFÖRLIGT)."""
        # Logga UTFÖRLIGT (med hela traceback)
        try:
            import traceback as _tb
            tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_traceback))
            self._log.critical(
                f"OHANTERAT FEL (Qt-hook) — "
                f"type={exc_type.__name__}, msg={exc_value}",
                extra={"traceback": tb_str[:5000]},  # Begränsa längd
            )
            self._log.critical(
                f"OHANTERAT FEL (Qt-hook) traceback:\n{tb_str}",
            )
        except Exception as e:
            self._log.critical(
                "OHANTERAT FEL (Qt-hook):",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        if self._app is not None:
            with suppress(Exception):
                self._QMessageBox.critical(
                    None,
                    f"{APP_NAME} — Kritisk krasch",
                    f"Ett oväntat fel uppstod:\n\n{exc_value}",
                )

    def _on_about_to_quit(self) -> None:
        """Callback när Qt håller på att stänga."""
        self._log.info("Qt aboutToQuit-signal mottagen")
        with suppress(Exception):
            self.shutdown()

    # -----------------------------------------------------------------------
    # INIT — Subsystems
    # -----------------------------------------------------------------------

    def _init_subsystems(self) -> None:
        """
        NY v6.4.1 v7: Initiera ALLA subsystems (med error boundary + AI-felsokning).

        Loggar varje steg med ✓ / ⚠ / ✗ for tydlig status.
        Vid fel: error_boundary fångar + visar svensk dialog.
        """
        self._log.info(f"{LOG_PREFIX} === Initierar subsystems (mode={self._mode.name}) ===")

        # 0. NY v8 (2026-10-12): saknas uppgifter/inställningar (t.ex. efter en
        # uppdatering som tagit js/-mappen) → läs in dem från den automatiska backupen
        # INNAN något annat läser filerna.
        with suppress(Exception):
            self._restore_from_external_backup()

        # 1. Settings (eller dummy)
        settings_status = self._imports.get("settings")
        if settings_status and settings_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("settings.init"):
                SettingsCls = settings_status.instance["Settings"]
                self.settings = SettingsCls()
                self._registry.register("settings", self.settings, dependencies=[])
                self._log.info(f"{LOG_PREFIX} ✓ Settings initierat")
                # NY v7-fix9: Rensa skräp-fönster EN gång vid start.
                # window_configs() är nu en pure getter (inga sidoeffekter) —
                # cleanup sker här istället, innan _init_signals kopplar
                # windows_updated → _safe_update_widgets (så emit:en inte
                # triggar populate innan widgets finns).
                if hasattr(self.settings, "cleanup_stale_windows"):
                    with suppress(Exception):
                        _removed = self.settings.cleanup_stale_windows()
                        if _removed:
                            self._log.info(
                                f"{LOG_PREFIX} ✓ Rensade {_removed} skräp-fönster "
                                f"ur settings"
                            )
        else:
            self.settings = self._create_dummy_settings()
            self._registry.register("settings", self.settings)
            self._log.warning(f"{LOG_PREFIX} ⚠ Settings: dummy-läge (använder tomt)")

        # 2. Store (eller dummy)
        store_status = self._imports.get("store")
        if store_status and store_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("store.init"):
                TaskStoreCls = store_status.instance["TaskStore"]
                self.store = TaskStoreCls()
                self._registry.register("store", self.store, dependencies=["utils"])
                self._log.info(f"{LOG_PREFIX} ✓ Store (TaskStore) initierat")
        else:
            self.store = self._create_dummy_store()
            self._registry.register("store", self.store)
            self._log.warning(f"{LOG_PREFIX} ⚠ Store: dummy-läge")

        # 3. Stability (om aktiverat)
        if self._config.enable_stability:
            stab_status = self._imports.get("stability")
            if stab_status and stab_status.ok:
                with error_boundary("stability.init"):
                    stability_mod = stab_status.instance.get("stability")
                    get_stability = getattr(stability_mod, "get_stability_manager", None)
                    if get_stability:
                        self.stability = get_stability()
                        self._registry.register("stability", self.stability)
                        self._log.info(f"{LOG_PREFIX} ✓ Stability-system initierat")

        # 4. Backup manager
        backup_status = self._imports.get("backup")
        if backup_status and backup_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("backup.init"):
                BackupMgrCls = backup_status.instance.get("BackupManager")
                if BackupMgrCls:
                    # NY v6.4.1 v7-fix: BackupManager.__init__ tar (keep, backup_dir, timeout_sec)
                    # INTE data_dir/tasks_file/settings_file (gamla felaktiga anropet).
                    # Vi skickar bara 'keep' och låter default _default_backup_dir() användas.
                    self.backup_manager = BackupMgrCls(keep=10)
                    self._registry.register("backup", self.backup_manager)
                    self._log.info(f"{LOG_PREFIX} ✓ Backup-manager initierat")

        # 5. Window creation + populate
        with error_boundary("windows.create"):
            # FIX 2026-09-25 v7-fix8: Skippa pretest-widgets helt.
            # Orsak: pretest-widgeten (`__pretest__`) skapade WS_OVERLAPPED-widgets
            # mitt i Qt:s flag-handshake, vilket gav:
            #   - "Failed to create platform window ... flags QFlags<Qt::WindowType>()"
            #     (tomma flaggor — Qt hann inte registrera Window-typ innan show())
            #   - PermissionError [WinError 32] pa TimedRotatingFileHandler.doRollover
            #     nar pretest skapade log-events under log-rotation
            # Pretest var ett forsok att "fanga tysta krascher" men skapar mer
            # brus an nytta — populate-widgets ger samma signal vid fel.
            self._log.info(
                f"{LOG_PREFIX} === Hoppar over widget pre-test (v7-fix8) ==="
            )

            self._create_default_window()
            self._populate_windows()

        # 5.5. NY v6.4.1 v7: Tvinga synlig vid force-show (DEFAULT PÅ)
        # FIX 2026-09-23: Kör på GUI-tråden via QTimer — INTE bakgrundstråd.
        # Qt-widget-metoder (show/raise/activate) från annan tråd → "Python svarar inte".
        if self._config.force_show_widget:
            try:
                if self._QTimer is None:
                    raise RuntimeError("self._QTimer saknas")
                # singleShot köar till GUI-tråden (widget-tråd) → ingen frysning
                self._QTimer.singleShot(600, self.force_show_all_widgets)
                self._log.info(
                    f"{LOG_PREFIX} force_show schemalagd på GUI-tråd (+600ms)"
                )
            except Exception as _fs_e:
                # Fallback: Win32-only via liten bakgrundstråd (inga Qt-anrop där)
                self._log.warning(
                    f"{LOG_PREFIX} QTimer.force-show misslyckades ({_fs_e}), "
                    f"fallback Win32-tråd"
                )

                def _force_show_bg() -> None:
                    import time as _time
                    _time.sleep(0.6)
                    try:
                        self.force_show_all_widgets()
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} force_show_bg misslyckades: {e}"
                        )
                fs_thread = threading.Thread(
                    target=_force_show_bg,
                    daemon=True,
                    name="ForceShow",
                )
                fs_thread.start()

        # 6. Tray (om aktiverat)
        if self._mode != AppMode.NO_TRAY:
            with error_boundary("tray.init"):
                self._init_tray()

        # 6b. NY v7-fix41: global snabbinput (Ctrl+Alt+N, hela Windows)
        with suppress(Exception):
            self._install_global_quick_add()

        # 6c. NY v7-fix50: installera/uppdatera tillägg automatiskt vid
        # start (Rickards val: full auto — bakgrund, 30 s fördröjning)
        with suppress(Exception):
            self._schedule_auto_plugin_update()

        # 6d. NY v7-fix64: påminnelsetjänst (förfallna + dagens uppgifter)
        with suppress(Exception):
            self._init_reminder_service()

        # 6e-2. NY v8: automatisk säkerhetskopia av uppgifter + inställningar
        with suppress(Exception):
            self._init_external_backup()

        # 6e-3a. NY: självläkande uppdatering — bekräfta uppstarten för väktaren
        with suppress(Exception):
            self._init_update_guard()

        # 6e-3. NY v8: tyst, automatisk koll efter ny version (2 gånger/dygn)
        with suppress(Exception):
            self._init_update_check()

        # 6e-4. NY: påminn när Thunderbird-tillägget (.xpi) ändrats
        with suppress(Exception):
            self._init_addon_notice()

        # 6e. NY v7-fix90: e-postbrygga (Thunderbird-tillägg) + inkorgsmapp
        # (tar emot mail från tillägget och skapar uppgifter som sparas i JSON)
        with suppress(Exception):
            self._init_mail_bridge(at_startup=True)

        # 7. NY v6.4.1 v7: Erbjud installera saknade plugins (icke-blockerande)
        # Körs BARA i NORMAL-läge (inte --safe-mode eller --no-tray)
        # NY v6.4.1 v7-fix: Skippa om --force-show (användaren vill bara se widgets)
        # NY v6.4.1 v7-fix: Skippa om --no-plugin-install
        if (self._mode == AppMode.NORMAL
                and not self._config.force_show_widget
                and not self._config.no_plugin_install):
            try:
                # Kör i bakgrunds-tråd så UI inte fryser under installation
                def _offer_plugins_bg() -> None:
                    try:
                        results = offer_install_missing_plugins()
                        if results:
                            ok_count = sum(1 for v in results.values() if v)
                            self._log.info(
                                f"{LOG_PREFIX} plugin-installation klar: "
                                f"{ok_count}/{len(results)} lyckades"
                            )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} plugin-erbjudande misslyckades: {e}",
                            exc_info=True,
                        )
                bg_thread = threading.Thread(
                    target=_offer_plugins_bg,
                    daemon=True,
                    name="PluginInstaller",
                )
                bg_thread.start()
                self._log.debug(
                    f"{LOG_PREFIX} plugin-erbjudande startat i bakgrunds-tråd"
                )
            except Exception as e:
                self._log.warning(
                    f"{LOG_PREFIX} kunde inte starta plugin-erbjudande: {e}"
                )

    def _init_timers(self) -> None:
        """Initiera ALLA periodiska timers."""
        if self._QTimer is None:
            self._log.warning("Kan inte initiera timers (QTimer saknas)")
            return

        timer_configs = [
            (self.CLEANUP_INTERVAL_MS, self._periodic_cleanup, "cleanup"),
            (self.METRICS_REFRESH_MS, self._refresh_metrics, "metrics"),
            (self.BACKUP_CHECK_INTERVAL_MS, self._check_backup_status, "backup"),
            (self.CAPABILITIES_REFRESH_MS, self._refresh_capabilities, "capabilities"),
            (self.HEARTBEAT_INTERVAL_MS, self._heartbeat, "heartbeat"),
            (self.IDLE_CHECK_INTERVAL_MS, self._check_idle, "idle"),
        ]

        for interval_ms, callback, name in timer_configs:
            with error_boundary(f"timer.{name}"):
                timer = self._QTimer(self._app)
                timer.timeout.connect(callback)
                timer.start(interval_ms)
                self._log.debug(f"Timer startad: {name} ({interval_ms}ms)")

    def _init_signals(self) -> None:
        """Koppla ALLA Qt-signaler."""
        with error_boundary("signals.connect"):
            if hasattr(self.settings, "windows_updated"):
                self.settings.windows_updated.connect(self._safe_update_widgets)
            if hasattr(self.settings, "theme_changed"):
                self.settings.theme_changed.connect(self._on_theme_changed)
            if hasattr(self.settings, "accent_changed"):
                self.settings.accent_changed.connect(self._on_theme_changed)
            # FIX v7-fix11: signalen heter 'changed' — INTE 'tasks_changed'!
            # Gammal bugg: hasattr(self.store, "tasks_changed") var alltid
            # False → kopplingen hoppades tyst över → UI:et uppdaterades
            # ALDRIG när uppgifter ändrades (och inget sparades till disk).
            if hasattr(self.store, "changed"):
                self.store.changed.connect(self._on_tasks_changed)
                self.store.changed.connect(self._on_store_data_changed)
                self._log.info(
                    f"{LOG_PREFIX} store.changed kopplad → live-refresh + autosave"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} store saknar 'changed'-signal — "
                    f"live-refresh/autosave avstängt"
                )
            self._log.debug("Signaler kopplade")

    def _get_qt_class(self, class_name: str) -> Optional[type]:
        """Hämta en Qt-klass från imports (QtCore/QtGui/QtWidgets)."""
        for mod_name in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
            status = self._imports.get(mod_name)
            if status and status.ok and class_name in status.instance:
                return status.instance[class_name]
        return None

    # -----------------------------------------------------------------------
    # DUMMY SUBSYSTEMS (safe-mode)
    # -----------------------------------------------------------------------

    def _create_dummy_settings(self) -> Any:
        """Skapa dummy-Settings för safe-mode."""

        class _DummySettings:
            def window_configs(self) -> List[Dict[str, Any]]:
                return []

            def add_window(self, x: int, y: int) -> None:
                pass

            def remove_window(self, wid: str) -> None:
                pass

            def __getattr__(self, name: str) -> Any:
                return lambda *a, **kw: None

        return _DummySettings()

    def _create_dummy_store(self) -> Any:
        """Skapa dummy-Store för safe-mode."""

        class _DummyStore:
            def count(self) -> Tuple[int, int]:
                return (0, 0)

            def active_tasks(self) -> List[Dict[str, Any]]:
                return []

            def archive_tasks(self) -> List[Dict[str, Any]]:
                return []

            def reload(self) -> None:
                pass

            def add_task(self, text: str) -> None:
                pass

            def __getattr__(self, name: str) -> Any:
                return lambda *a, **kw: None

        return _DummyStore()

    # -----------------------------------------------------------------------
    # WINDOWS — create / populate / BUGG 19/26
    # -----------------------------------------------------------------------

    def _create_default_window(self) -> None:
        """Skapa default-fönster om inget finns sparat."""
        try:
            if not hasattr(self.settings, "window_configs") or not self.settings.window_configs():
                if hasattr(self.settings, "add_window"):
                    self.settings.add_window(100, 100)
                    self._log.debug("Default-fönster skapat (100, 100)")
        except Exception as e:
            self._log.error(f"Kunde inte skapa default-fönster: {e}")

    def _show_simple_error(self, title: str, message: str) -> None:
        """
        NY v6.4.1 v7: Visa kort QMessageBox-fel (med forbattrad loggning).

        Args:
            title: Kort titel (utan app-namn)
            message: Medellangt meddelande (svenska forklaringar)
        """
        if self._app is None or self._QMessageBox is None:
            self._log.error(
                f"{LOG_PREFIX} _show_simple_error: {title}: {message}"
            )
            return
        try:
            self._QMessageBox.warning(None, f"{APP_NAME} — {title}", message)
            self._log.debug(
                f"{LOG_PREFIX} _show_simple_error visad: {title!r}"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _show_simple_error misslyckades: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # DIALOGS — ask_new_task, ask_rename, ask_confirm_delete
    # -----------------------------------------------------------------------

    def ask_new_task(self) -> None:
        """Öppna dialog för ny uppgift (QInputDialog)."""
        if not self._app or self._QInputDialog is None:
            return
        try:
            text, ok = self._QInputDialog.getText(
                None,
                "Ny uppgift",
                "Vad behöver göras?",
            )
            if ok and text and text.strip():
                if hasattr(self.store, "add_task"):
                    self.store.add_task(text.strip())
                    self._log.info(f"Ny uppgift tillagd: {text.strip()!r}")
                    self.bring_all_to_front()
                else:
                    self._log.warning("Store har ingen add_task-metod")
        except Exception as e:
            self._log.error(f"ask_new_task misslyckades: {e}")

    def ask_rename_task(self, task_id: str, current_text: str) -> None:
        """Öppna dialog för att byta namn på en uppgift."""
        if not self._app or self._QInputDialog is None:
            return
        try:
            text, ok = self._QInputDialog.getText(
                None,
                "Byt namn på uppgift",
                "Ny text:",
                text=current_text,
            )
            if ok and text and text.strip() and text != current_text:
                if hasattr(self.store, "rename_task"):
                    self.store.rename_task(task_id, text.strip())
                    self._log.info(f"Task {task_id!r} döpt om till: {text.strip()!r}")
        except Exception as e:
            self._log.error(f"ask_rename_task misslyckades: {e}")

    def ask_confirm_delete(self, task_id: str, task_text: str) -> bool:
        """Fråga användaren om bekräftelse innan radering."""
        if not self._app or self._QMessageBox is None:
            return False
        try:
            reply = self._QMessageBox.question(
                None,
                "Ta bort uppgift?",
                f"Vill du verkligen ta bort:\n\n\"{task_text}\"\n\n"
                f"Detta går inte att ångra.",
                self._QMessageBox.StandardButton.Yes
                | self._QMessageBox.StandardButton.No,
                self._QMessageBox.StandardButton.No,
            )
            return reply == self._QMessageBox.StandardButton.Yes
        except Exception as e:
            self._log.error(f"ask_confirm_delete misslyckades: {e}")
            return False

    # -----------------------------------------------------------------------
    # SHUTDOWN
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        NY v6.4.1 v7: Stäng app rent (graceful, idempotent, trådsäker).

        Steg (alla med 10000% loggning):
          1. Stang alla widget-fönster
          2. Dolj + frigör tray-ikon
          3. Stäng subsystems (LIFO)
          4. Stoppa async workers
          5. Logga sammanfattning
        """
        if self._shutdown_initiated:
            self._log.debug(
                f"{LOG_PREFIX} shutdown: redan initierad (idempotent)"
            )
            return
        self._shutdown_initiated = True
        # NY: ren avslutning efter en uppdatering räknas som "kom igång" (annars skulle
        # väktaren återställa en fungerande uppdatering om du stänger appen inom 10 s)
        with suppress(Exception):
            self._confirm_update_health(on_exit=True)
        # Använd svensk uptime-text i loggen
        uptime_sec = time.time() - getattr(self, "_start_time", time.time())
        uptime_sv = format_uptime(uptime_sec)
        # NY v7-fix41: avregistrera global hotkey FÖRST
        self._uninstall_global_quick_add()
        self._log.info(
            f"{LOG_PREFIX} Stänger ner {APP_NAME} efter {uptime_sv}..."
        )
        # FIX v7-fix11: slutgiltig save av store — tidigare sparades ALDRIG
        # vid nedstängning (dataförlust). Autosave-timern hinner kanske inte
        # köra klart innan processen dör, därför sparas här synkront.
        try:
            if self.store is not None and getattr(self.store, "is_dirty", False):
                ok = self.store.save()
                self._log.info(
                    f"{LOG_PREFIX} Slutgiltig save vid nedstängning: "
                    f"{'OK' if ok else 'MISSLYCKADES'}"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} Slutgiltig save misslyckades: {e}", exc_info=True
            )
        # NY v7-fix90: stoppa e-postbryggan (släpper porten + skriver status)
        with suppress(Exception):
            self._stop_mail_bridge()
        # NY v8 (2026-10-12): spara fönstrets position + storlek INNAN något stängs
        # och skriv settings till disk (nedstängningen sparade tidigare inte settings
        # alls → fönsterläget glömdes vid omstart).
        with suppress(Exception):
            with self._widget_lock:
                _geo_widgets = list(self._widgets.values())
            for _w in _geo_widgets:
                with suppress(Exception):
                    if hasattr(_w, "_save_geometry_now"):
                        _w._save_geometry_now()
            if self.settings is not None and hasattr(self.settings, "save"):
                _ok_s = self.settings.save()
                self._log.info(
                    f"{LOG_PREFIX} Settings sparade vid nedstängning: "
                    f"{'OK' if _ok_s else 'MISSLYCKADES'}"
                )
        # NY v8: automatisk säkerhetskopia av uppgifter + inställningar
        with suppress(Exception):
            self._external_backup("nedstängning")
        try:
            # 1. Stäng alla widgets
            with self._widget_lock:
                widget_ids = list(self._widgets.keys())
            for wid in widget_ids:
                with suppress(Exception):
                    w = self._widgets.pop(wid, None)
                    if w and hasattr(w, "_unregister_hotkeys"):
                        w._unregister_hotkeys()
                    if w and hasattr(w, "close"):
                        # FIX 2026-09-24: tillåt close vid shutdown
                        w._allow_close = True
                        w.close()
                        with suppress(Exception):
                            w.deleteLater()
            # FIX: stäng också ev. pretest/spök-widgeter som inte är i _widgets
            with suppress(Exception):
                for child in list(self._app.topLevelWidgets()):
                    if not hasattr(child, "win_id"):
                        continue
                    if str(getattr(child, "win_id", "")).startswith("__"):
                        child._allow_close = True
                        child.close()
                        with suppress(Exception):
                            child.deleteLater()
            self._log.info(
                f"{LOG_PREFIX} Stängt {len(widget_ids)} widget-fönster"
            )

            # 2. Dölj + frigör tray
            if self._tray is not None:
                with suppress(Exception):
                    self._tray.hide()
                    self._tray.deleteLater()
                self._tray = None
                self._log.debug(f"{LOG_PREFIX} Tray dold och frigjord")

            # 3. Stäng subsystems (LIFO)
            self._registry.shutdown_all()
            self._log.debug(f"{LOG_PREFIX} Subsystems avslutade")

            # 4. Stoppa async runner
            if self._async_runner:
                self._async_runner.stop(timeout=Timeouts.WORKER_CLEANUP)
                self._log.debug(f"{LOG_PREFIX} Async runner stoppad")

            # NY v7-fix25: Full cache-rensning
            with suppress(Exception):
                self._cleanup_all_caches()

            # NY v7-fix28: Logg-rensning — 3 dagars retention
            with suppress(Exception):
                from utils import cleanup_old_logs
                _lr = cleanup_old_logs(
                    data_path=str(SCRIPT_DIR / "data"), max_age_days=3
                )
                if _lr.get("removed"):
                    self._log.info(
                        f"{LOG_PREFIX} Logg-rensning: "
                        f"{_lr['removed']} gamla loggar raderade"
                    )

            # 5. Flush logging
            for handler in logging.getLogger().handlers:
                with suppress(Exception):
                    handler.flush()

            # NY v7-fix87: stäng instans-kanalen (så att nästa start kan
            # lyssna direkt)
            _m = getattr(self, "_instance_messenger", None)
            if _m is not None:
                with suppress(Exception):
                    _m.close()
                self._instance_messenger = None
            self._log.info("Avslutning klar")
        except Exception as e:
            self._log.error(f"Shutdown-fel: {e}", exc_info=True)
        finally:
            hide_splash()
            if self._app is not None:
                with suppress(Exception):
                    self._app.quit()

    def run(self) -> int:
        """Kör Qt event loop (blocking)."""
        if self._app is None:
            self._log.error("Kan inte starta event loop (QApplication saknas)")
            return 1
        # NY v6.4.1: Kör diagnostik vid start (efter Qt-init)
        try:
            self._run_diagnostics_on_startup()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} diagnostik vid start misslyckades: {e}"
            )
        return self._app.exec()
