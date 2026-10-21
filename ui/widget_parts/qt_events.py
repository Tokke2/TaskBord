# -*- coding: utf-8 -*-
"""
ui/widget_parts/qt_events.py — Qt-händelser: mus, stäng, fokus, storlek/flytt, visa/dölj, förändring och nativeEvent samt geometrispar.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class QtEventsMixin:
    """Qt-händelser: mus, stäng, fokus, storlek/flytt, visa/dölj, förändring och nativeEvent samt geometrispar."""

    @_log_event("event:mouse_press")
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        NY v6.4.1 v7: Börja drag (med bring_to_front vid klick).

        FIX v7-fix39 (2026-10-01, Rickard: "fönstret går inte att
        flytta även fast man låst upp"):
          1. BUGG: int(event.button()) i logg-raden kraschade vid
             VARJE klick (PySide6-enum har inte int()) — och eftersom
             f-string-defaulten i dict.get() utvärderas ALLTID dog
             hela mousePressEvent → drag startade ALDRIG.
          2. BUGG: mouseMoveEvent loggade odefinierade old_x/old_y
             → NameError vid första drag-rörelsen.
          3. NYTT: HELA fönstret är nu dragbart — vänsterklick som
             når widgeten (dvs. INTE fångas av knappar/kort/fält)
             startar drag, inte bara översta 42 px-remsan.

        Princip: DRAG-LOGIK FÖRST — loggning körs sist och får
        ALDRIG döda funktionalitet.
        """
        # === 0. AKTIVERA FÖR SKRIVNING (v7-fix73) ==================
        # Varje vänsterklick på widgeten → ta bort NOACTIVATE så
        # tangentbordet fungerar (fokus sätts av Qt/Windows).
        with suppress(Exception):
            self._activate_for_typing()

        # === 1. DRAG (körs först — krash-säkrat) ====================
        try:
            get_throttle().notify_activity()
        except Exception:
            pass
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                if (self._locked and not (
                        event.modifiers()
                        & Qt.KeyboardModifier.ShiftModifier)):
                    logger.debug(
                        f"{LOG_PREFIX} drag blockerat (fonstret låst, "
                        f"håll Shift för att flytta)"
                    )
                    event.ignore()
                    return
                _shell = getattr(self, "_shell", None)
                _origin = (
                    _shell.frameGeometry().topLeft()
                    if _shell is not None
                    else self.frameGeometry().topLeft()
                )
                self._drag_offset = (
                    event.globalPosition().toPoint() - _origin
                )
                self._drag_active = True
                _zone = (
                    "handle" if event.y() < DRAG_HANDLE_HEIGHT else "yta"
                )
                logger.debug(
                    f"{LOG_PREFIX} drag startad (zon={_zone}, "
                    f"y={event.y()}, locked={self._locked})"
                )
                event.accept()
                return
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} drag-start misslyckades: "
                f"{_describe_widget_error(e)}"
            )

        # === 2. Övriga knappar (befintligt beteende) =================
        try:
            # Visa widget temporärt överst vid klick
            self.bring_to_front()
        except Exception:
            pass
        try:
            super().mousePressEvent(event)
        except Exception:
            pass

        # === 3. Diagnostik (SIST — får aldrig påverka ovanstående) ==
        with suppress(Exception):
            _btn = {
                Qt.MouseButton.LeftButton: "Left",
                Qt.MouseButton.RightButton: "Right",
                Qt.MouseButton.MiddleButton: "Middle",
            }.get(event.button())
            if _btn is None:
                # v7-fix39: int() på PySide6-enum = TypeError —
                # använd .name/str() istället
                _btn = _qt_enum_name(event.button(), "btn=?")
            _mods = []
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                _mods.append("Shift")
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                _mods.append("Ctrl")
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                _mods.append("Alt")
            _mod_str = "+".join(_mods) if _mods else "-"
            logger.debug(
                f"{LOG_PREFIX} mousePress "
                f"btn={_btn} mods={_mod_str} "
                f"local=({event.x()},{event.y()}) "
                f"global=({event.globalPosition().toPoint().x()},"
                f"{event.globalPosition().toPoint().y()}) "
                f"locked={self._locked}"
            )

    @_log_event("event:mouse_move")
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """NY v6.4.1 v7: Drag (med bättre loggning).
        FIX 2026-09-24: trace under hela drag-rörelsen.
        FIX v7-fix39: old_x/old_y var ODEFINIERADE → NameError vid
        första drag-rörelsen (fönstret flyttades aldrig). Nu loggas
        skal-fönstrets faktiska position före/efter."""
        try:
            if (self._drag_active and self._drag_offset is not None and
                    (event.buttons() & Qt.MouseButton.LeftButton)):
                new_pt = event.globalPosition().toPoint() - self._drag_offset
                _shell_m = getattr(self, "_shell", None)
                _target = _shell_m if _shell_m is not None else self
                _old_x, _old_y = _target.x(), _target.y()
                # v7-fix48: komposterad flytt — rätt skärm-position
                # även när fönstret är barn i skrivbordet (Progman)
                self._shell_screen_move(new_pt.x(), new_pt.y())
                logger.debug(
                    f"{LOG_PREFIX} mouseMove DRAG "
                    f"({_old_x},{_old_y}) → ({_target.x()},{_target.y()}) "
                    f"size={_target.width()}x{_target.height()}"
                )
                event.accept()
            else:
                super().mouseMoveEvent(event)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} mouseMoveEvent misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("event:mouse_release")
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """NY v6.4.1 v7: Avsluta drag + BUGG 26 auto-reposition.
        FIX 2026-09-24: full release-info."""
        try:
            _shell_r = getattr(self, "_shell", None)
            _final = (
                (_shell_r.x(), _shell_r.y())
                if _shell_r is not None
                else (self.x(), self.y())
            )
            logger.debug(
                f"{LOG_PREFIX} mouseRelease "
                f"btn=L?{event.button() == Qt.MouseButton.LeftButton} "
                f"was_dragging={self._drag_active} "
                f"final_pos=({_final[0]},{_final[1]})"
            )
            self._drag_active = False
            self._drag_offset = None
            # NY v7-fix9: Tvinga SPARNING av slutpositionen (förbi 500ms-
            # throttlen i moveEvent). Utan detta kunde sista positionen
            # tappas om användaren släppte inom 500 ms efter senaste save.
            #
            # OBS: Anropade tidigare _auto_reposition_if_needed() här — det
            # var fel, eftersom den flyttar widgeten TILL den sparade
            # positionen och därmed kunde ångra användarens drag.
            # FIX v7-fix33: spara SKALETS position om vi är barn
            _shell = getattr(self, "_shell", None)
            if _shell is not None:
                _sx, _sy = _shell.x(), _shell.y()
            else:
                _sx, _sy = self.x(), self.y()
            with suppress(Exception):
                if hasattr(self.settings, "update_window_geometry"):
                    # NY v7-fix43: slutposition + slutstorlek
                    self.settings.update_window_geometry(
                        self.win_id, _sx, _sy,
                        (_shell.width() if _shell is not None
                         else self.width()),
                        (_shell.height() if _shell is not None
                         else self.height()),
                    )
                    self._last_pos_save = time.monotonic()
                    self._last_size_save = time.monotonic()
                elif hasattr(self.settings, "update_window_position"):
                    self.settings.update_window_position(
                        self.win_id, _sx, _sy
                    )
                    self._last_pos_save = time.monotonic()
            logger.debug(f"{LOG_PREFIX} drag avslutad vid ({_sx}, {_sy})")
            event.accept()
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} mouseReleaseEvent misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("event:close")
    def closeEvent(self, event: QCloseEvent) -> None:
        """
        NY v6.4.1 v7: Close = satta z-order (widget stannar synlig).
        FIX 2026-09-24: Tillåt close när _allow_close=True
        (shutdown, populate-remove, pretest) — annars spöken
        som stod kvar över appar.
        """
        try:
            if getattr(self, "_allow_close", False):
                event.accept()
                with __import__("contextlib").suppress(Exception):
                    self.hide()
                logger.info(
                    f"{LOG_PREFIX} closeEvent: TILLÅTEN "
                    f"(win_id={self.win_id!r}) — stängs"
                )
                return
            event.ignore()  # BUGG 19: normal close = stanna synlig
            self._setup_bugg19_zorder()
            self._audit.add("close_event_ignored")
            logger.debug(
                f"{LOG_PREFIX} closeEvent ignorerad (BUGG 19: "
                f"widget stannar synlig pa skrivbordet)"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} closeEvent misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("event:focus_in")
    def focusInEvent(self, event):
        """FIX 2026-09-24: logga när widgeten får fokus."""
        logger.debug(f"{LOG_PREFIX} focusInEvent: {type(event).__name__}")
        super().focusInEvent(event)

    @_log_event("event:focus_out")
    def focusOutEvent(self, event):
        """FIX 2026-09-24: logga när widgeten tappar fokus.
        NY v7-fix73: + återställ NOACTIVATE (stjäl ej fokus längre)."""
        logger.debug(f"{LOG_PREFIX} focusOutEvent: {type(event).__name__}")
        with suppress(Exception):
            self._deactivate_restore_noact()
        super().focusOutEvent(event)

    # FIX 2026-09-25: säkra position-extrahering (event.position() kan saknas)
    @staticmethod
    def _pt_of(ev) -> tuple:
        try:
            # Ny Qt6 API: position() -> QPointF
            if hasattr(ev, "position") and callable(ev.position):
                p = ev.position()
                return (int(p.x()), int(p.y()))
        except Exception:
            pass
        # Äldre / fallback
        if hasattr(ev, "pos"):
            p = ev.pos()
            return (int(p.x()), int(p.y()))
        return (-1, -1)

    @_log_event("event:enter")
    def enterEvent(self, event):
        """FIX 2026-09-24: logga hover-in."""
        try:
            _x, _y = self._pt_of(event)
            logger.debug(
                f"{LOG_PREFIX} enterEvent: hover börjar @ ({_x},{_y})"
            )
            super().enterEvent(event)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} enterEvent misslyckades: {e}")

    @_log_event("event:leave")
    def leaveEvent(self, event):
        """FIX 2026-09-24: logga hover-out."""
        try:
            _x, _y = self._pt_of(event)
            logger.debug(
                f"{LOG_PREFIX} leaveEvent: hover slutar @ ({_x},{_y})"
            )
            super().leaveEvent(event)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} leaveEvent misslyckades: {e}")

    @_log_event("event:wheel")
    def wheelEvent(self, event):
        """FIX 2026-09-24: logga scroll."""
        try:
            _x, _y = self._pt_of(event)
            _delta = (
                (event.angleDelta().x(), event.angleDelta().y())
                if hasattr(event, "angleDelta")
                else (0, 0)
            )
            logger.debug(
                f"{LOG_PREFIX} wheelEvent delta={_delta} @ ({_x},{_y})"
            )
            super().wheelEvent(event)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} wheelEvent misslyckades: {e}")

    @_log_event("event:resize")
    def _save_geometry_now(self) -> None:
        """NY v7-fix43: spara skal-geometri (position + storlek)."""
        try:
            _sh = getattr(self, "_shell", None)
            _g = _sh if _sh is not None else self
            # FIX v8: spara aldrig skräpgeometri (minimerat fönster ligger på
            # (-32000,-32000) i Windows) — då skulle riktiga läget skrivas över.
            if _g.isMinimized() or _g.x() <= -10000 or _g.y() <= -10000:
                return
            if hasattr(self.settings, "update_window_geometry"):
                self.settings.update_window_geometry(
                    self.win_id,
                    _g.x(), _g.y(), _g.width(), _g.height(),
                )
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _save_geometry_now: {e}")

    def resizeEvent(self, event: QResizeEvent) -> None:
        """FIX 2026-09-24: full resize-info."""
        try:
            logger.debug(
                f"{LOG_PREFIX} resizeEvent "
                f"old=({event.oldSize().width()}x{event.oldSize().height()}) "
                f"new=({event.size().width()}x{event.size().height()}) "
                f"final_pos=({self.x()},{self.y()})"
            )
            self._pixmap_cache.clear()
            # NY v7-fix43: debounced sparning — timern startas om vid
            # VARJE resize och sparar 600 ms efter den SISTA (garanterar
            # att slutstorleken alltid sparas, även snabba drag)
            _timer = getattr(self, "_size_save_timer", None)
            if _timer is None:
                _timer = QTimer(self)
                _timer.setSingleShot(True)
                _timer.setInterval(600)
                _timer.timeout.connect(self._save_geometry_now)
                self._size_save_timer = _timer
            _timer.start()
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} resizeEvent misslyckades: {e}"
            )

    @_log_event("event:move")
    def moveEvent(self, event: QMoveEvent) -> None:
        """
        FIX 2026-09-24: full move-info + throttlad positionssparning.

        NY v7-fix9: Throttle 500 ms — förhindrar att varje pixel-drag
        skriver till settings (vilket tidigare triggade
        windows_updated → populate → show → moveEvent i en loop).
        Slutpositionen sparas alltid i mouseReleaseEvent (förbi throttlen).
        """
        try:
            cur_x, cur_y = self.x(), self.y()
            old_x, old_y = event.oldPos().x(), event.oldPos().y()
            logger.debug(
                f"{LOG_PREFIX} moveEvent: ({old_x},{old_y}) → ({cur_x},{cur_y}) "
                f"win_id={self.win_id!r} drag={self._drag_active}"
            )
            if not self._drag_active:
                # Programmatisk flytt (auto-reposition, z-order, skärmbyte)
                # — spara direkt, throttlen gäller bara användar-drag.
                # FIX v7-fix43: i barn-läge är self.x()/y() LOKALA (0,0)
                # — läs SKALETS skärmposition istället!
                _sh_m = getattr(self, "_shell", None)
                if _sh_m is not None:
                    cur_x, cur_y = _sh_m.x(), _sh_m.y()
                logger.debug(
                    f"{LOG_PREFIX} moveEvent: programmatisk flytt — "
                    f"sparar utan throttle (skal-pos {cur_x},{cur_y})"
                )
                if hasattr(self.settings, "update_window_position"):
                    self.settings.update_window_position(
                        self.win_id, cur_x, cur_y
                    )
                    self._last_pos_save = time.monotonic()
                return
            # Användar-drag → throttla (max 2 sparningar/sekund)
            now = time.monotonic()
            last = getattr(self, "_last_pos_save", 0.0)
            elapsed_ms = (now - last) * 1000.0
            if elapsed_ms < 500.0:
                logger.trace(
                    f"{LOG_PREFIX} moveEvent: throttle — "
                    f"{elapsed_ms:.0f}ms sedan senaste save (<500ms)"
                )
                return
            self._last_pos_save = now
            # FIX v7-fix43: läs SKALETS position i barn-läge
            _sh_d = getattr(self, "_shell", None)
            if _sh_d is not None:
                cur_x, cur_y = _sh_d.x(), _sh_d.y()
            logger.debug(
                f"{LOG_PREFIX} moveEvent: sparar position "
                f"({cur_x},{cur_y}) — {elapsed_ms:.0f}ms sedan senaste"
            )
            if hasattr(self.settings, "update_window_position"):
                self.settings.update_window_position(
                    self.win_id, cur_x, cur_y
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} moveEvent misslyckades: {e}"
            )

    @_log_event("event:show")
    def _is_child(self) -> bool:
        """FIX v7-fix29: Är vi ett barn-widget (i skal-QWidget)?"""
        try:
            return self.parent() is not None
        except Exception:
            return False

    def _native_window_ok(self) -> bool:
        """
        NY v7-fix18: finns ett fungerande nativt fönster?

        OBS: QWidget::winId() TVINGAR fram fönster-skapande — därför
        läser vi QWindow::winId() via windowHandle() istället (ren
        getter som ALDRIG skapar). False innan första show() (normalt)
        och True efter en lyckad show().
        """
        try:
            if self._is_child():
                # Barn: kolla FÖRÄLDERNs fönster (skalet)
                _p = self.parent()
                if _p is None:
                    return False
                _ph = _p.windowHandle()
                return _ph is not None and int(_ph.winId()) != 0
            wh = self.windowHandle()
            if wh is None:
                return False
            return int(wh.winId()) != 0
        except Exception:
            return False

    def _handle_window_creation_failure(self) -> None:
        """
        NY v7-fix18: CreateWindowEx misslyckades → karantän + backoff.

        Storm-mekaniken som brutits:
          show() → [fönstret kan ej skapas] → Qt försöker igen vid varje
          expose/paint + VÅRA winId()-anrop tvingar fram fler försök →
          tusentals "CreateWindowEx failed"-rader per minut.

        Nu: hide() stoppar Qt:s omförsök OMEDELBART (stormen dör),
        sedan max 5 nya försök med exponentiell backoff (2s → 20s).
        """
        self._win_fail_count = getattr(self, "_win_fail_count", 0) + 1
        n = self._win_fail_count
        if n == 2:
            # FIX v7-fix20: sond — skiljer miljö-fel från vår widget-setup
            self._probe_bare_window()
        if n == 1:
            # FIX v7-fix25: FULL STACK-TRACE — visar EXAKT vilken
            # kodrad som ledde till show()-anropet
            import traceback as _tb_full
            _stack = "".join(_tb_full.format_stack())
            logger.critical(
                f"{LOG_PREFIX} ★ STACK-TRACE (exakt kodväg till "
                f"misslyckat show()):\n{_stack}"
            )
            thread_txt = "okänd"
            try:
                from PySide6.QtCore import QThread
                thread_txt = QThread.currentThread().objectName() or "main"
            except Exception:
                pass
            logger.error(
                f"{LOG_PREFIX} ★ FÖNSTERSKAPANDE MISSLYCKADES (försök 1) "
                f"— karantän + backoff. Tråd={thread_txt} "
                f"geo=({self.x()},{self.y()}) {self.width()}x{self.height()} "
                f"flags={int(self.windowFlags())} dpr={self._dpr}. "
                f"Vanligaste orsaken: ogiltig geometri i settings.json "
                f"(klamras nu automatiskt, se _restore_window_position)."
            )
        try:
            self.hide()  # stoppar expose/paint-omförsöken = stormen dör
        except Exception:
            pass
        if n >= 5:
            logger.error(
                f"{LOG_PREFIX} Fönstret kunde inte skapas efter {n} "
                f"försök — GER UPP (appen fortsätter, tray fungerar). "
                f"ÅTGÄRD: 1) stäng appen 2) öppna data\\settings.json och "
                f"radera hela \"windows\"-avsnittet 3) starta igen. "
                f"Uppdatera ev. grafikdrivrutin."
            )
            return
        delay_ms = min(2000 * (2 ** (n - 1)), 20000)
        logger.warning(
            f"{LOG_PREFIX} fönster-karantän: nytt försök om {delay_ms} ms "
            f"(försök {n + 1}/5)"
        )
        QTimer.singleShot(delay_ms, self._retry_show_after_failure)

    def _probe_bare_window(self) -> None:
        """
        NY v7-fix20: skapa ett BART QWidget och försök visa det.

        Skiljer MILJÖ-fel (Qt-installation/drvrutin/Python-version) från
        fel i VÅR widget-setup:
          probe OK  → miljön kan skapa fönster → problemet är vår setup
          probe FALLER → hela Qt-installationen kan inte skapa fönster
                      → åtgärd: 'pip install --upgrade PySide6'
        """
        try:
            from PySide6.QtWidgets import QWidget as _QW
            probe = _QW()
            probe.setObjectName("DTPProbe")
            probe.setWindowTitle("TaskBord-probe")
            probe.resize(200, 100)
            probe.show()
            _ok = False
            try:
                _wh = probe.windowHandle()
                _ok = _wh is not None and int(_wh.winId()) != 0
            except Exception:
                _ok = False
            if _ok:
                logger.error(
                    f"{LOG_PREFIX} ★ PROBE: bart QWidget SKAPADES OK → "
                    f"miljön fungerar, problemet är TodoWidget:s setup "
                    f"(flags/ikoner/barn). Rapport: window_failure_report.txt"
                )
            else:
                logger.error(
                    f"{LOG_PREFIX} ★ PROBE: bart QWidget MISSLYCKADES "
                    f"också → HELA Qt-installationen kan inte skapa "
                    f"fönster. ÅTGÄRD: pip install --upgrade PySide6 "
                    f"(Python 3.14 kräver färsk PySide6!)"
                )
            with suppress(Exception):
                probe.close()
                probe.deleteLater()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} probe misslyckades: {e}")

    def _retry_show_after_failure(self) -> None:
        """NY v7-fix18: backoff-retry efter misslyckat fönsterskapande."""
        logger.info(f"{LOG_PREFIX} fönster-karantän: försöker visa igen…")
        try:
            self.show()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} retry-show misslyckades: {e}")

    def showEvent(self, event):
        """FIX 2026-09-24: logga + återställ z-order när widgeten syns.

        FIX v7-fix18: om det nativa fönstret inte kunde skapas går vi i
        karantän DIRECT (winId() i logg-raden tvingade tidigare fram nya
        CreateWindowEx-försök vid VARJE event = storm-motorn)."""
        try:
            if sys.platform == "win32" and not self._native_window_ok():
                self._handle_window_creation_failure()
                with suppress(Exception):
                    super().showEvent(event)
                return
            if getattr(self, "_win_fail_count", 0) > 0:
                logger.info(
                    f"{LOG_PREFIX} fönstret SKAPAT EFTER karantän — "
                    f"återställer felräknare"
                )
                self._win_fail_count = 0
            _hwnd_txt = "(saknas)"
            if self._native_window_ok():
                with suppress(Exception):
                    _hwnd_txt = str(int(self.winId()))
            _sh_s = getattr(self, "_shell", None)
            logger.info(
                f"{LOG_PREFIX} 🔺 showEvent: FÖNSTRET SYNS — "
                f"win_id={self.win_id!r} HWND={_hwnd_txt} "
                f"pos=({self.x()},{self.y()}) "
                f"size=({self.width()}x{self.height()})"
                + (
                    f" skal=({_sh_s.x()},{_sh_s.y()}) "
                    f"{_sh_s.width()}x{_sh_s.height()}"
                    if _sh_s is not None else ""
                )
            )
            super().showEvent(event)
            # FIX 2026-09-25 v7-fix7: reentrancy-skydd — showEvent → SetWindowPos
            # → moveEvent → save → signal → populate → show() → showEvent (LOOP!).
            # Hoppa över z-order-push om vi redan satt denna cykel.
            if getattr(self, "_zorder_in_show", False):
                return
            self._zorder_in_show = True
            try:
                # FIX 2026-09-25: reaktiv HWND_BOTTOM (andra fönster kan ha flyttat oss)
                with suppress(Exception):
                    self._setup_bugg19_zorder()
            finally:
                self._zorder_in_show = False
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} showEvent misslyckades: {e}"
            )

    @_log_event("event:hide")
    def hideEvent(self, event):
        """
        FIX 2026-09-24: logga när widgeten göms.
        NY v7-fix44 (500000%-loggningen): synlighetsspårning —
        visar VEM/VAD som gömde fönstret + skal-status + orsak.
        """
        try:
            # FIX v7-fix18: winId() får aldrig tvinga fram skapande
            _hwnd_txt = "(saknas)"
            if self._native_window_ok():
                with suppress(Exception):
                    _hwnd_txt = str(int(self.winId()))
            # Kort anropsstack — vem gömde oss?
            _cause = "?"
            with suppress(Exception):
                import traceback as _tb
                _frames = _tb.extract_stack(limit=4)[:-1]
                if _frames:
                    _f = _frames[-1]
                    _cause = f"{_f.name} ({_f.filename.split(chr(92))[-1]}:{_f.lineno})"
            _sh = getattr(self, "_shell", None)
            _sh_state = (
                f"skal synlig={_sh.isVisible()}" if _sh is not None
                else "inget skal (fristående)"
            )
            _why = (
                "APPMEN STÄNGER (allow_close=True)"
                if getattr(self, "_allow_close", False)
                else "GÖMS (X-knapp/toggle/hotkey eller systemet)"
            )
            logger.info(
                f"{LOG_PREFIX} 🔻 hideEvent: FÖNSTRET GÖMS — "
                f"win_id={self.win_id!r} HWND={_hwnd_txt} | "
                f"{_why} | {_sh_state} | orsak={_cause}"
            )
            super().hideEvent(event)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} hideEvent misslyckades: {e}"
            )

    @_log_event("event:change")
    def changeEvent(self, event):
        """FIX 2026-09-24: logga state-changes (minimized, fullscreen…).
        FIX v7-fix10: windowState() är enum i PySide6 >= 6.9 — int() kraschar
        där; !r funkar i ALLA versioner (och är mer läsbart i loggen)."""
        try:
            _etype = getattr(event.type(), "name", None) or repr(event.type())
            logger.debug(
                f"{LOG_PREFIX} changeEvent type={_etype} "
                f"state={self.windowState()!r}"
            )
            super().changeEvent(event)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} changeEvent misslyckades: {e}"
            )

    @_log_event("event:native")
    def nativeEvent(self, eventType, message):
        """
        NY v6.4.1 v7: Win32-event handler — blockerar Win+D-hide.

        Rickard 2026-09-25: "Win+D ska ej funka för att dölja fönstret".

        Skydd:
          1. WM_SYSCOMMAND + SC_MINIMIZE/SC_CLOSE → blockera + re-show
          2. WM_SIZE + SIZE_MINIMIZED → blockera + re-show
          3. WM_SHOWWINDOW wParam utan SW_SHOW-flagga → blockera
        """
        if sys.platform != "win32":
            return False, 0
        # FIX v7-fix29: barn → skalet hanterar native events
        if self._is_child():
            return False, 0
        try:
            import ctypes
            from ctypes import wintypes
            WM_SYSCOMMAND = 0x0112
            WM_SIZE = 0x0005
            WM_SHOWWINDOW = 0x0018
            SC_MINIMIZE = 0xF020
            SC_CLOSE = 0xF060
            SIZE_MINIMIZED = 1
            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt_x", wintypes.LONG),
                    ("pt_y", wintypes.LONG),
                ]
            msg = MSG.from_address(int(message))
            user32 = ctypes.windll.user32
            # FIX v7-fix18: winId() får aldrig tvinga fram skapande
            hwnd = int(self.winId()) if self._native_window_ok() else 0

            if msg.message == WM_SYSCOMMAND:
                cmd = msg.wParam & 0xFFF0
                if cmd == SC_MINIMIZE or cmd == SC_CLOSE:
                    label = "SC_MINIMIZE" if cmd == SC_MINIMIZE else "SC_CLOSE"
                    logger.info(
                        f"{LOG_PREFIX} nativeEvent: blockerade {label} (Win+D-skydd)"
                    )
                    if hwnd:
                        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                    return True, 0
            if msg.message == WM_SIZE:
                if msg.wParam == SIZE_MINIMIZED:
                    logger.info(
                        f"{LOG_PREFIX} nativeEvent: blockerade WM_SIZE=SIZE_MINIMIZED"
                    )
                    if hwnd:
                        user32.ShowWindow(hwnd, 4)
                    return True, 0
            if msg.message == WM_SHOWWINDOW:
                if not (msg.wParam & 1):  # bit 0 = SW_SHOW
                    logger.info(
                        f"{LOG_PREFIX} nativeEvent: blockerade WM_SHOWWINDOW"
                        f" wParam={msg.wParam}"
                    )
                    if hwnd:
                        user32.ShowWindow(hwnd, 4)
                    return True, 0
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} nativeEvent misslyckades: {e}")
        return False, 0
