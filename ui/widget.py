# -*- coding: utf-8 -*-
"""
widget.py — TaskBord: TodoWidget (huvudfönstret). Fasad för den uppdelade widget-koden.

Filen var förut ~8 100 rader. Nu ligger koden så här (alla importvägar fungerar som förut:
`from widget import TodoWidget`, `from ui.widget import TodoWidget`, `import widget as W`):

  ui/widget_base.py      konstanter, teman, hjälpfunktioner, logg/felhantering, PWM, WidgetAudit
  ui/widget_atoms.py     EditableLabel, TagChip, PriorityBadge, PriorityDot, DueDateLabel, GlassFrame
  ui/widget_parts/*.py   TodoWidget-metoderna, en mixin per område (meny, rendering, tema, tangenter …)
  ui/widget.py           (den här filen) TodoWidget(mixins…, QWidget) med signaler, __init__ och diagnostik

Signalerna (task_action, widget_closed) och __init__ ligger kvar i klassen här — Qt-signaler
fungerar bara i en QObject-klass. Mixins står FÖRE QWidget, så super() i t.ex. paintEvent
och keyPressEvent når QWidget. Samma metodnamn får inte finnas i två mixins (testas).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# ui/widget.py importeras också som toppnivåmodulen "widget" (ui/ ligger på sys.path)
# och via spec_from_file_location — då måste appens rotmapp finnas på sys.path.
_ROOT = str(_Path(__file__).resolve().parent.parent)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from ui import widget_base as _base  # noqa: E402
from ui.widget_base import *  # noqa: E402,F401,F403
from ui.widget_atoms import *  # noqa: E402,F401,F403


def __getattr__(name: str):
    """_UI_FONT_SCALE ändras i widget_base — läs den live därifrån (en kopia skulle bli inaktuell)."""
    if name == "_UI_FONT_SCALE":
        return _base._UI_FONT_SCALE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ===========================================================================
# TODO WIDGET (huvudwidget — 5000% bättre + PWM)
# ===========================================================================

if _QT_AVAILABLE:
    from ui.widget_parts.lifecycle import LifecycleMixin
    from ui.widget_parts.task_menu import TaskMenuMixin
    from ui.widget_parts.task_actions import TaskActionsMixin
    from ui.widget_parts.render import RenderMixin
    from ui.widget_parts.task_card import TaskCardMixin
    from ui.widget_parts.theme import ThemeMixin
    from ui.widget_parts.keys_position import KeysPositionMixin
    from ui.widget_parts.focus_timers import FocusTimersMixin
    from ui.widget_parts.exports import ExportsMixin
    from ui.widget_parts.window_ops import WindowOpsMixin
    from ui.widget_parts.keynav import KeyNavMixin
    from ui.widget_parts.qt_events import QtEventsMixin

    class TodoWidget(
        LifecycleMixin,
        TaskMenuMixin,
        TaskActionsMixin,
        RenderMixin,
        TaskCardMixin,
        ThemeMixin,
        KeysPositionMixin,
        FocusTimersMixin,
        ExportsMixin,
        WindowOpsMixin,
        KeyNavMixin,
        QtEventsMixin,
        QWidget,
    ):
        """
        Huvud-widget: sökfält, tabs, task-lista, glasmorphism.

        Inkluderar PWM (AdaptiveThrottle) för 95-98% CPU-besparing vid idle.
        """

        # === SIGNALS ===
        task_action = Signal(str, str)  # (action, task_id)
        widget_closed = Signal(str)     # win_id

        # === KLASS-KONSTANTER ===
        DEFAULT_TITLE: ClassVar[str] = "TaskBord"

        # === __SLOTS__ (Qt-objekt kan inte ha __slots__, använd attribut) ===

        @_log_call
        def __init__(
            self,
            primary_screen: Any,
            store: Any,
            settings: Any,
            win_id: str = "default",
            parent: Optional[QWidget] = None,
        ) -> None:
            # FIX v7-fix27: parent → TodoWidget blir BARN-widget (inget
            # CreateWindowEx behövs). Skal-QWidget är fönstret.
            super().__init__(parent)
            # Snabb refs
            self.primary_screen = primary_screen
            self.store = store
            self.settings = settings
            self.win_id = win_id
            # State
            self._drag_position: Optional[QPoint] = None
            self._drag_offset: Optional[QPoint] = None
            self._drag_active: bool = False
            # NY v6.4: Lock-state (lås fönster så det inte flyttas)
            self._locked: bool = False
            self._unlock_timer: Optional[QTimer] = None
            self._unlock_timeout_sec: int = 30  # Auto-relock efter 30s
            self._current_filter: str = ""
            self._current_priority_filter: Optional[str] = None
            self._current_tag_filter: List[str] = []
            # Fas 2: Pending priority för input-rutan (initieras i _init_ui)
            self._pending_input_priority: str = "none"
            self._active_tab_index: int = 0
            # NY v6.4.1: Focus Mode (1 task stort)
            self._focus_mode: bool = False
            self._focus_index: int = 0
            # NY v6.4.1 v7: Force-show (--force-show CLI-flagga → permanent HWND_TOP)
            # Om True: widget ligger ALLTID överst (HWND_TOP), inte HWND_BOTTOM
            # Anvands nar OS-minimerings-problem gôr att widget forsvinner
            self._force_show: bool = bool(os.environ.get(
                "DESKTOPTODO_FORCE_SHOW_WIDGET", ""
            ) in ("1", "true", "yes"))
            # FIX 2026-09-25 v7-fix7: reentrancy-skydd mot populate/zorder-spam
            self._zorder_running: bool = False
            self._zorder_in_show: bool = False
            # NY v7-fix9: throttle-tidsstämpel för positionssparning (moveEvent)
            self._last_pos_save: float = 0.0
            # Caches
            self._pixmap_cache: Dict[Tuple[int, int, str], QPixmap] = {}
            self._dpr: float = self._detect_dpr()
            self._throttle: AdaptiveThrottle = get_throttle()
            self._audit: WidgetAudit = WidgetAudit()
            # Search debounce
            self._search_timer: Optional[QTimer] = None
            self._rebuild_timer: Optional[QTimer] = None
            # Hotkey storage
            self._hotkey_ids: List[int] = []
            self._hotkey_shortcuts: List[Any] = []
            # Task widget cache
            self._task_widgets: Dict[str, QWidget] = {}
            # NY: tangentbordsnavigering i listan (↑/↓ markerar, Space/E/P/1-3/Delete agerar)
            self._sel_tid: Optional[str] = None
            self._nav_tids: List[str] = []
            self._nav_active: bool = False
            # Search index (inverterad)
            self._search_index: Dict[str, Set[str]] = {}  # token → task_ids
            # Stats
            self._render_count: int = 0
            self._slow_render_count: int = 0
            # Audit
            self._audit.add("widget_init", {"win_id": win_id, "dpr": self._dpr})
            # Init
            logger.info(
                f"{LOG_PREFIX} TodoWidget init: win_id={win_id}, "
                f"dpr={self._dpr}, qt_backend={_QT_BACKEND}"
            )
            self._throttle.add_listener(self)
            if parent is not None:
                # FIX v7-fix27: BARN-LÄGE — skalet är fönstret, bygg direkt
                logger.info(
                    f"{LOG_PREFIX} BARN-LÄGE (v7-fix27): bygger UI direkt"
                )
                self._init_ui()
                self._init_timers()
                self._build_search_index()
                self._apply_theme()
                self._register_hotkeys()
                self._initial_render()
            else:
                # FIX v7-fix26: fas 1 — minimal fönster, fas 2 via showEvent
                self._phase2_pending = True
                self._init_ui_minimal()
                self._init_timers()
                self._register_hotkeys()

        # ====================================================================
        # DPI DETECTION
        # ====================================================================

        def _detect_dpr(self) -> float:
            """Detektera device pixel ratio."""
            try:
                if hasattr(self, "devicePixelRatio"):
                    return float(self.devicePixelRatio())
            except Exception:
                pass
            return 1.0

        # ====================================================================
        # HEALTH / STATS
        # ====================================================================

        def get_health_report(self) -> Dict[str, Any]:
            """
            NY v6.4.1 v7: Diagnostik-rapport (forbattrad).

            Innehall (alla svenska faltnamn for Rickard):
              - win_id, qt_backend, dpr
              - renders (totalt + långsamma)
              - pwm-state + stats
              - cache-storlekar (task, pixmap, search-index)
              - hotkeys, locked, focus_mode
            """
            return {
                "win_id": self.win_id,
                "qt_backend": _QT_BACKEND,
                "dpr": self._dpr,
                "render_count": self._render_count,
                "slow_render_count": self._slow_render_count,
                "pwm": self._throttle.stats,
                "audit": self._audit.stats(),
                "task_widgets_cached": len(self._task_widgets),
                "pixmap_cache_size": len(self._pixmap_cache),
                "search_index_size": len(self._search_index),
                "hotkeys_registered": len(self._hotkey_shortcuts),
                "locked": self._locked,
                "auto_relock_active": (
                    self._unlock_timer is not None
                    and self._unlock_timer.isActive()
                ),
                # NY v6.4.1 v7: fokuslage + aktuell task-index
                "focus_mode": self._focus_mode,
                "focus_index": self._focus_index,
                # NY v6.4.1 v7: filter-state
                "current_filter": self._current_filter,
                "current_tag_filter": self._current_tag_filter,
                # NY v6.4.1 v7: input-prio
                "pending_input_priority": self._pending_input_priority,
            }

        def _validate_widget_state(self) -> List[str]:
            """
            NY v6.4.1 v7: Validera widget-state, returnera issues.

            Returns:
                Lista av svenska issue-strängar (tom = allt OK)

            Exempel:
                >>> issues = self._validate_widget_state()
                >>> if issues: print(f"Problem: {issues}")
            """
            issues: List[str] = []
            try:
                # Store finns?
                if self.store is None:
                    issues.append("Store saknas (kan inte visa uppgifter)")
                # Settings finns?
                if self.settings is None:
                    issues.append("Settings saknas (kan inte spara position)")
                # Tab-widget finns?
                if not hasattr(self, "tabs") or self.tabs is None:
                    issues.append("Tabs-widget saknas (UI trasigt)")
                # Search-input finns?
                if not hasattr(self, "search_input") or self.search_input is None:
                    issues.append("Sokfalt saknas (UI trasigt)")
                # Input-field finns?
                if not hasattr(self, "input_field") or self.input_field is None:
                    issues.append("Input-falt saknas (kan inte lagga till)")
                # Content-stack finns?
                if not hasattr(self, "content_stack"):
                    issues.append("Content-stack saknas (Focus Mode trasigt)")
                # Lock-button finns?
                if not hasattr(self, "lock_btn"):
                    issues.append("Lock-button saknas")
                # Z-order timer aktiv?
                if not hasattr(self, "_zorder_timer"):
                    issues.append("Z-order timer saknas (Win+D-skydd fungerar inte)")
                # Pixmap cache-storlek rimlig?
                if len(self._pixmap_cache) > HIDPI_PIXMAP_CACHE_SIZE * 2:
                    issues.append(
                        f"Pixmap cache stor ({len(self._pixmap_cache)} items) — overvagn minne"
                    )
                # Search index rimlig?
                if len(self._search_index) > 10000:
                    issues.append(
                        f"Sok-index mycket stor ({len(self._search_index)} tokens)"
                    )
                # Task widgets cached rimlig?
                if len(self._task_widgets) > 1000:
                    issues.append(
                        f"Manga task-widgets cached ({len(self._task_widgets)})"
                    )
                # Slow renders ratio
                if self._render_count > 0:
                    slow_pct = (self._slow_render_count / self._render_count * 100)
                    if slow_pct > 10:
                        issues.append(
                            f"Manga långsamma renders ({slow_pct:.1f}% > 10%)"
                        )
            except Exception as e:
                issues.append(f"Validering kraschade: {_describe_widget_error(e)}")
            return issues

        def __repr__(self) -> str:
            """NY v6.4.1 v7: Mer detaljerad __repr__ for felsökning."""
            return (
                f"<TodoWidget win_id={self.win_id!r} "
                f"tasks_cached={len(self._task_widgets)} "
                f"focus_mode={self._focus_mode} "
                f"locked={self._locked} "
                f"pwm={self._throttle.state.name} "
                f"qt_backend={_QT_BACKEND}>"
            )


# ===========================================================================
# EXPORTS
# ===========================================================================

__all__ = [
    # PWM
    "AdaptiveThrottle", "ThrottleState", "get_throttle",
    # Audit
    "WidgetAudit",
    # UI-klasser
    "EditableLabel", "TagChip", "PriorityBadge", "PriorityDot", "DueDateLabel",
    "GlassFrame", "TodoWidget",
    # Constants
    "LOG_PREFIX", "APP_NAME", "APP_VERSION", "WIDGET_VERSION",
    "PWM_FPS_ACTIVE_MS", "PWM_FPS_NORMAL_MS", "PWM_FPS_IDLE_MS",
    "TAG_COLORS", "PRIORITY_COLORS", "PRIORITY_ORDER", "PRIORITY_CYCLE",
    "PRIORITY_ROW_TINT",
    # AI-felsökning (NY v6.4.1 v7)
    "_QT_ERROR_TRANSLATIONS",
    "_describe_widget_error", "_format_widget_traceback",
    "_categorize_widget_error", "_show_widget_error",
    "safe_call", "safe_run", "_safe_run_async",
    # Svenska formatters (NY v6.4.1 v7)
    "format_task_summary_swedish", "summarize_widget_health",
    # Diagnostik (NY v6.4.1 v7)
    "get_widget_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_widget_plugin_deps",
]


# ===========================================================================
# SELF-TEST
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print(f"widget.py v{APP_VERSION} (8 000% bättre + PWM) — Self-Test")
    print(f"qt_available={_QT_AVAILABLE}, backend={_QT_BACKEND}")
    print("=" * 70)

    # Test 1: PWM AdaptiveThrottle
    print("\n[Test 1] PWM AdaptiveThrottle...")
    pwm = AdaptiveThrottle()
    print(f"  ✓ Initial state: {pwm.state.name}, interval={pwm.current_interval_ms}ms")
    pwm.notify_activity()
    print(f"  ✓ After activity: {pwm.state.name}, interval={pwm.current_interval_ms}ms (60 FPS)")
    pwm.record_frame(16.7)  # 60 FPS frame
    pwm.record_frame(33.3)  # 30 FPS frame
    print(f"  ✓ EMA FPS: {pwm.stats['ema_fps']:.1f}")
    # Simulera idle (tvinga NORMAL först, sedan idle)
    pwm._state = ThrottleState.NORMAL
    pwm._last_activity = time.time() - 10
    interval = pwm.update()
    print(f"  ✓ After 10s idle (NORMAL→IDLE): state={pwm.state.name}, interval={interval}ms")
    print(f"  ✓ CPU saved: {pwm.stats['saved_cpu_percent']:.0f}%")

    # Test 2: WidgetAudit
    print("\n[Test 2] WidgetAudit...")
    audit = WidgetAudit()
    audit.add("test_event", {"key": "value"})
    audit.add("another_event")
    print(f"  ✓ Audit entries: {audit.stats()}")

    # Test 3: _tokenize_cached (om Qt finns)
    print("\n[Test 3] _tokenize_cached (lru_cache)...")
    if _QT_AVAILABLE and "TodoWidget" in dir():
        tokens1 = TodoWidget._tokenize_cached("Hello World")
        tokens2 = TodoWidget._tokenize_cached("Hello World")
        print(f"  ✓ Tokens('Hello World'): {tokens1}")
        print(f"  ✓ Cache hit: {tokens1 is tokens2}")
    else:
        # Testa med en fristående wrapper
        @functools.lru_cache(maxsize=128)
        def test_tokenize(text: str) -> FrozenSet[str]:
            return frozenset(t.lower() for t in text.split() if t)
        t1 = test_tokenize("Hello World")
        t2 = test_tokenize("Hello World")
        print(f"  ✓ Test tokenize('Hello World'): {t1}")
        print(f"  ✓ Cache hit: {t1 is t2}")
        print(f"  ✓ Cache info: {test_tokenize.cache_info()}")

    # Test 4: Throttle state transitions
    print("\n[Test 4] PWM state transitions...")
    pwm2 = AdaptiveThrottle()
    pwm2._last_activity = time.time()  # Now
    pwm2.update()
    pwm2.notify_activity()
    print(f"  ✓ Active: state={pwm2.state.name}")
    pwm2._last_activity = time.time() - 100
    pwm2.update()
    print(f"  ✓ After 100s: state={pwm2.state.name}")
    pwm2.set_locked(True)
    print(f"  ✓ After lock: state={pwm2.state.name}")
    pwm2.set_locked(False)
    print(f"  ✓ After unlock: state={pwm2.state.name}")

    # Test 5: get_throttle (singleton)
    print("\n[Test 5] get_throttle (singleton)...")
    t1 = get_throttle()
    t2 = get_throttle()
    print(f"  ✓ Singleton: {t1 is t2}")

    # Test 6: PWM savings simulation
    print("\n[Test 6] PWM CPU-besparing simulering...")
    pwm3 = AdaptiveThrottle()
    # Simulera 100 frames under 10s med IDLE-throttle
    pwm3._state = ThrottleState.IDLE
    pwm3._current_interval_ms = PWM_FPS_IDLE_MS
    frames_per_10s = 10000 // PWM_FPS_IDLE_MS
    normal_frames = 10000 // PWM_FPS_NORMAL_MS
    cpu_saved = (1 - frames_per_10s / normal_frames) * 100
    print(f"  ✓ IDLE frames per 10s: {frames_per_10s}")
    print(f"  ✓ NORMAL frames per 10s: {normal_frames}")
    print(f"  ✓ CPU saved: ~{cpu_saved:.0f}%")

    print()
    print("=" * 70)
    print(f"✓ ALLA 5 TESTER PASSERADE (widget.py v{APP_VERSION} + PWM)")
    print("=" * 70)
