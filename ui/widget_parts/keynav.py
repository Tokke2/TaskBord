# -*- coding: utf-8 -*-
"""
ui/widget_parts/keynav.py — Tangentbordsnavigering i listan (piltangenter, markering) och aktivering för inmatning.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class KeyNavMixin:
    """Tangentbordsnavigering i listan (piltangenter, markering) och aktivering för inmatning."""

    def _navigate_tasks(self, key: int) -> None:
        """
        Tangentbordsnavigering i Aktiva-listan: ↑/↓ markerar föregående/nästa uppgift
        (Home/End = första/sista). Fokus flyttas från textfältet till listan så att
        Space/E/P/1–3/Delete kan användas; Esc eller klick i ett textfält lämnar läget.
        """
        try:
            if getattr(self, "_focus_mode", False):
                return
            tabs = getattr(self, "tabs", None)
            if tabs is not None and tabs.currentIndex() != 0:
                return
            tids = list(self._nav_tids)
            if not tids:
                return
            cur = self._sel_tid if self._sel_tid in tids else None
            if key == Qt.Key.Key_Home:
                new = tids[0]
            elif key == Qt.Key.Key_End:
                new = tids[-1]
            elif key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                step = 5 if key == Qt.Key.Key_PageDown else -5
                i = 0 if cur is None else tids.index(cur) + step
                new = tids[max(0, min(i, len(tids) - 1))]
            elif key == Qt.Key.Key_Down:
                new = tids[0] if cur is None else tids[min(tids.index(cur) + 1, len(tids) - 1)]
            else:  # Up
                if cur is None:
                    new = tids[-1]
                elif tids.index(cur) == 0:
                    # högst upp + ↑ = lämna listan, tillbaka till inmatningsfältet
                    self._nav_exit(focus_input=True)
                    return
                else:
                    new = tids[tids.index(cur) - 1]
            self._nav_select(new)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _navigate_tasks: {e}", exc_info=True)

    def _nav_select(self, tid: str) -> None:
        """Markera en uppgift, flytta fokus till listan och scrolla fram kortet."""
        self._sel_tid = tid
        self._nav_active = True
        with suppress(Exception):
            self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._nav_paint()
        card = self._task_widgets.get(tid)
        tabs = getattr(self, "tabs", None)
        if card is not None and tabs is not None:
            with suppress(Exception):
                tabs.widget(0).ensureWidgetVisible(card, 0, 24)
        get_throttle().notify_activity()

    def _nav_select_by_mouse(self, tid: str) -> None:
        """Klick på ett kort: markera det och gör fönstret redo för tangenter."""
        if tid not in self._nav_tids:
            return
        with suppress(Exception):
            self._activate_for_typing()  # tar bort NOACTIVATE så tangenter når fönstret
        self._nav_select(tid)

    def _nav_paint(self) -> None:
        """Sätt QSS-egenskapen taskSelected på rätt kort (och bara det)."""
        for _tid, _w in list(self._task_widgets.items()):
            want = (_tid == self._sel_tid) and self._nav_active
            try:
                if bool(_w.property("taskSelected")) != want:
                    _w.setProperty("taskSelected", want)
                    _w.style().unpolish(_w)
                    _w.style().polish(_w)
            except RuntimeError:
                pass  # kortet hann raderas

    def _nav_exit(self, focus_input: bool = False) -> None:
        """Lämna navigeringsläget (ta bort markeringen)."""
        self._nav_active = False
        self._sel_tid = None
        self._nav_paint()
        if focus_input and getattr(self, "input_field", None) is not None:
            with suppress(Exception):
                self.input_field.setFocus()

    def _nav_after_render(self, new_tids: List[str]) -> None:
        """Efter varje ombyggnad: behåll markeringen, eller flytta den till grannen."""
        old = list(self._nav_tids)
        self._nav_tids = list(new_tids)
        sel = self._sel_tid
        if sel is not None and sel not in new_tids:
            if self._nav_active and new_tids:
                i = old.index(sel) if sel in old else 0
                sel = new_tids[min(i, len(new_tids) - 1)]
            else:
                sel = None
            self._sel_tid = sel
            if sel is None:
                self._nav_active = False
        self._nav_paint()

    def _handle_nav_key(self, event: QKeyEvent) -> bool:
        """
        Tangenter i navigeringsläget. Returnerar True om tangenten förbrukades.

        Space = klar/oklar · E/F2 = redigera titel · P = fäst/lossa · Delete = ta bort
        1/2/3 = hög/normal/låg prioritet · 0 = ingen · Home/End/PgUp/PgDn · Esc = lämna.
        Vanlig text (övriga tecken) lämnar läget och skrivs in i inmatningsfältet.
        """
        if not self._nav_active or not self._sel_tid:
            return False
        if getattr(self, "_focus_mode", False):
            return False
        from PySide6.QtWidgets import QApplication, QLineEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            return False
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        key = event.key()
        tid = self._sel_tid
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
                   Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self._navigate_tasks(key)
            return True
        if key == Qt.Key.Key_Escape:
            self._nav_exit(focus_input=True)
            return True
        get_throttle().notify_activity()
        if key == Qt.Key.Key_Space:
            self._on_task_toggle(tid, True)
            return True
        if key in (Qt.Key.Key_E, Qt.Key.Key_F2):
            self._prompt_rename(tid)
            return True
        if key == Qt.Key.Key_P:
            self._on_pin_toggle(tid)
            return True
        if key == Qt.Key.Key_Delete:
            self._prompt_delete(tid)
            return True
        _prio = {
            Qt.Key.Key_1: "high", Qt.Key.Key_2: "medium",
            Qt.Key.Key_3: "low", Qt.Key.Key_0: "none",
        }.get(key)
        if _prio is not None:
            self._set_task_priority(tid, _prio)
            return True
        txt = event.text() if hasattr(event, "text") else ""
        if txt and txt.isprintable():
            # började skriva → tillbaka till inmatningsfältet med tecknet
            self._nav_exit(focus_input=True)
            with suppress(Exception):
                self.input_field.insert(txt)
            return True
        return False

    # ====================================================================
    # EVENT HANDLERS (NY v6.4.1 v7 - forbattrade med svenska loggar)
    # ====================================================================

    def _activate_for_typing(self) -> None:
        """
        NY v7-fix73: gör fönstret SKRIVBART vid klick.

        Rickard 2026-10-06: "kan inte skriva i textfältet" — fönstret
        har WS_EX_NOACTIVATE (stjäl inte fokus) men den blockerar
        OCKSÅ tangentbordsinput! Lösning: vid klick/fokus i ett
        textfält → ta bort NOACTIVATE + gör förgrunds-fönster →
        användaren kan skriva. Vid focusOut → NOACTIVATE tillbaka
        (stjäl inte fokus från andra appar när den inte används).
        """
        try:
            if sys.platform != "win32":
                return
            import ctypes
            _sh = getattr(self, "_shell", None)
            _win = _sh if _sh is not None else self
            _hwnd = 0
            with suppress(Exception):
                _hwnd = int(_win.winId())
            if not _hwnd:
                return
            _u = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            _ex = _u.GetWindowLongW(_hwnd, GWL_EXSTYLE)
            if _ex & WS_EX_NOACTIVATE:
                _u.SetWindowLongW(
                    _hwnd, GWL_EXSTYLE, _ex & ~WS_EX_NOACTIVATE
                )
                _win._noact_saved = True
                logger.info(
                    f"{LOG_PREFIX} FÖNSTER AKTIVERAT för inmatning "
                    f"(NOACTIVATE av) — nu går det att skriva (v7-fix73)"
                )
            with suppress(Exception):
                _u.SetForegroundWindow(_hwnd)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _activate_for_typing: {e}"
            )

    def _deactivate_restore_noact(self) -> None:
        """NY v7-fix73: fönstret tappade fokus → NOACTIVATE tillbaka."""
        try:
            if sys.platform != "win32":
                return
            import ctypes
            _sh = getattr(self, "_shell", None)
            _win = _sh if _sh is not None else self
            if not getattr(_win, "_noact_saved", False):
                return
            with suppress(Exception):
                _hwnd = int(_win.winId())
                if not _hwnd:
                    return
                _u = ctypes.windll.user32
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                _ex = _u.GetWindowLongW(_hwnd, GWL_EXSTYLE)
                if not (_ex & WS_EX_NOACTIVATE):
                    _u.SetWindowLongW(
                        _hwnd, GWL_EXSTYLE, _ex | WS_EX_NOACTIVATE
                    )
                    _win._noact_saved = False
                    logger.info(
                        f"{LOG_PREFIX} Fönster deaktiverat — NOACTIVATE "
                        f"aterställd (stjäl ej fokus) (v7-fix73)"
                    )
        except Exception as e:
            logger.debug(
                f"{LOG_PREFIX} _deactivate_restore_noact: {e}"
            )
