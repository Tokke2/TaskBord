# -*- coding: utf-8 -*-
"""Global snabbtangent "Lägg till från urklipp": markerad text i valfritt program blir en uppgift."""

from __future__ import annotations

import sys
from contextlib import suppress

from app.config import parse_hotkey_combo
from app.constants import LOG_PREFIX
from core import clip_capture as _cc


class ClipTaskMixin:
    """Ctrl+Alt+K (kan ändras): kopierar markeringen och skapar en uppgift av den."""

    _CLIP_TASK_ID = _cc.HOTKEY_ID
    _clip_task_registered = None   # kombinationen som är registrerad just nu
    _clip_capture = None

    # ------------------------------------------------------------------
    # Inställningar
    # ------------------------------------------------------------------
    def _get_clip_task_combo(self) -> str:
        try:
            return str(self.settings.clip_task_hotkey())
        except Exception:
            return _cc.DEFAULT_CLIP_TASK

    def _clip_task_enabled(self) -> bool:
        try:
            return bool(self.settings.clip_task_enabled())
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Registrering
    # ------------------------------------------------------------------
    def _install_clip_task_hotkey(self) -> None:
        """Registrera tangenten vid start (efter att WM_HOTKEY-filtret finns)."""
        if sys.platform != "win32":
            return
        if not self._clip_task_enabled():
            self._log.info(f"{LOG_PREFIX} 'Lägg till från urklipp' är avstängd i inställningarna")
            return
        combo = self._get_clip_task_combo()
        ok, why = self._register_clip_task_hotkey(combo)
        if not ok:
            self._log.warning(
                f"{LOG_PREFIX} snabbtangenten för urklipp ({combo}) inte aktiv: {why} — "
                f"välj en annan via tray → ⌨️ Snabbkommandon"
            )
        else:
            self._log.info(f"{LOG_PREFIX} Lägg till från urklipp aktiv: {combo}")

    def _register_clip_task_hotkey(self, combo: str) -> "tuple[bool, str]":
        if sys.platform != "win32":
            return False, "Globala snabbtangenter finns bara i Windows."
        mods, vk = parse_hotkey_combo(combo)
        if not vk:
            return False, f"'{combo}' kunde inte tolkas."
        import ctypes
        user32 = ctypes.windll.user32
        previous = self._clip_task_registered
        with suppress(Exception):
            user32.UnregisterHotKey(None, self._CLIP_TASK_ID)
        self._clip_task_registered = None
        if not bool(user32.RegisterHotKey(None, self._CLIP_TASK_ID, mods | 0x4000, vk)):
            if previous:
                _pm, _pv = parse_hotkey_combo(previous)
                if _pv and bool(user32.RegisterHotKey(None, self._CLIP_TASK_ID, _pm | 0x4000, _pv)):
                    self._clip_task_registered = previous
            return False, f"{combo} är upptagen av ett annat program."
        self._clip_task_registered = combo
        self._ensure_hotkey_filter()
        return True, ""

    def _unregister_clip_task_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        with suppress(Exception):
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self._CLIP_TASK_ID)
        self._clip_task_registered = None

    def _change_clip_task_hotkey_dialog(self) -> None:
        """Ändra (eller stäng av) snabbtangenten för 'Lägg till från urklipp'."""
        try:
            from ui.hotkey_dialog import ask_hotkey
            current = self._get_clip_task_combo()
            enabled = self._clip_task_enabled()
            combo = ask_hotkey(
                "📋 Snabbtangent: lägg till från urklipp",
                "Markera text i VILKET program som helst och tryck kombinationen — texten blir en\n"
                "uppgift direkt (första raden = rubrik, resten = anteckning). Är inget markerat\n"
                "används det som ligger i urklippet.\n\n"
                f"Nu: {current if enabled else 'avstängd'}",
                current,
                _cc.DEFAULT_CLIP_TASK,
                taken=[self._get_quick_add_hotkey_combo(), self._get_push_hotkey_combo()],
                allow_disable=True,
            )
            if combo is None:
                return
            if combo == "":
                self._unregister_clip_task_hotkey()
                self.settings.set_clip_task_enabled(False)
                self._notify_hotkey("Snabbtangenten för urklipp är avstängd.")
                self._populate_tray_menu()
                return
            ok, why = self._register_clip_task_hotkey(combo)
            if not ok:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None, "Kunde inte registrera",
                        f"{why}\nProva en annan kombination.",
                    )
                return
            self.settings.set_clip_task_enabled(True)
            self.settings.set_clip_task_hotkey(combo)
            self._notify_hotkey(f"✅ Lägg till från urklipp: {combo}\n(gäller direkt)")
            self._populate_tray_menu()
            self._log.info(f"{LOG_PREFIX} Urklipps-snabbtangent ändrad: {current} → {combo}")
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _change_clip_task_hotkey_dialog: {e}", exc_info=True
            )

    # ------------------------------------------------------------------
    # Själva fångsten
    # ------------------------------------------------------------------
    def _clip_task_press(self) -> None:
        """Snabbtangenten trycktes (GUI-tråden): kopiera markeringen och skapa uppgiften."""
        try:
            cap = self._clip_capture
            if cap is None:
                user32 = _cc.load_user32()
                if user32 is None:
                    return
                from PySide6.QtCore import QMimeData
                from PySide6.QtGui import QGuiApplication

                def _cb():
                    return QGuiApplication.clipboard()

                def get_state():
                    md = _cb().mimeData()
                    if md is None:
                        return None
                    clone = QMimeData()
                    for fmt in md.formats():
                        clone.setData(fmt, md.data(fmt))
                    return clone

                cap = _cc.ClipCapture(
                    user32,
                    get_text=lambda: _cb().text(),
                    get_state=get_state,
                    set_state=lambda st: _cb().setMimeData(st),
                    schedule=lambda ms, fn: self._QTimer.singleShot(ms, fn),
                    done=self._clip_task_done,
                )
                self._clip_capture = cap
            if not cap.start():
                self._log.info(f"{LOG_PREFIX} urklipps-fångst pågår redan — ignorerar")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _clip_task_press: {e}", exc_info=True)

    def _clip_task_from_clipboard(self) -> None:
        """Tray-menyn: ny uppgift av det som redan ligger i urklippet (ingen Ctrl+C skickas)."""
        try:
            from PySide6.QtGui import QGuiApplication
            text = QGuiApplication.clipboard().text()
            self._clip_task_done(text, "urklipp")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _clip_task_from_clipboard: {e}", exc_info=True)

    def _clip_task_done(self, text: str, source: str) -> None:
        """Skapa uppgiften av ``text`` och visa en kvittens i tray."""
        title, note = _cc.split_text(text)
        if not title:
            self._clip_balloon(
                "📋 Inget att lägga till",
                "Ingen markerad text, och urklippet är tomt.",
            )
            self._log.info(f"{LOG_PREFIX} urklipps-uppgift: ingen text (source={source!r})")
            return
        if self.store is None or not hasattr(self.store, "add_task"):
            return
        new_id = self.store.add_task(title)
        if not new_id:
            self._clip_balloon("⚠️ Kunde inte skapa uppgiften", title[:80])
            return
        if note:
            with suppress(Exception):
                self.store.set_task_metadata(new_id, "note", note)
        self._log.info(
            f"{LOG_PREFIX} uppgift skapad från {source} id={new_id!r} titel={title[:30]!r}"
        )
        with suppress(Exception):
            self._update_tray_tooltip()
        what = "från markeringen" if source == "markering" else "från urklippet"
        self._clip_balloon(
            f"✅ Uppgift skapad ({what})",
            title if len(title) <= 80 else title[:79] + "…",
        )

    def _clip_balloon(self, title: str, text: str) -> None:
        if self._tray is None:
            return
        with suppress(Exception):
            self._tray.showMessage(
                title, text, self._QSystemTrayIcon.MessageIcon.Information, 3500
            )
