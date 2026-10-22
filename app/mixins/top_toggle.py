# -*- coding: utf-8 -*-
"""Global snabbtangent som slår "Alltid överst" på/av (fönstret ligger över alla andra appar)."""

from __future__ import annotations

import sys
from contextlib import suppress

from app.config import parse_hotkey_combo
from app.constants import LOG_PREFIX

DEFAULT_TOP_TOGGLE = "Ctrl+Alt+T"
TOP_TOGGLE_HOTKEY_ID = 0xB44


class TopToggleMixin:
    """Ctrl+Alt+T (kan ändras): växlar mellan "Alltid överst" och det läge du hade förut."""

    _TOP_TOGGLE_ID = TOP_TOGGLE_HOTKEY_ID
    _top_toggle_registered = None   # kombinationen som är registrerad just nu

    # ------------------------------------------------------------------
    # Inställningar
    # ------------------------------------------------------------------
    def _get_top_toggle_combo(self) -> str:
        try:
            return str(self.settings.top_toggle_hotkey())
        except Exception:
            return DEFAULT_TOP_TOGGLE

    def _top_toggle_enabled(self) -> bool:
        try:
            return bool(self.settings.top_toggle_enabled())
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Själva växlingen (fungerar på alla system — även från tray-menyn)
    # ------------------------------------------------------------------
    def _toggle_always_on_top(self) -> str:
        """
        Slå "Alltid överst" på/av. På → läget sparas först så "av" går tillbaka till det.
        Returnerar det nya läget (``top`` eller det förra).
        """
        try:
            cur = self._desktop_mode()
            if cur == "top":
                prev = "behind"
                with suppress(Exception):
                    p = str(self.settings.top_toggle_prev_mode())
                    prev = p if p in ("above", "behind") else "behind"
                new = prev
            else:
                with suppress(Exception):
                    self.settings.set_top_toggle_prev_mode(cur if cur in ("above", "behind") else "behind")
                new = "top"
            self._set_desktop_mode(new)
            self._log.info(f"{LOG_PREFIX} Alltid överst: {cur} → {new}")
            if new == "top":
                self._notify_hotkey("Visa över andra appar: PÅ — fönstret ligger över alla andra appar.")
            else:
                self._notify_hotkey("Visa över andra appar: AV — fönstret ligger på skrivbordet.")
            return new
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_always_on_top: {e}", exc_info=True)
            return ""

    def _top_menu_label(self) -> str:
        """Texten på kryssrutan (tray + högerklick); snabbtangenten visas om den är på."""
        label = "Visa över andra appar"
        with suppress(Exception):
            if sys.platform == "win32" and self._top_toggle_enabled():
                label += f"  ({self._get_top_toggle_combo()})"
        return label

    def _set_show_over_apps(self, on: bool) -> None:
        """Kryssrutan 'Visa över andra appar': på = alltid överst, av = på skrivbordet."""
        try:
            if (self._desktop_mode() == "top") != bool(on):
                self._toggle_always_on_top()
            else:
                self._populate_tray_menu()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _set_show_over_apps: {e}", exc_info=True)

    def _top_toggle_press(self) -> None:
        """Snabbtangenten trycktes (GUI-tråden)."""
        self._toggle_always_on_top()

    # ------------------------------------------------------------------
    # Registrering (Windows)
    # ------------------------------------------------------------------
    def _install_top_toggle_hotkey(self) -> None:
        """Registrera tangenten vid start (efter att WM_HOTKEY-filtret finns)."""
        if sys.platform != "win32":
            return
        if not self._top_toggle_enabled():
            self._log.info(f"{LOG_PREFIX} 'Alltid överst'-tangenten är avstängd i inställningarna")
            return
        combo = self._get_top_toggle_combo()
        ok, why = self._register_top_toggle_hotkey(combo)
        if not ok:
            self._log.warning(
                f"{LOG_PREFIX} snabbtangenten för Alltid överst ({combo}) inte aktiv: {why} — "
                f"välj en annan via tray → ⌨️ Snabbkommandon"
            )
        else:
            self._log.info(f"{LOG_PREFIX} Alltid överst-tangent aktiv: {combo}")

    def _register_top_toggle_hotkey(self, combo: str) -> "tuple[bool, str]":
        if sys.platform != "win32":
            return False, "Globala snabbtangenter finns bara i Windows."
        mods, vk = parse_hotkey_combo(combo)
        if not vk:
            return False, f"'{combo}' kunde inte tolkas."
        import ctypes
        user32 = ctypes.windll.user32
        previous = self._top_toggle_registered
        with suppress(Exception):
            user32.UnregisterHotKey(None, self._TOP_TOGGLE_ID)
        self._top_toggle_registered = None
        if not bool(user32.RegisterHotKey(None, self._TOP_TOGGLE_ID, mods | 0x4000, vk)):  # MOD_NOREPEAT
            if previous:
                _pm, _pv = parse_hotkey_combo(previous)
                if _pv and bool(user32.RegisterHotKey(None, self._TOP_TOGGLE_ID, _pm | 0x4000, _pv)):
                    self._top_toggle_registered = previous
            return False, f"{combo} är upptagen av ett annat program."
        self._top_toggle_registered = combo
        self._ensure_hotkey_filter()
        return True, ""

    def _unregister_top_toggle_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        with suppress(Exception):
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self._TOP_TOGGLE_ID)
        self._top_toggle_registered = None

    def _change_top_toggle_hotkey_dialog(self) -> None:
        """Ändra (eller stäng av) snabbtangenten för "Alltid överst"."""
        try:
            from ui.hotkey_dialog import ask_hotkey
            current = self._get_top_toggle_combo()
            enabled = self._top_toggle_enabled()
            combo = ask_hotkey(
                "📌 Snabbtangent: Alltid överst",
                "Tryck kombinationen för att lägga Ledgebord över ALLA andra appar — tryck igen för\n"
                "att lägga tillbaka det på skrivbordet. Fungerar var som helst i Windows.\n\n"
                f"Nu: {current if enabled else 'avstängd'}",
                current,
                DEFAULT_TOP_TOGGLE,
                taken=[self._get_quick_add_hotkey_combo(), self._get_push_hotkey_combo(),
                       self._get_clip_task_combo()],
                allow_disable=True,
            )
            if combo is None:
                return
            if combo == "":
                self._unregister_top_toggle_hotkey()
                self.settings.set_top_toggle_enabled(False)
                self._notify_hotkey("Snabbtangenten för Alltid överst är avstängd.")
                self._populate_tray_menu()
                return
            ok, why = self._register_top_toggle_hotkey(combo)
            if not ok:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None, "Kunde inte registrera", f"{why}\nProva en annan kombination.",
                    )
                return
            self.settings.set_top_toggle_enabled(True)
            self.settings.set_top_toggle_hotkey(combo)
            self._notify_hotkey(f"✅ Alltid överst: {combo}\n(gäller direkt)")
            self._populate_tray_menu()
            self._log.info(f"{LOG_PREFIX} Alltid överst-tangent ändrad: {current} → {combo}")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _change_top_toggle_hotkey_dialog: {e}", exc_info=True)
