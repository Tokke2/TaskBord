# -*- coding: utf-8 -*-
"""
edge_dock.py — dockning vid skärmkant: dra fönstret mot en kant så glider det ut (bara en smal list
syns kvar), och det glider in igen när musen nuddar kanten. Geometrin ligger i core/edge_dock.py.

* Dockas när du SLÄPPER fönstret nära en yttre kant (vänster, höger, överkant). Kanter som gränsar mot
  en annan skärm används aldrig, och inte heller underkanten (aktivitetsfältet).
* Gömmer sig när musen varit utanför en stund — inte medan en dialog/meny är öppen, du drar i fönstret,
  redigerar en titel eller har text i inmatningsfältet.
* Det SYNLIGA läget är det som sparas (settings.set_geometry_filter), så fönstret kommer tillbaka på
  rätt plats efter omstart/uppdatering och dockningen följer med.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional, Tuple

from core import edge_dock as geo

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[EDGEDOCK]"

try:
    from PySide6.QtCore import QEasingCurve, QObject, QTimer, QVariantAnimation, Qt
    from PySide6.QtGui import QCursor, QGuiApplication
    from PySide6.QtWidgets import QApplication
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QObject = object  # type: ignore[misc,assignment]

Rect = geo.Rect
HIDE_DELAY_S = 0.7
POLL_MS = 70
REVEAL_TICKS = 2          # musen måste ligga kvar ~140 ms vid kanten (inte bara svischa förbi)
START_GRACE_S = 2.5       # efter start/omstart: ge dig tid innan det gömmer sig


def _qt_screens() -> List[Tuple[Rect, Rect]]:
    out = []
    for s in QGuiApplication.screens():
        a, g = s.availableGeometry(), s.geometry()
        out.append(((a.x(), a.y(), a.width(), a.height()), (g.x(), g.y(), g.width(), g.height())))
    return out


def _qt_cursor() -> Tuple[int, int]:
    p = QCursor.pos()
    return (p.x(), p.y())


def _qt_buttons() -> bool:
    return QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton


if _QT:

    class EdgeDocker(QObject):
        def __init__(
            self, widget: Any, settings: Any, win_id: str = "default",
            screens_fn: Optional[Callable[[], List[Tuple[Rect, Rect]]]] = None,
            cursor_fn: Optional[Callable[[], Tuple[int, int]]] = None,
            buttons_fn: Optional[Callable[[], bool]] = None,
            anim_ms: int = 170,
        ) -> None:
            super().__init__(widget)
            self.w = widget
            self.settings = settings
            self.win_id = win_id
            self._screens_fn = screens_fn or _qt_screens
            self._cursor_fn = cursor_fn or _qt_cursor
            self._buttons_fn = buttons_fn or _qt_buttons
            self.anim_ms = anim_ms
            self.state = "idle"            # idle | shown | hidden | animating
            self._after_anim = "idle"
            self.edge: Optional[str] = None
            self.avail: Optional[Rect] = None
            self.shown: Optional[Rect] = None    # skärmkoordinater, flush mot kanten
            self._outside_since: Optional[float] = None
            self._hits = 0
            self._pinned = False
            self._anim: Optional[Any] = None
            self._timer = QTimer(self)
            self._timer.setInterval(POLL_MS)
            self._timer.timeout.connect(self._tick)
            with_f = getattr(settings, "set_geometry_filter", None)
            if callable(with_f):
                with_f(win_id, self._filter)

        # ------------------------------------------------------------ hjälp
        def _shell(self) -> Any:
            return getattr(self.w, "_shell", None) or self.w

        def _origin(self) -> Tuple[int, int]:
            o = getattr(self._shell(), "_parent_origin", None) or (0, 0)
            return (int(o[0]), int(o[1]))

        def _rect(self) -> Rect:
            sh, (ox, oy) = self._shell(), self._origin()
            return (sh.x() + ox, sh.y() + oy, sh.width(), sh.height())

        def _move(self, x: int, y: int) -> None:
            fn = getattr(self.w, "_shell_screen_move", None)
            if callable(fn) and self._shell() is not self.w:
                fn(int(x), int(y))
            else:
                ox, oy = self._origin()
                self._shell().move(int(x) - ox, int(y) - oy)

        def _enabled(self) -> bool:
            fn = getattr(self.settings, "edge_dock_enabled", None)
            return bool(fn()) if callable(fn) else True

        def is_docked(self) -> bool:
            return self.state != "idle"

        def is_hidden(self) -> bool:
            return self.state == "hidden"

        def _filter(self, x: int, y: int, w: Any, h: Any) -> Optional[tuple]:
            """Settings-filter: medan fönstret är gömt/glider sparas det SYNLIGA läget."""
            if self.state in ("hidden", "animating") and self.shown is not None:
                ox, oy = self._origin()
                return (self.shown[0] - ox, self.shown[1] - oy,
                        self.shown[2] if w is None else w, self.shown[3] if h is None else h)
            return None

        def _persist(self) -> None:
            """Spara det synliga läget (går via filtret om fönstret råkar vara gömt)."""
            r = self._rect()
            ox, oy = self._origin()
            with_g = getattr(self.settings, "update_window_geometry", None)
            if callable(with_g):
                with_g(self.win_id, r[0] - ox, r[1] - oy, r[2], r[3])

        # ------------------------------------------------------- dockning
        def on_drag_release(self) -> bool:
            """Anropas när användaren släppt fönstret efter drag. True om det dockades."""
            if not self._enabled():
                self.undock()
                return False
            rect = self._rect()
            screens = self._screens_fn()
            scr = geo.screen_for(rect, [a for a, _ in screens])
            if scr is None:
                return False
            full = next(f for a, f in screens if a == scr)
            allowed = geo.outer_edges(full, [f for _, f in screens])
            edge = geo.detect_edge(rect, scr, allowed)
            if edge is None:
                self.undock()
                return False
            self.dock_to(edge, scr)
            return True

        def dock_to(self, edge: str, avail: Rect, grace: float = 0.0) -> None:
            self._stop_anim()
            rect = self._rect()
            self.edge, self.avail = edge, avail
            self.shown = geo.shown_rect(rect, avail, edge)
            self.state = "shown"
            if self.shown[:2] != rect[:2]:
                self._move(self.shown[0], self.shown[1])
            self._persist()
            with_e = getattr(self.settings, "set_edge_dock_edge", None)
            if callable(with_e):
                with_e(edge)
            self._outside_since = time.monotonic() + grace if grace else None
            self._hits = 0
            self._timer.start()
            logger.info(f"{LOG_PREFIX} dockat vid {edge}: {self.shown}")

        def undock(self) -> None:
            """Sluta docka: fönstret hamnar direkt på sitt synliga läge och ligger kvar där."""
            self._stop_anim()
            if self.state in ("hidden", "animating") and self.shown is not None:
                self._move(self.shown[0], self.shown[1])
            was = self.state != "idle"
            self.state, self.edge, self.shown = "idle", None, None
            self._timer.stop()
            with_e = getattr(self.settings, "set_edge_dock_edge", None)
            if callable(with_e):
                with_e("")
            if was:
                self._persist()
                logger.info(f"{LOG_PREFIX} dockning avslutad")

        def adopt_saved(self) -> bool:
            """Vid start: var fönstret dockat när appen stängdes? Då fortsätter dockningen."""
            if not self._enabled():
                return False
            fn = getattr(self.settings, "edge_dock_edge", None)
            saved = fn() if callable(fn) else ""
            if saved not in geo.EDGES:
                return False
            rect = self._rect()
            screens = self._screens_fn()
            scr = geo.screen_for(rect, [a for a, _ in screens])
            if scr is None:
                return False
            full = next(f for a, f in screens if a == scr)
            allowed = geo.outer_edges(full, [f for _, f in screens])
            if geo.detect_edge(rect, scr, allowed, snap=geo.SNAP_PX + 40) != saved:
                with_e = getattr(self.settings, "set_edge_dock_edge", None)
                if callable(with_e):
                    with_e("")
                return False
            self.dock_to(saved, scr, grace=START_GRACE_S)
            return True

        def pin(self, on: bool) -> None:
            """Håll fönstret framme (t.ex. medan Ctrl+Alt+V hålls nere)."""
            self._pinned = bool(on)
            if not on:
                self._outside_since = time.monotonic()

        # ------------------------------------------------------ animation
        def _stop_anim(self) -> None:
            if self._anim is not None:
                self._anim.stop()
                self._anim = None

        def _slide(self, target: str) -> None:
            """target: 'hidden' eller 'shown'."""
            if self.shown is None or self.avail is None or self.edge is None:
                return
            end_r = (geo.hidden_rect(self.shown, self.avail, self.edge) if target == "hidden" else self.shown)
            start = self._rect()
            self._stop_anim()
            self.state, self._after_anim = "animating", target
            if self.anim_ms <= 0 or (start[0], start[1]) == (end_r[0], end_r[1]):
                self._move(end_r[0], end_r[1])
                self._finish_slide()
                return
            a = QVariantAnimation(self)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setDuration(self.anim_ms)
            a.setEasingCurve(QEasingCurve.Type.Linear)
            a.valueChanged.connect(lambda t, s=(start[0], start[1]), e=(end_r[0], end_r[1]):
                                   self._move(*geo.lerp_point(s, e, float(t))))
            a.finished.connect(lambda e=(end_r[0], end_r[1]): (self._move(*e), self._finish_slide()))
            self._anim = a
            a.start()

        def _finish_slide(self) -> None:
            self._anim = None
            self.state = self._after_anim
            self._hits = 0
            if self.state == "shown":
                self._outside_since = time.monotonic()
                self._persist()

        def hide(self) -> None:
            if self.state == "shown":
                self._slide("hidden")

        def reveal(self) -> None:
            if self.state == "hidden":
                self._slide("shown")
                with_r = getattr(self._shell(), "raise_", None)
                if callable(with_r):
                    with_r()
            elif self.state == "animating" and self._after_anim == "hidden":
                self._slide("shown")

        # ------------------------------------------------------------ takt
        def busy(self) -> bool:
            """Något pågår som gör att fönstret INTE ska gömmas."""
            if self._pinned or getattr(self.w, "_drag_active", False):
                return True
            if getattr(self.w, "_inline_edit", None) is not None:
                return True
            app = QApplication.instance()
            if app is not None and (app.activeModalWidget() is not None or app.activePopupWidget() is not None):
                return True
            inp = getattr(self.w, "input_field", None)
            try:
                if inp is not None and inp.text().strip() and self._shell().isActiveWindow():
                    return True  # du håller på att skriva
            except Exception:
                pass
            return False

        def _tick(self) -> None:
            try:
                if self.state == "animating" or self.shown is None or self.avail is None:
                    return
                if not self._enabled():
                    self.undock()
                    return
                sh = self._shell()
                if not sh.isVisible() or sh.isMinimized():
                    return
                cur = self._cursor_fn()
                if self.state == "shown":
                    if not self.busy() and self._rect() != self.shown:
                        self._readopt()
                        return
                    if self.busy() or geo.keep_shown(cur, self.shown):
                        self._outside_since = None
                    else:
                        now = time.monotonic()
                        if self._outside_since is None:
                            self._outside_since = now
                        elif now - self._outside_since >= HIDE_DELAY_S:
                            self.hide()
                elif self.state == "hidden":
                    if (not self._buttons_fn()
                            and geo.reveal_hit(cur, self.shown, self.avail, self.edge or "left")):
                        self._hits += 1
                        if self._hits >= REVEAL_TICKS:
                            self.reveal()
                    else:
                        self._hits = 0
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} _tick: {e}")

        def _readopt(self) -> None:
            """Fönstret flyttades/ändrade storlek medan det var framme → docka om (eller släpp dockningen)."""
            rect = self._rect()
            screens = self._screens_fn()
            scr = geo.screen_for(rect, [a for a, _ in screens])
            if scr is None:
                return
            full = next(f for a, f in screens if a == scr)
            allowed = geo.outer_edges(full, [f for _, f in screens])
            edge = geo.detect_edge(rect, scr, allowed)
            if edge is None:
                self.undock()
            else:
                self.dock_to(edge, scr)
