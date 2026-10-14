# -*- coding: utf-8 -*-
"""Globala snabbtangenter (snabbtillägg och push-to-show)."""

from __future__ import annotations

import sys
from contextlib import suppress

from app.config import parse_hotkey_combo
from app.constants import APP_NAME, LOG_PREFIX


class HotkeysMixin:
    """Globala snabbtangenter (snabbtillägg och push-to-show)."""

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
        try:
            if hasattr(self.settings, "global_quick_add"):
                if not self.settings.global_quick_add():
                    self._log.info(
                        f"{LOG_PREFIX} Global snabbinput avstängd i settings"
                    )
                    return
            elif hasattr(self.settings, "get") and not self.settings.get(
                "global_quick_add", True
            ):
                return
        except Exception:
            pass
        try:
            import ctypes
            from PySide6.QtCore import QAbstractNativeEventFilter

            user32 = ctypes.windll.user32
            self._global_hotkey_id = 0xB41  # unikt hotkey-id
            # FIX v7-fix83: hotkey NUMERA KONFIGURERBAR (settings
            # 'quick_add_hotkey', default 'Ctrl+Alt+N') — ändras i tray →
            # ⌨️ Snabbkommandon → Ny uppgift (registreras om direkt).
            _qa_combo = self._get_quick_add_hotkey_combo()
            _qa_mods, _qa_vk = parse_hotkey_combo(_qa_combo)
            if not _qa_vk:
                # Ogiltig sparad kombination → fallback default
                self._log.warning(
                    f"{LOG_PREFIX} ogiltig quick_add_hotkey '{_qa_combo}' "
                    f"— använder Ctrl+Alt+N"
                )
                _qa_combo = "Ctrl+Alt+N"
                _qa_mods, _qa_vk = parse_hotkey_combo(_qa_combo)
            ok = bool(user32.RegisterHotKey(
                None, self._global_hotkey_id, _qa_mods, _qa_vk,
            ))
            if not ok:
                self._log.warning(
                    f"{LOG_PREFIX} RegisterHotKey({_qa_combo}) misslyckades "
                    f"— kanske upptagen av annan app"
                )
                return
            ctrl = self

            class _HotkeyFilter(QAbstractNativeEventFilter):
                """Fångar WM_HOTKEY i Qt:s meddelandepump (GUI-tråd)."""

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
                        if (
                            m_.message == 0x0312
                            and (m_.wParam & 0xFFFF) == ctrl._global_hotkey_id
                        ):
                            ctrl._log.info(
                                f"{LOG_PREFIX} Global snabbinput-hotkey "
                                f"triggad ({ctrl._get_quick_add_hotkey_combo()}, "
                                f"var som helst i Windows)"
                            )
                            ctrl._QTimer.singleShot(
                                0, ctrl._global_quick_add
                            )
                            return True
                        # NY v7-fix68: push-to-show (Ctrl+Alt+V intryckt)
                        elif (
                            m_.message == 0x0312
                            and (m_.wParam & 0xFFFF)
                            == getattr(ctrl, "_push_hotkey_id", 0)
                        ):
                            ctrl._QTimer.singleShot(
                                0, ctrl._push_show_press
                            )
                            return True
                    except Exception:
                        pass
                    return False

            # NY v7-fix68/69: push-to-show — konfigurerbar hotkey
            # (settings 'push_show_hotkey', default 'Ctrl+Alt+V').
            # Håll inne = fönstret över appar; släpp = tillbaka.
            self._push_hotkey_id = 0xB42  # unikt id
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

            self._global_hotkey_filter = _HotkeyFilter()
            self._app.installNativeEventFilter(self._global_hotkey_filter)
            self._log.info(
                f"{LOG_PREFIX} Global snabbinput aktiv: {_qa_combo} öppnar "
                f"ny uppgift VAR SOM HELST i Windows (v7-fix41/83)"
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
        NY v7-fix83: tray-dialog för att ändra snabbinput-hotkey.

        Skriv t.ex. 'Ctrl+Alt+N', 'Ctrl+Shift+N' eller 'Alt+F4'.
        Valideras + testregistreras innan den sparas; koll även mot
        konflikt med Visa-över-hotkey:en. Widgetens interna genväg
        (shortcuts 'add_task') uppdateras till samma kombination.
        """
        try:
            if self._QInputDialog is None:
                return
            _current = self._get_quick_add_hotkey_combo()
            text, ok = self._QInputDialog.getText(
                None,
                "⌨️ Snabbinput-hotkey (ny uppgift)",
                "Skriv din kombination:\n\n"
                "Modifierare: Ctrl, Alt, Shift, Win\n"
                "Tangent: A-Z, 0-9, F1-F12, Space, Enter, Tab\n\n"
                "Exempel: Ctrl+Alt+N  eller  Ctrl+Shift+A\n"
                "(öppnar snabbinput för ny uppgift VAR SOM HELST)",
                text=_current,
            )
            if not ok or not text.strip():
                return
            combo = text.strip()
            # Konflikt med Visa-över-hotkey?
            if combo.lower() == self._get_push_hotkey_combo().lower():
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Konflikt",
                        f"'{combo}' används redan som Visa-över-hotkey.\n"
                        f"Välj en annan kombination.",
                    )
                return
            mods, vk = parse_hotkey_combo(combo)
            if not vk:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Ogiltig kombination",
                        f"'{combo}' kunde inte tolkas.\n\n"
                        f"Format: Ctrl+Alt+N (modifierare + tangent).",
                    )
                return
            # Testregistrera (avregistrera gammal först — Windows tillåter
            # bara en registrering per kombination)
            import ctypes
            _u = ctypes.windll.user32
            _old_id = getattr(self, "_global_hotkey_id", None)
            if _old_id is not None:
                with suppress(Exception):
                    _u.UnregisterHotKey(None, _old_id)
            _ok = bool(_u.RegisterHotKey(None, 0xB41, mods, vk))
            if not _ok:
                # Registrera tillbaka den gamla
                if _old_id is not None:
                    _om, _ov = parse_hotkey_combo(_current)
                    if _ov:
                        with suppress(Exception):
                            _u.RegisterHotKey(None, 0xB41, _om, _ov)
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Kunde inte registrera",
                        f"'{combo}' är upptagen av ett annat program.\n"
                        f"Prova en annan kombination.",
                    )
                return
            # Spara (settings + widgetens interna genväg)
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
            self._global_hotkey_id = 0xB41
            if self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ Snabbinput-hotkey ändrad till: {combo}\n"
                    f"(ny uppgift var som helst i Windows)",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    4000,
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
                _prev = str(
                    getattr(shell, "_push_prev_mode", "normal")
                )
                hwnd = int(shell.winId())
                if _prev in ("behind", "above"):
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

    def _global_quick_add(self) -> None:
        """
        NY v7-fix41: global snabbinput triggad (köad på GUI-tråden).

        Visar befintligt fönster (enbart-läge) + öppnar snabbinput-dialogen.
        """
        try:
            if self._single_window_enabled():
                self._show_existing_window()
            self._tray_quick_add_task()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _global_quick_add: {e}")

    def _uninstall_global_quick_add(self) -> None:
        """NY v7-fix41: avregistrera global hotkey vid nedstängning."""
        hk_id = getattr(self, "_global_hotkey_id", None)
        if hk_id is None:
            return
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
