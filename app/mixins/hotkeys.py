# -*- coding: utf-8 -*-
"""Globala snabbtangenter (snabbtillägg och push-to-show)."""

from __future__ import annotations

import sys
from contextlib import suppress

from app.config import parse_hotkey_combo
from app.constants import APP_NAME, LOG_PREFIX


class HotkeysMixin:
    """Globala snabbtangenter (snabbtillägg och push-to-show)."""

    # ------------------------------------------------------------------
    # Registrering av globala snabbtangenter
    # ------------------------------------------------------------------
    _QUICK_ADD_ID = 0xB41
    _PUSH_SHOW_ID = 0xB42
    _MOD_NOREPEAT = 0x4000  # håll inne tangenten → bara EN utlösning
    _global_hotkey_id = None        # id när snabbinput-tangenten är registrerad
    _quick_add_registered = None    # kombinationen som är registrerad just nu
    _global_hotkey_filter = None

    def _ensure_hotkey_filter(self) -> None:
        """
        Installera Qt-filtret som fångar WM_HOTKEY — alltid, en enda gång.

        Förr installerades filtret först NÄR standardtangenten lyckades
        registreras. Var Ctrl+Alt+N upptagen vid start (eller snabbinput
        avstängd) fick man sedan en tangent som registrerades via menyn men
        som ingen lyssnade på förrän nästa omstart.
        """
        if getattr(self, "_global_hotkey_filter", None) is not None:
            return
        import ctypes
        from PySide6.QtCore import QAbstractNativeEventFilter

        ctrl = self

        class _HotkeyFilter(QAbstractNativeEventFilter):
            """Fångar WM_HOTKEY i Qt:s meddelandepump (GUI-tråden)."""

            def nativeEventFilter(self, eventType, message):
                try:
                    if eventType != b"windows_generic_MSG":
                        return False

                    class _MSG(ctypes.Structure):
                        _fields_ = [
                            ("hwnd", ctypes.c_void_p),
                            ("message", ctypes.c_uint),
                            ("wParam", ctypes.c_size_t),
                            ("lParam", ctypes.c_ssize_t),
                            ("time", ctypes.c_uint32),
                            ("pt_x", ctypes.c_long),
                            ("pt_y", ctypes.c_long),
                        ]

                    m_ = _MSG.from_address(int(message))
                    if m_.message != 0x0312:
                        return False
                    hk = m_.wParam & 0xFFFF
                    if hk == getattr(ctrl, "_global_hotkey_id", None):
                        ctrl._log.info(
                            f"{LOG_PREFIX} Global snabbinput-hotkey "
                            f"triggad ({ctrl._get_quick_add_hotkey_combo()}, "
                            f"var som helst i Windows)"
                        )
                        ctrl._QTimer.singleShot(0, ctrl._global_quick_add)
                        return True
                    # NY v7-fix68: push-to-show (Ctrl+Alt+V intryckt)
                    if hk == getattr(ctrl, "_push_hotkey_id", None):
                        ctrl._QTimer.singleShot(0, ctrl._push_show_press)
                        return True
                    # Markerad text → uppgift (Ctrl+Alt+K)
                    if hk == 0xB43 and getattr(ctrl, "_clip_task_registered", None):
                        ctrl._QTimer.singleShot(0, ctrl._clip_task_press)
                        return True
                    # Alltid överst på/av (Ctrl+Alt+T)
                    if hk == 0xB44 and getattr(ctrl, "_top_toggle_registered", None):
                        ctrl._QTimer.singleShot(0, ctrl._top_toggle_press)
                        return True
                except Exception:
                    pass
                return False

        self._global_hotkey_filter = _HotkeyFilter()
        self._app.installNativeEventFilter(self._global_hotkey_filter)

    def _register_quick_add_hotkey(self, combo: str) -> "tuple[bool, str]":
        """
        Registrera (eller byt till) snabbinput-tangenten ``combo``.

        Den gamla avregistreras först (Windows tillåter bara en registrering
        per kombination). Misslyckas den nya registreras den gamla tillbaka
        så att man aldrig står utan fungerande tangent. → (ok, orsak)
        """
        if sys.platform != "win32":
            return False, "Globala snabbtangenter finns bara i Windows."
        mods, vk = parse_hotkey_combo(combo)
        if not vk:
            return False, f"'{combo}' kunde inte tolkas."
        import ctypes
        user32 = ctypes.windll.user32
        hk_id = self._QUICK_ADD_ID
        previous = getattr(self, "_quick_add_registered", None)
        with suppress(Exception):
            user32.UnregisterHotKey(None, hk_id)
        self._global_hotkey_id = None
        ok = bool(user32.RegisterHotKey(None, hk_id, mods | self._MOD_NOREPEAT, vk))
        if not ok:
            if previous:
                _pm, _pv = parse_hotkey_combo(previous)
                if _pv and bool(user32.RegisterHotKey(
                    None, hk_id, _pm | self._MOD_NOREPEAT, _pv,
                )):
                    self._global_hotkey_id = hk_id
            self._log.warning(
                f"{LOG_PREFIX} RegisterHotKey({combo}) misslyckades "
                f"— kanske upptagen av annan app"
            )
            return False, f"{combo} är upptagen av ett annat program."
        self._global_hotkey_id = hk_id
        self._quick_add_registered = combo
        self._ensure_hotkey_filter()
        return True, ""

    def _unregister_quick_add_hotkey(self) -> None:
        """Ta bort snabbinput-tangenten (”Stäng av” i dialogen)."""
        if sys.platform != "win32":
            return
        with suppress(Exception):
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self._QUICK_ADD_ID)
        self._global_hotkey_id = None
        self._quick_add_registered = None

    def _install_global_quick_add(self) -> None:
        """
        NY v7-fix41: GLOBAL snabbinput — Ctrl+Alt+N var som helst i Windows.

        RegisterHotKey (Win32) + QAbstractNativeEventFilter som fångar
        WM_HOTKEY (0x0312) i Qt:s meddelandepump — inget extra fönster
        behövs (viktigt med tanke på CreateWindowEx-storm-historiken!).
        Öppnar samma snabbinput-dialog som tray-menyn + visar widgeten.
        """
        if sys.platform != "win32":
            return
        enabled = True
        try:
            if hasattr(self.settings, "global_quick_add"):
                enabled = bool(self.settings.global_quick_add())
            elif hasattr(self.settings, "get"):
                enabled = bool(self.settings.get("global_quick_add", True))
        except Exception:
            enabled = True
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # Filtret först och ALLTID — så att en tangent som senare
            # registreras via menyn faktiskt lyssnas på.
            self._ensure_hotkey_filter()

            _qa_combo = "Ctrl+Alt+N"
            if enabled:
                # FIX v7-fix83: hotkey KONFIGURERBAR (settings
                # 'quick_add_hotkey', default 'Ctrl+Alt+N')
                _qa_combo = self._get_quick_add_hotkey_combo()
                if not parse_hotkey_combo(_qa_combo)[1]:
                    self._log.warning(
                        f"{LOG_PREFIX} ogiltig quick_add_hotkey "
                        f"'{_qa_combo}' — använder Ctrl+Alt+N"
                    )
                    _qa_combo = "Ctrl+Alt+N"
                _ok_qa, _why = self._register_quick_add_hotkey(_qa_combo)
                if not _ok_qa:
                    self._log.warning(
                        f"{LOG_PREFIX} snabbinput-tangenten {_qa_combo} "
                        f"inte aktiv ({_why}) — välj en annan via tray → "
                        f"⌨️ Snabbkommandon"
                    )
            else:
                self._log.info(
                    f"{LOG_PREFIX} Global snabbinput avstängd i settings"
                )

            # NY v7-fix68/69: push-to-show — konfigurerbar hotkey
            # (settings 'push_show_hotkey', default 'Ctrl+Alt+V').
            # Håll inne = fönstret över appar; släpp = tillbaka.
            self._push_hotkey_id = self._PUSH_SHOW_ID
            _combo = self._get_push_hotkey_combo()
            _mods, _vk = parse_hotkey_combo(_combo)
            if _vk:
                _ok_push = bool(user32.RegisterHotKey(
                    None, self._push_hotkey_id, _mods, _vk,
                ))
            else:
                _ok_push = False
            if _ok_push:
                self._log.info(
                    f"{LOG_PREFIX} Push-to-show aktiv: HÅLL INNE "
                    f"{_combo} = fönstret visas över appar; släpp = "
                    f"tillbaka på skrivbordet (v7-fix68/69)"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} RegisterHotKey({_combo}) misslyckades "
                    f"(ogiltig/upptagen) — push-to-show ej aktivt. "
                    f"Ändra via tray → '⌨️ Ändra Visa-över-hotkey...'"
                )

            with suppress(Exception):
                self._install_clip_task_hotkey()
            with suppress(Exception):
                self._install_top_toggle_hotkey()

            if self._global_hotkey_id is not None:
                self._log.info(
                    f"{LOG_PREFIX} Global snabbinput aktiv: {_qa_combo} "
                    f"öppnar ny uppgift VAR SOM HELST i Windows "
                    f"(v7-fix41/83)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _install_global_quick_add misslyckades: {e}",
                exc_info=True,
            )

    def _get_push_hotkey_combo(self) -> str:
        """NY v7-fix69: läs konfigurerad push-to-show-hotkey."""
        try:
            if hasattr(self.settings, "push_show_hotkey"):
                return self.settings.push_show_hotkey()
            return str(
                self.settings.get("push_show_hotkey", "Ctrl+Alt+V")
            )
        except Exception:
            return "Ctrl+Alt+V"

    def _get_quick_add_hotkey_combo(self) -> str:
        """
        NY v7-fix83: läs konfigurerad snabbinput-hotkey (ny uppgift).

        Default 'Ctrl+Alt+N' — ändras i tray → ⌨️ Snabbkommandon.
        """
        try:
            if hasattr(self.settings, "quick_add_hotkey"):
                return self.settings.quick_add_hotkey()
            return str(
                self.settings.get("quick_add_hotkey", "Ctrl+Alt+N")
            )
        except Exception:
            return "Ctrl+Alt+N"

    def _change_quick_add_hotkey_dialog(self) -> None:
        """
        Ändra snabbtangenten för NY UPPGIFT — man trycker bara tangenterna.

        Dialogen (ui/hotkey_dialog.py) kontrollerar direkt att kombinationen
        duger (minst två modifierare, inte reserverad av Windows, inte samma
        som Visa-över-tangenten). Sedan testregistreras den hos Windows; är
        den upptagen behålls den gamla. Spara → registreras och gäller
        direkt (ingen omstart). Widgetens interna genväg ('add_task')
        uppdateras till samma kombination.
        """
        try:
            from core.hotkey_combo import DEFAULT_QUICK_ADD
            from ui.hotkey_dialog import ask_hotkey

            _current = self._get_quick_add_hotkey_combo()
            _enabled = True
            with suppress(Exception):
                _enabled = bool(self.settings.global_quick_add())
            combo = ask_hotkey(
                "⌨️ Snabbtangent för ny uppgift",
                "Klicka i rutan och TRYCK den kombination du vill ha.\n"
                "Den öppnar rutan för ny uppgift var som helst i Windows,"
                " även när Ledgebord är dolt.\n\n"
                f"Nu: {_current if _enabled else 'avstängd'}",
                _current,
                DEFAULT_QUICK_ADD,
                taken=[self._get_push_hotkey_combo(), self._get_clip_task_combo(), self._get_top_toggle_combo()],
                allow_disable=True,
            )
            if combo is None:
                return
            if combo == "":
                self._unregister_quick_add_hotkey()
                if hasattr(self.settings, "set_global_quick_add"):
                    self.settings.set_global_quick_add(False)
                self._notify_hotkey("Snabbtangenten för ny uppgift är avstängd.")
                self._populate_tray_menu()
                self._log.info(
                    f"{LOG_PREFIX} Snabbinput-hotkey avstängd av användaren"
                )
                return
            ok, why = self._register_quick_add_hotkey(combo)
            if not ok:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None, "Kunde inte registrera",
                        f"{why}\nProva en annan kombination."
                        + (f"\n\nKvar sedan tidigare: {_current}"
                           if _enabled and self._global_hotkey_id is not None
                           else ""),
                    )
                return
            # Spara (settings + widgetens interna genväg)
            if hasattr(self.settings, "set_global_quick_add"):
                self.settings.set_global_quick_add(True)
            if hasattr(self.settings, "set_quick_add_hotkey"):
                self.settings.set_quick_add_hotkey(combo)
            if hasattr(self.settings, "set_shortcut"):
                self.settings.set_shortcut("add_task", combo)
            # Omregistrera widgetens QShortcuts med nya kombinationen
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_unregister_hotkeys"):
                            w._unregister_hotkeys()
                        if hasattr(w, "_register_hotkeys"):
                            w._register_hotkeys()
            self._notify_hotkey(
                f"✅ Snabbtangent för ny uppgift: {combo}\n"
                f"(gäller direkt, var som helst i Windows)"
            )
            self._populate_tray_menu()
            self._log.info(
                f"{LOG_PREFIX} Snabbinput-hotkey ändrad: "
                f"{_current} → {combo} (v7-fix83)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _change_quick_add_hotkey_dialog: {e}",
                exc_info=True,
            )

    def _notify_hotkey(self, text: str) -> None:
        """Liten bekräftelse i tray (om tray finns)."""
        if self._tray is not None:
            with suppress(Exception):
                self._tray.showMessage(
                    APP_NAME, text,
                    self._QSystemTrayIcon.MessageIcon.Information, 4000,
                )

    def _change_push_hotkey_dialog(self) -> None:
        """
        NY v7-fix69: tray-dialog för att ändra push-to-show-hotkey.

        Skriv t.ex. 'Ctrl+Alt+V', 'Ctrl+Shift+Space' eller 'Alt+F3'.
        Valideras + testregistreras innan den sparas.
        """
        try:
            if self._QInputDialog is None:
                return
            _current = self._get_push_hotkey_combo()
            text, ok = self._QInputDialog.getText(
                None,
                "⌨️ Visa-över-hotkey (push-to-show)",
                "Skriv din kombination:\n\n"
                "Modifierare: Ctrl, Alt, Shift, Win\n"
                "Tangent: A-Z, 0-9, F1-F12, Space, Enter, Tab\n\n"
                "Exempel: Ctrl+Alt+V  eller  Ctrl+Shift+Space\n"
                "(Håll inne tangenten = fönstret visas över appar)",
                text=_current,
            )
            if not ok or not text.strip():
                return
            combo = text.strip()
            mods, vk = parse_hotkey_combo(combo)
            if not vk:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Ogiltig kombination",
                        f"'{combo}' kunde inte tolkas.\n\n"
                        f"Format: Ctrl+Alt+V (modifierare + tangent).",
                    )
                return
            # Testregistrera den nya (kräver att gamla avregistreras först)
            import ctypes
            _u = ctypes.windll.user32
            _old_id = getattr(self, "_push_hotkey_id", None)
            if _old_id is not None:
                with suppress(Exception):
                    _u.UnregisterHotKey(None, _old_id)
            _ok = bool(_u.RegisterHotKey(None, 0xB42, mods, vk))
            if not _ok:
                # Registrera tillbaka den gamla
                if _old_id is not None:
                    _om, _ov = parse_hotkey_combo(_current)
                    if _ov:
                        with suppress(Exception):
                            _u.RegisterHotKey(None, 0xB42, _om, _ov)
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Hotkey upptagen",
                        f"'{combo}' används redan av ett annat program."
                        f"\nProva en annan kombination.",
                    )
                return
            # Spara
            if hasattr(self.settings, "set_push_show_hotkey"):
                self.settings.set_push_show_hotkey(combo)
            self._push_hotkey_id = 0xB42
            if self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ Visa-över-hotkey ändrad till: {combo}\n"
                    f"(håll inne = fönstret över appar)",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            self._log.info(
                f"{LOG_PREFIX} Push-to-show-hotkey ändrad: "
                f"{_current} → {combo} (v7-fix69)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _change_push_hotkey_dialog: {e}",
                exc_info=True,
            )

    def _push_show_press(self) -> None:
        """
        NY v7-fix68: Ctrl+Alt+V tryckt ned — visa fönstret ÖVER appar.

        Behind-läge: lyft fönstret överst (HWND_TOP bland toppfönster).
        Above-läge: lossa från Progman (bevara skärm-position) + lyft.
        Släpp detekteras av _push_show_poll (GetAsyncKeyState) →
        _push_show_release återfäster på skrivbordet.
        """
        try:
            if getattr(self, "_push_show_active", False):
                return  # Redan aktivt
            import ctypes
            from ctypes import wintypes as _wt
            _u = ctypes.windll.user32
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                hwnd = int(shell.winId())
                if not hwnd:
                    continue
                with suppress(Exception):  # dockat och gömt → glid fram och håll kvar
                    w._edge_dock_reveal()
                    w._edge_dock_pin(True)
                _prev = str(
                    getattr(shell, "_desktop_layer_mode", "normal")
                )
                shell._push_prev_mode = _prev
                if _prev == "above":
                    # Lossa från Progman + bevara skärm-position
                    _pre = _wt.RECT()
                    _u.GetWindowRect(hwnd, ctypes.byref(_pre))
                    _u.SetParent(hwnd, 0)
                    _u.SetWindowPos(
                        hwnd, 0, _pre.left, _pre.top, 0, 0,
                        0x0004 | 0x0010 | 0x0001,  # NOZORDER|NOACTIVATE|NOSIZE
                    )
                # FIX v7-fix75: TILLFÄLLIG TOPMOST — garanterat över
                # alla normala fönster (HWND_TOP räckte inte när t.ex.
                # Explorer låg över). NOTOPMOST vid release.
                _u.SetWindowPos(
                    hwnd, -1, 0, 0, 0, 0,
                    0x0040 | 0x0010 | 0x0001 | 0x0002,
                )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = "_push"
                self._log.info(
                    f"{LOG_PREFIX} PUSH-TO-SHOW: {wid!r} visas över "
                    f"appar (var: {_prev}) — släpp Ctrl+Alt+V för "
                    f"tillbaka (v7-fix68)"
                )
            self._push_show_active = True
            # Poll-timer: detektera släpp (V-knappen)
            _pt = getattr(self, "_push_poll_timer", None)
            if _pt is None:
                _pt = self._QTimer()
                _pt.setInterval(120)  # 120 ms
                _pt.timeout.connect(self._push_show_poll)
                self._push_poll_timer = _pt
            _pt.start()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _push_show_press: {e}", exc_info=True
            )

    def _push_show_poll(self) -> None:
        """NY v7-fix68: polla V-knappen — släppt? → release."""
        try:
            import ctypes
            _still_down = bool(
                ctypes.windll.user32.GetAsyncKeyState(0x56) & 0x8000
            )
            if _still_down:
                return
            _pt = getattr(self, "_push_poll_timer", None)
            if _pt is not None:
                with suppress(Exception):
                    _pt.stop()
            self._push_show_release()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _push_show_poll: {e}")

    def _push_show_release(self) -> None:
        """
        NY v7-fix68: Ctrl+Alt+V släppt — återfäst på skrivbordet.
        """
        try:
            import ctypes
            _u = ctypes.windll.user32
            # FIX v7-fix75: ta bort TOPMOST först
            with self._widget_lock:
                _shells_r = [
                    getattr(w, "_shell", None)
                    for w in self._widgets.values()
                ]
            for _sh_r in _shells_r:
                if _sh_r is None:
                    continue
                with suppress(Exception):
                    _hw = int(_sh_r.winId())
                    if _hw:
                        _u.SetWindowPos(
                            _hw, -2, 0, 0, 0, 0,
                            0x0010 | 0x0001 | 0x0002,
                        )  # HWND_NOTOPMOST
            desktop_status = self._imports.get("desktop")
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                with suppress(Exception):
                    w._edge_dock_pin(False)  # dockat fönster får gömma sig igen
                _prev = str(
                    getattr(shell, "_push_prev_mode", "normal")
                )
                hwnd = int(shell.winId())
                if _prev in ("behind", "above", "top"):
                    # FIX v7-fix70: kör HELA kedjan (behind → above →
                    # toppfönster) i stället för endast en väg —
                    # garanterar en fungerande återfästning
                    shell._desktop_layer_mode = None
                    self._apply_desktop_shell(shell, wid)
                else:
                    # normal: låt vara (vanligt fönster, rör ej z-ordning)
                    shell._desktop_layer_mode = "normal"
                self._log.info(
                    f"{LOG_PREFIX} PUSH-TO-SHOW: {wid!r} tillbaka "
                    f"({_prev}) (v7-fix68)"
                )
            self._push_show_active = False
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _push_show_release: {e}", exc_info=True
            )

    def _any_window_not_visible(self) -> bool:
        """Finns något fönster (skal) som inte är synligt just nu?"""
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            if not widgets:
                return True
            for w in widgets:
                target = getattr(w, "_shell", None) or w
                if not target.isVisible():
                    return True
            return False
        except Exception:
            return True

    def _global_quick_add(self) -> None:
        """
        NY v7-fix41: global snabbinput triggad (köad på GUI-tråden).

        Visar befintligt fönster (enbart-läge) + öppnar snabbinput-dialogen.
        """
        try:
            # Visa bara fönstret om det FAKTISKT är gömt/minimerat — att köra om skrivbordslagret
            # på ett synligt fönster kan flytta det. Ligger det i tray lämnas det där.
            if self._single_window_enabled() and not self._is_hidden_to_tray() and self._any_window_not_visible():
                self._show_existing_window()
            self._tray_quick_add_task()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _global_quick_add: {e}")

    def _uninstall_global_quick_add(self) -> None:
        """NY v7-fix41: avregistrera global hotkey vid nedstängning."""
        hk_id = getattr(self, "_global_hotkey_id", None)
        if hk_id is not None:
            try:
                import ctypes
                ctypes.windll.user32.UnregisterHotKey(None, hk_id)
                self._log.info(f"{LOG_PREFIX} Global hotkey avregistrerad")
            except Exception:
                pass
        # NY v7-fix68: push-to-show-hotkey
        _phk = getattr(self, "_push_hotkey_id", None)
        if _phk is not None:
            with suppress(Exception):
                import ctypes as _ct
                _ct.windll.user32.UnregisterHotKey(None, _phk)
                self._log.info(
                    f"{LOG_PREFIX} Push-to-show-hotkey avregistrerad"
                )
            self._push_hotkey_id = None
        with suppress(Exception):
            self._unregister_clip_task_hotkey()
        with suppress(Exception):
            self._unregister_top_toggle_hotkey()
        _pt = getattr(self, "_push_poll_timer", None)
        if _pt is not None:
            with suppress(Exception):
                _pt.stop()
        _f = getattr(self, "_global_hotkey_filter", None)
        if _f is not None and self._app is not None:
            with suppress(Exception):
                self._app.removeNativeEventFilter(_f)
        self._global_hotkey_filter = None
        self._global_hotkey_id = None
