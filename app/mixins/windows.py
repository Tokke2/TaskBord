# -*- coding: utf-8 -*-
"""Widget-fönster: skapa, visa, storlek, tema och synk med inställningar."""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import List, Optional, Tuple

from app.config import error_boundary
from app.constants import APP_NAME, LOG_FILE, LOG_PREFIX
from app.errors import _format_compact_traceback, show_error_dialog


class WindowsMixin:
    """Widget-fönster: skapa, visa, storlek, tema och synk med inställningar."""

    def _populate_windows(self) -> None:
        """
        Initiera/synka ALLA widgets baserat på settings.window_configs().
        Befintliga widgets behåller sin state (position, storlek, hotkeys).

        NY v6.4.1 v7: Steg-for-steg loggning sa vi ser VAR det kraschar.
        Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det".
        """
        self._log.info(f"{LOG_PREFIX} === _populate_windows START ===")
        # FIX 2026-09-24: reentrancy-skydd (populate → show → move → signal → populate)
        import traceback as _pbtb
        _pst = _pbtb.extract_stack(limit=4)[:-1]
        _pcall = " ← ".join(
            f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
            for f in _pst[-2:]
        )
        # FIX 2026-09-25 v7-fix7: Hard reentrancy + cooldown mot populate-spam
        # Symptomet i loggen: 25+ anrop / 100 ms → 100-tals fönster-försök / sekund.
        # Orsak: windows_updated signal triggas rekursivt (moveEvent → save → signal → populate → show → moveEvent).
        # Skydd:
        #   1. _populate_in_progress — return direkt om populate redan kör
        #   2. _populate_last_ts + _populate_calls_in_window —> 3 anrop / 500 ms = SPAM
        #      return +_DEBUG-log med stack-frame (så vi ser VEM som spammar)
        import time as _t_pop
        _now = _t_pop.monotonic()
        _last = getattr(self, "_populate_last_ts", 0.0)
        _cnt = getattr(self, "_populate_calls_in_window", 0)
        if (_now - _last) > 0.5:
            # Nytt fönster — återställ räknare
            self._populate_calls_in_window = 1
            self._populate_last_ts = _now
        else:
            _cnt += 1
            self._populate_calls_in_window = _cnt
            self._populate_last_ts = _now
            if _cnt > 3:
                self._log.warning(
                    f"{LOG_PREFIX} _populate_windows SPAM-SKYDD: {_cnt} anrop "
                    f"sista 500 ms — return (kallad från {_pcall})"
                )
                return
        if getattr(self, "_populate_in_progress", False):
            self._log.debug(
                f"{LOG_PREFIX} _populate_windows: redan igång — hoppar över "
                f"(kallad från {_pcall})"
            )
            return
        self._log.info(f"{LOG_PREFIX} _populate_windows ORSAK: {_pcall}")
        self._populate_in_progress = True
        widget_status = self._imports.get("widget")
        if not widget_status or not widget_status.ok:
            self._log.error(
                f"{LOG_PREFIX} Widget-modul EJ TILLGANGLIG — hoppar over populate! "
                f"widget_status={widget_status}"
            )
            self._populate_in_progress = False
            return
        TodoWidget = widget_status.instance["TodoWidget"]
        self._log.info(f"{LOG_PREFIX} TodoWidget class: {TodoWidget}")

        try:
            with self._widget_lock:
                configs = (
                    self.settings.window_configs()
                    if hasattr(self.settings, "window_configs")
                    else []
                )
                self._log.info(
                    f"{LOG_PREFIX} _populate_windows: {len(configs)} "
                    f"window_configs fran settings: "
                    f"{[c.get('id') for c in configs if c.get('id')]}"
                )
                # NY v7-fix40: enbart-läge — visa MAX ett fönster
                if self._single_window_enabled() and len(configs) > 1:
                    _keep = next(
                        (c for c in configs if c.get("id") == "default"),
                        configs[0],
                    )
                    _skipped = [c.get("id") for c in configs if c is not _keep]
                    configs = [_keep]
                    self._log.info(
                        f"{LOG_PREFIX} enbart-ett-fönster-läge: visar "
                        f"{_keep.get('id')!r}, hoppar över {_skipped} "
                        f"(v7-fix40)"
                    )
                primary = self._app.primaryScreen() if self._app else None
                self._log.info(
                    f"{LOG_PREFIX} primary screen: {primary}, "
                    f"QApplication: {self._app}"
                )

                for conf in configs:
                    wid = conf.get("id")
                    if not wid:
                        self._log.warning(f"{LOG_PREFIX} config utan id: {conf}")
                        continue
                    # FIX 2026-09-23: skapa aldrig widget för interna __*-id
                    if str(wid).startswith("__"):
                        self._log.warning(
                            f"{LOG_PREFIX} hoppar över internt-id {wid!r}"
                        )
                        continue
                    if wid in self._widgets:
                        self._log.debug(f"{LOG_PREFIX} widget {wid!r} finns redan, skip")
                        continue
                    self._log.info(
                        f"{LOG_PREFIX} === Skapar widget {wid!r} ==="
                    )
                    # NY v7: Wrappa i BADE error_boundary OCH en extra try/except
                    # som loggar VARJE steg sa vi kan se exakt var det kraschar.
                    try:
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 1/4 — skapar "
                            f"TodoWidget(primary, store, settings, win_id={wid!r})"
                        )
                        # FIX v7-fix27: SKAL-MÖNSTER — vanligt QWidget som
                        # fönster (bevisat funka!), TodoWidget som BARN.
                        _QW = self._get_qt_class("QWidget")
                        if _QW is not None:
                            _shell = _QW()
                            _shell.setWindowTitle("TaskBord")
                            # v7-fix61: ikonläge — tillåt ikon-storlek
                            _shell.setMinimumSize(150, 200)
                            # NY v7-fix46: positionera SKALET från config!
                            # Tidigare positionerades bara BARN-widgeten —
                            # skalet fick Windows cascade-position (slump,
                            # ofta fel skärm) → "fönstret syns inte".
                            # NY v7-fix47: x/y < 0 = centrera (första start).
                            with suppress(Exception):
                                _gx = int(conf.get("x", -1))
                                _gy = int(conf.get("y", -1))
                                _gw = int(conf.get("w", 340) or 340)
                                _gh = int(conf.get("h", 648) or 648)
                                # v7-fix48: centrera vid sentinel (-1) ELLER
                                # om positionen är utanför ALLA skärmar
                                # (sparad skräpposition från koordinat-buggen)
                                _on_screen = False
                                for _sc in (self._app.screens() if self._app else []):
                                    if _sc.geometry().contains(_gx, _gy):
                                        _on_screen = True
                                        break
                                if _gx == -1 or _gy == -1 or not _on_screen:
                                    if primary is not None:
                                        _sg = primary.availableGeometry()
                                        _gx = _sg.x() + (_sg.width() - _gw) // 2
                                        _gy = _sg.y() + (_sg.height() - _gh) // 2
                                        self._log.info(
                                            f"{LOG_PREFIX} Fönster {wid!r}: "
                                            f"FÖRSTA START/OGILTIG POS → "
                                            f"centrerad ({_gx},{_gy}) "
                                            f"{_gw}x{_gh} (v7-fix47/48)"
                                        )
                                _shell.setGeometry(_gx, _gy, _gw, _gh)
                            w = TodoWidget(
                                primary, self.store, self.settings,
                                win_id=wid, parent=_shell,
                            )
                            from PySide6.QtWidgets import (
                                QVBoxLayout as _QVL,
                            )
                            _lay = _QVL(_shell)
                            _lay.setContentsMargins(0, 0, 0, 0)
                            _lay.addWidget(w)
                            w._shell = _shell
                            # NY v7-fix46: spara skal-geometrin direkt —
                            # rättar ev. (0,0)-skräp som barnets tidiga
                            # moveEvent hann skriva under konstruktorn
                            with suppress(Exception):
                                if hasattr(self.settings, "update_window_geometry"):
                                    self.settings.update_window_geometry(
                                        wid,
                                        _shell.x(), _shell.y(),
                                        _shell.width(), _shell.height(),
                                    )
                        else:
                            w = TodoWidget(
                                primary, self.store, self.settings, win_id=wid,
                            )
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 2/4 — TodoWidget "
                            f"skapad utan krasch"
                        )
                        if self._config.force_show_widget:
                            w._force_show = True
                            self._log.info(
                                f"{LOG_PREFIX} Widget {wid!r}: force-show aktiverat"
                            )
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 3/4 — show()"
                        )
                        _shell_ref = getattr(w, "_shell", None)
                        if _shell_ref is not None:
                            # FIX v7-fix32+38: FULLSTÄNDIG desktop-shell —
                            # Rickard: "win+D ska ej funka, ska alltid vara
                            # synlig på skrivbordet, INTE över andra fönster"
                            # + "transparent så ej ikoner döljs"
                            #
                            # NY v7-fix38: frameless + genomskinligt glas-skal.
                            # MÅSTE ske FÖRE show() (flaggor sätts innan det
                            # nativa fönstret skapas — inget riskfyllt byte
                            # av fönsterklass efteråt).
                            self._apply_shell_appearance(_shell_ref, wid)
                            #
                            # 1. Desktop-lager (above/behind) — Win+D-säkert
                            # 2. WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW
                            # 3. nativeEvent blockerar SC_MINIMIZE (Win+D)
                            # 4. Timer underhåller lagret var 30:e sek
                            _shell_ref.show()
                            self._apply_desktop_shell(_shell_ref, wid)
                            # NY v7-fix38: auto-fallback om det genomskinliga
                            # skalet inte kunde skapas (CreateWindowEx-fel)
                            self._schedule_shell_native_check(_shell_ref, wid)
                        else:
                            w.show()
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 4/4 — registrerar "
                            f"i self._widgets"
                        )
                        self._widgets[wid] = w
                        # FIX v7-fix18: winId() får ALDRIG tvinga fram
                        # fönster-skapande (CreateWindowEx-storm-vektor)
                        _hwnd_txt = "?"
                        with suppress(Exception):
                            if (hasattr(w, "_native_window_ok")
                                    and not w._native_window_ok()):
                                _hwnd_txt = "(skapande misslyckades — karantän)"
                            else:
                                _hwnd_txt = str(int(w.winId()))
                        self._log.info(
                            f"{LOG_PREFIX} Fönster skapat: {wid!r} — "
                            f"HWND={_hwnd_txt} visible={w.isVisible()}"
                        )
                        # FIX v7-fix22: ikoner ENDAST om fönstret FACTISKT
                        # skapats — annars förgiftas fönsterklassen och
                        # ALLA efterföljande CreateWindowEx misslyckas.
                        with suppress(Exception):
                            _win_ok = (
                                hasattr(w, "_native_window_ok")
                                and w._native_window_ok()
                            )
                            if _win_ok and self._app_icon:
                                if hasattr(w, "setWindowIcon"):
                                    w.setWindowIcon(self._app_icon)
                                if not self._app_icon_set_on_first_window:
                                    self._app_icon_set_on_first_window = True
                                    self._app.setWindowIcon(self._app_icon)
                                    self._log.info(
                                        f"{LOG_PREFIX} App-ikon satt NU "
                                        f"(efter lyckat fönster, v7-fix22)"
                                    )
                                self.apply_win32_process_icon(int(w.winId()))
                            elif not _win_ok:
                                self._log.warning(
                                    f"{LOG_PREFIX} hoppar över ikon-sättning "
                                    f"— fönstret skapades ej (v7-fix22)"
                                )
                    except BaseException as _bw_err:  # Fångar ALLT
                        import traceback as _tb
                        self._log.critical(
                            f"{LOG_PREFIX} WIDGET-SKAPANDE KRASCHADE for {wid!r}: "
                            f"{type(_bw_err).__name__}: {_bw_err}"
                        )
                        for line in _tb.format_exception(
                            type(_bw_err), _bw_err, _bw_err.__traceback__
                        ):
                            self._log.critical(f"{LOG_PREFIX}   {line.rstrip()}")
                        # Visa dialog sa Rickard ser vad som handde
                        try:
                            show_error_dialog(
                                title=f"Widget {wid!r} kunde inte skapas",
                                user_message=(
                                    f"Kunde inte skapa widget {wid!r}.\n\n"
                                    f"Fel: {type(_bw_err).__name__}: {_bw_err}\n\n"
                                    f"Loggfil: {LOG_FILE}"
                                ),
                                technical=_format_compact_traceback(_bw_err),
                                category="code_bug",
                            )
                        except Exception:
                            pass
                        # Fortsatt med naesta widget istallet for att krascha helt
                        continue

                self._log.info(
                    f"{LOG_PREFIX} _populate_windows: skapat {len(self._widgets)} "
                    f"widgets"
                )

                # Ta bort widgets som inte längre finns i settings
                config_ids = {c.get("id") for c in configs if c.get("id")}
                to_remove = [wid for wid in self._widgets if wid not in config_ids]
                for wid in to_remove:
                    with error_boundary(f"widget.remove.{wid}"):
                        w = self._widgets.pop(wid)
                        if hasattr(w, "_unregister_hotkeys"):
                            w._unregister_hotkeys()
                        if hasattr(w, "close"):
                            # FIX 2026-09-24: tillåt close (annars spöken)
                            w._allow_close = True
                            with suppress(Exception):
                                w.hide()
                            w.close()
                            with suppress(Exception):
                                w.deleteLater()
                        self._log.info(f"Fönster borttaget: {wid!r}")
                self._log.info(
                    f"{LOG_PREFIX} === _populate_windows SLUT — "
                    f"{len(self._widgets)} widgets kvar ==="
                )
        except Exception as e:
            self._log.error(f"_populate_windows misslyckades: {e}", exc_info=True)
        finally:
            self._populate_in_progress = False

    def _set_theme_value(self, value: str) -> None:
        """
        NY v7-fix82: sätt tema från tray-menyn (light/dark/auto/system).

        settings.set_theme() sänder theme_changed → _on_theme_changed
        applicerar om temat på ALLA widgets + bygger om tray-menyn.
        'auto' = klockstyrt (07:00–18:59 ljust, annars mörkt).
        """
        try:
            value = str(value).lower().strip()
            if value not in ("light", "dark", "auto", "system"):
                self._log.warning(
                    f"{LOG_PREFIX} _set_theme_value: ogiltigt tema {value!r}"
                )
                return
            if hasattr(self.settings, "set_theme"):
                self.settings.set_theme(value)
                self._log.info(
                    f"{LOG_PREFIX} Tema satt till '{value}' via tray-menyn "
                    f"(v7-fix82)"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} settings saknar set_theme() — kan ej "
                    f"sätta tema {value!r}"
                )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _set_theme_value: {e}")

    def _set_window_size_max(self) -> None:
        """NY v7-fix61: max storlek (90 % bredd, 75 % höjd av skärmen)."""
        try:
            _scr = (
                self._app.primaryScreen() if self._app else None
            )
            if _scr is None:
                return
            _sg = _scr.availableGeometry()
            self._set_window_size_preset(
                int(_sg.width() * 0.9), int(_sg.height() * 0.75)
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _set_window_size_max: {e}")

    def _set_window_size_preset(self, width: int, height: int) -> None:
        """
        NY v7-fix61: sätt fönsterstorlek (förinställning från tray).

        Rickard: "gör det som en ikon som man kan justera storleken på" —
        Ikon / Kompakt / Standard / Stor. Behåller topp-vänster-position,
        sparar geometrin, fungerar i alla desktop-lägen (DII-kompenserad).
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                _sx, _sy = shell.x(), shell.y()
                # FIX v7-fix62: sakerhets-clamp — om positionen ligger
                # utanfor ALLA skärmar (sparade felkoordinater, t.ex.
                # 2546 på en 1536 px skärm) → centrera på primära skärmen
                _on_screen = False
                for _sc in (self._app.screens() if self._app else []):
                    if _sc.geometry().contains(_sx, _sy):
                        _on_screen = True
                        break
                if not _on_screen:
                    _sg = (
                        self._app.primaryScreen().availableGeometry()
                        if self._app and self._app.primaryScreen() else None
                    )
                    if _sg is not None:
                        _sx = _sg.x() + (_sg.width() - width) // 2
                        _sy = _sg.y() + (_sg.height() - height) // 2
                        self._log.info(
                            f"{LOG_PREFIX} Storlek: position utanfor "
                            f"skarm → centrerad ({_sx},{_sy})"
                        )
                if hasattr(w, "_shell_screen_move"):
                    w._shell_screen_move(_sx, _sy, width, height)
                else:
                    shell.resize(width, height)
                with suppress(Exception):
                    shell.show()
                with suppress(Exception):
                    w._save_geometry_now()
                self._log.info(
                    f"{LOG_PREFIX} Storlek satt: {width}x{height} "
                    f"(vid {_sx},{_sy}) — v7-fix61"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_window_size_preset: {e}", exc_info=True
            )

    def _tray_center_window(self, keep_size: bool = True) -> None:
        """
        NY v7-fix47: centrera fönstret via tray-menyn.

        FIX v7-fix72: keep_size=True som default — BEHÅLLER nuvarande
        storlek (Rickard: "fönsterstorlek ska alltid sparas, även vid
        omstart eller centrering"). Full nollställning finns i fönstrets
        högerklicksmeny "Nollställ (centrera + standardstorlek)".
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                if hasattr(w, "_center_window"):
                    w._center_window(reset_size=not keep_size)
            self._log.info(
                f"{LOG_PREFIX} Fönstret centrerat via tray-menyn "
                f"(storlek {'beholden' if keep_size else 'nollställd'})"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _tray_center_window misslyckades: {e}",
                exc_info=True,
            )

    def _single_window_enabled(self) -> bool:
        """
        NY v7-fix40: är enbart-ett-fönster-läget aktivt?

        Rickard 2026-10-01: "ska enbart visa ett fönster, när man väljer
        öppna nytt fönster, så ska den enbart visa det redan skapat".
        Default: PÅ. Kan stängas av via settings (single_window=false)
        om multi-fönster önskas igen.
        """
        try:
            if hasattr(self.settings, "single_window"):
                return bool(self.settings.single_window())
            return bool(self.settings.get("single_window", True))
        except Exception:
            return True

    def _show_existing_window(self) -> None:
        """
        NY v7-fix40: visa det BEFINTLIGA fönstret (enbart-läge).

        Visar skalet (om gömt), återfäster desktop-lagret och ser till
        att widget-barnet är synligt.
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                wid = getattr(w, "win_id", "?")
                shell = getattr(w, "_shell", None)
                if shell is not None:
                    # NY v7-fix44: minimerat (Win+D)? → SW_RESTORE först
                    with suppress(Exception):
                        if sys.platform == "win32":
                            import ctypes as _ct
                            _hw = int(shell.winId())
                            _u32 = _ct.windll.user32
                            if _u32.IsIconic(_hw):
                                _u32.ShowWindow(_hw, 9)  # SW_RESTORE
                                self._log.info(
                                    f"{LOG_PREFIX} _show_existing_window: "
                                    f"{wid!r} var MINIMERAT → återställt"
                                )
                    with suppress(Exception):
                        if not shell.isVisible():
                            shell.show()
                    self._apply_desktop_shell(shell, wid)
                with suppress(Exception):
                    if not w.isVisible():
                        w.setVisible(True)
                self._log.info(
                    f"{LOG_PREFIX} _show_existing_window: {wid!r} synlig "
                    f"(enbart-läge, inget nytt fönster skapat)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _show_existing_window misslyckades: {e}",
                exc_info=True,
            )

    def add_window(self, x: Optional[int] = None, y: Optional[int] = None) -> Optional[str]:
        """
        Lägg till ett nytt fönster (via settings.add_window + populate).
        Returnerar window-id (None vid fel).

        NY v7-fix40: i enbart-läge (default) visas DET BEFINTLIGA fönstret
        i stället för att skapa ett nytt.
        """
        try:
            if not hasattr(self.settings, "add_window"):
                self._log.warning("Settings saknar add_window")
                return None
            # NY v7-fix40: finns redan fönster? → VISA det, skapa inget nytt
            if self._single_window_enabled():
                with self._widget_lock:
                    _existing = list(self._widgets.items())
                if _existing:
                    _wid, _w = _existing[0]
                    self._log.info(
                        f"{LOG_PREFIX} enbart-läge: 'Nytt fönster' → visar "
                        f"det befintliga fönstret {_wid!r}"
                    )
                    self._show_existing_window()
                    return _wid
            x = x if x is not None else 100
            y = y if y is not None else 100
            wid = self.settings.add_window(x, y)
            self._populate_windows()
            self._log.info(f"Nytt fönster skapat: wid={wid!r} vid ({x}, {y})")
            return wid
        except Exception as e:
            self._log.error(f"add_window misslyckades: {e}")
            return None

    def remove_window(self, wid: str) -> bool:
        """Ta bort ett fönster (via settings.remove_window + populate)."""
        try:
            if hasattr(self.settings, "remove_window"):
                self.settings.remove_window(wid)
            self._populate_windows()
            self._log.info(f"Fönster borttaget via UI: {wid!r}")
            return True
        except Exception as e:
            self._log.error(f"remove_window misslyckades: {e}")
            return False

    def _set_glass_style(self, style: str) -> None:
        """Sätt glasmorphism-stil och uppdatera alla fönster."""
        self._glass_style = style
        self._log.info(f"Glasmorphism: {style}")
        with self._widget_lock:
            for w in self._widgets.values():
                if hasattr(w, "set_glass_style"):
                    with suppress(Exception):
                        w.set_glass_style(style)
                elif hasattr(w, "_apply_theme"):
                    with suppress(Exception):
                        w._apply_theme()
        self._populate_tray_menu()  # Uppdatera checkmarks

    # -----------------------------------------------------------------------
    # LOCK / UNLOCK (NY v6.4)
    # -----------------------------------------------------------------------

    def _set_all_windows_locked(self, locked: bool) -> None:
        """Sätt lås-status för ALLA fönster (via tray-menyn)."""
        with self._widget_lock:
            widgets = list(self._widgets.values())
        for w in widgets:
            if hasattr(w, "set_locked"):
                with suppress(Exception):
                    w.set_locked(locked)
        self._log.info(
            f"{LOG_PREFIX} {'Låser' if locked else 'Låser upp'} "
            f"{len(widgets)} fönster"
        )
        # Uppdatera tray-meny
        self._populate_tray_menu()

    def _toggle_focus_mode_all_windows(self) -> None:
        """
        NY v6.4.1: Toggla Focus Mode för ALLA widget-fönster (från tray).

        Vad Focus Mode gör:
          - Döljer normal task-lista
          - Visar 1 task åt gången (stor)
          - ← → = navigera, Enter/Space = markera klar, Esc = avsluta
        """
        try:
            toggled = 0
            for widget in self._widgets.values():
                if hasattr(widget, "_toggle_focus_mode"):
                    widget._toggle_focus_mode()
                    toggled += 1
            self._log.info(
                f"{LOG_PREFIX} _toggle_focus_mode_all_windows: "
                f"togglade {toggled} fönster"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_focus_mode_all_windows misslyckades: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # EVENT HANDLERS
    # -----------------------------------------------------------------------

    def _on_second_instance(self, message: str = "SHOW") -> None:
        """
        NY v7-fix87: en andra instans av TaskBord startade → visa oss.

        Kedja: användaren startar appen igen → det hårda låset stoppar
        den nya processen → den signalar "SHOW" via instans-kanalen →
        HÄR: visa + lyft fönstret + tray-notis. Att starta appen igen
        blir alltså ett sätt att TA FRAM den.
        """
        try:
            self._log.info(
                f"{LOG_PREFIX} Andra instans startade ({message!r}) → "
                f"visar fönstret (v7-fix87)"
            )
            with suppress(Exception):
                self._show_existing_window()
            # Lyft över appar en stund så att den SYNNS (tray-lyft-tricket)
            with suppress(Exception):
                self._lift_on_top_temporarily()
            if self._tray is not None:
                with suppress(Exception):
                    self._tray.showMessage(
                        APP_NAME,
                        "TaskBord var redan igång — fönstret visas nu",
                        self._QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _on_second_instance misslyckades: {e}"
            )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """Hantera tema-ändring (uppdatera tray + alla widgets)."""
        try:
            if self._tray is not None:
                self._update_tray_tooltip()
                self._populate_tray_menu()
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_apply_theme"):
                            w._apply_theme()
        except Exception as e:
            self._log.debug(f"on_theme_changed misslyckades: {e}")

    def _safe_update_widgets(self) -> None:
        """Säker widget-uppdatering (anropas via windows_updated-signal).
        FIX 2026-09-24: Debounce — populate ska inte spammas av
        windows_updated (moveEvent→save→signal→populate→show→move…)."""
        try:
            import traceback as _tbs
            _stk = _tbs.extract_stack(limit=4)[:-1]
            _call = " ← ".join(
                f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                for f in _stk[-2:]
            )
            self._log.info(
                f"{LOG_PREFIX} _safe_update_widgets ANROPAD "
                f"← {_call}"
            )
            if getattr(self, "_populate_scheduled", False):
                self._log.debug(
                    f"{LOG_PREFIX} _safe_update_widgets: populate redan schemalagd"
                )
                return
            self._populate_scheduled = True
            # NY v6.4.1 v7-fix7: 150→500 ms — vi såg 25 anrop / 100 ms i loggen.
            # 500 ms tar kvar poptat-kaskad men UI känns fortfarande responsivt.
            delay_ms = 500
            if self._QTimer is not None:
                def _run_populate() -> None:
                    self._populate_scheduled = False
                    import traceback as _tbr
                    _s = _tbr.extract_stack(limit=4)[:-1]
                    _src = " ← ".join(
                        f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                        for f in _s[-2:]
                    )
                    self._log.info(
                        f"{LOG_PREFIX} _populate_windows UTLÖST "
                        f"av QTimer (debounced 500ms) ← {_src}"
                    )
                    self._populate_windows()
                self._QTimer.singleShot(delay_ms, _run_populate)
            else:
                self._populate_scheduled = False
                self._populate_windows()
        except Exception as e:
            self._populate_scheduled = False
            self._log.error(f"update_widgets misslyckades: {e}")

    # -----------------------------------------------------------------------
    # POPULATE / REFRESH — synka UI med data
    # -----------------------------------------------------------------------

    def populate_all(self) -> None:
        """Synka ALLA UI-komponenter med aktuell data (användbart efter restore)."""
        with error_boundary("populate_all"):
            self._populate_windows()
            self._update_tray_tooltip()
            if self._tray is not None:
                self._populate_tray_menu()
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_rebuild_task_list"):
                            w._rebuild_task_list()
                        elif hasattr(w, "reload"):
                            w.reload()
            self._log.info("populate_all klar")

    # -----------------------------------------------------------------------
    # FORCE SHOW WIDGET (NY v6.4.1 v7)
    # -----------------------------------------------------------------------

    def force_show_all_widgets(self) -> None:
        """
        NY v6.4.1 v7-fix3: Tvinga ALLA widget-fonster att bli synliga.

        Rickard 2026-09-22: "fortfarande inget fönster, ska ej vara osynligt,
        men ej dölja iconer".

        Approach (v7-fix3):
          - Reparenta från WorkerW (som ÄR Explorer-ikon-lagret → döljer ikoner)
          - Ta bort WS_EX_NOACTIVATE + WS_EX_TOPMOST
          - HWND_TOP = toppen av normal z-order (över Explorer-ikoner)
          - ShowWindow(SW_SHOW) + SW_RESTORE

        Skilljer fran bring_all_to_front() som respekterar z-order.
        Aktiveras via:
          - CLI-flagga --force-show (permanent under sessionen)
          - Tray-meny 'Diagnostik' → 'Tvinga synlig'
        """
        n_total = 0
        n_shown = 0
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            n_total = len(widgets)
            self._log.info(
                f"{LOG_PREFIX} force_show_all_widgets: {n_total} widgets → "
                f"NOTOPMOST (synlig, EJ över appar)"
            )
            for w in widgets:
                try:
                    # NY v6.4.1 v7-fix2: Sätt _force_show PÅ widget så
                    # _periodic_zorder_check + _setup_bugg19_zorder använder
                    # HWND_TOP (toppen av desktop-lagret, EJ över allt).
                    w._force_show = True
                    # NY v7-fix51: desktop-lagret aktivt? → slita ALDRIG
                    # loss fönstret från skrivbordet! Gamla koden körde
                    # SetParent(hwnd, 0) som rev ner Progman-parentingen
                    # → Win+D kunde gömma fönstret igen (+ force_show-
                    # flaggan gjorde att bevakningen hoppade över det).
                    _fs_shell0 = getattr(w, "_shell", None)
                    _layer_active = str(
                        getattr(_fs_shell0, "_desktop_layer_mode", "")
                    ) in ("above", "behind", "top")
                    if _layer_active:
                        with suppress(Exception):
                            if sys.platform == "win32":
                                import ctypes as _ct0
                                _u0 = _ct0.windll.user32
                                _h0 = (
                                    int(_fs_shell0.winId())
                                    if _fs_shell0 is not None else 0
                                )
                                if _h0 and _u0.IsIconic(_h0):
                                    _u0.ShowWindow(_h0, 9)  # SW_RESTORE
                            if (_fs_shell0 is not None
                                    and not _fs_shell0.isVisible()):
                                _fs_shell0.show()
                        self._log.info(
                            f"{LOG_PREFIX} force_show: "
                            f"{getattr(w, 'win_id', '?')!r} behåller "
                            f"desktop-lagret ({getattr(_fs_shell0, '_desktop_layer_mode', '?')}) "
                            f"— sliter ej loss (v7-fix51)"
                        )
                        n_shown += 1
                        continue
                    # 1. Använd Win32 ShowWindow(hwnd, SW_RESTORE = 9)
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            hwnd = int((w._shell.winId() if hasattr(w, '_shell') and w._shell else w.winId()))
                            if hwnd:
                                user32 = ctypes.windll.user32
                                # NY v6.4.1 v7-fix3: Reparenta från WorkerW
                                # Workers ÄR Explorer-ikon-lagret → döljer ikoner.
                                # Vi vill vara top-level igen.
                                try:
                                    current_parent = user32.GetParent(hwnd)
                                    if current_parent:
                                        user32.SetParent(hwnd, 0)
                                except Exception:
                                    pass
                                # NY v7-fix38: force-show = escape hatch —
                                # markera skalet som legacy så underhålls-
                                # timern INTE återfäster det i desktop-lagret
                                with suppress(Exception):
                                    _fs_shell = getattr(w, "_shell", None)
                                    if _fs_shell is not None:
                                        _fs_shell._desktop_layer_mode = (
                                            "normal"  # v7-fix56: ej legacy
                                        )
                                # Ta bort WS_EX_NOACTIVATE + WS_EX_TOPMOST
                                try:
                                    GWL_EXSTYLE = -20
                                    WS_EX_NOACTIVATE = 0x08000000
                                    WS_EX_TOPMOST = 0x00000008
                                    try:
                                        current_ex = user32.GetWindowLongPtrW(
                                            hwnd, GWL_EXSTYLE
                                        )
                                    except Exception:
                                        current_ex = user32.GetWindowLongW(
                                            hwnd, GWL_EXSTYLE
                                        )
                                    new_ex = (
                                        current_ex
                                        & ~WS_EX_NOACTIVATE
                                        & ~WS_EX_TOPMOST
                                    )
                                    if new_ex != current_ex:
                                        try:
                                            user32.SetWindowLongPtrW(
                                                hwnd, GWL_EXSTYLE, new_ex
                                            )
                                        except Exception:
                                            user32.SetWindowLongW(
                                                hwnd, GWL_EXSTYLE, new_ex
                                            )
                                except Exception:
                                    pass
                                # VIKTIGT: först ShowWindow(SW_RESTORE) + SW_SHOW
                                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                                # FIX 2026-09-24: INTE NOTOPMOST/TOP —
                                # båda flyttar ÖVER andra appar.
                                # Bara säkerställ synlig (SW_SHOWNOACTIVATE).
                                # Z-order lämnas orörd → fokuserade app går
                                # naturligt ovanför widgeten.
                                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                                # 3. Verifiera synlig
                                if user32.IsWindowVisible(hwnd):
                                    n_shown += 1
                                    self._log.info(
                                        f"{LOG_PREFIX} force_show: "
                                        f"HWND={hwnd} nu SYNLIG "
                                        f"(z-order orörd, ej över appar)"
                                    )
                                else:
                                    user32.ShowWindow(hwnd, 5)
                                    if user32.IsWindowVisible(hwnd):
                                        n_shown += 1
                                        self._log.info(
                                            f"{LOG_PREFIX} force_show (fallback): "
                                            f"HWND={hwnd} nu SYNLIG"
                                        )
                                    else:
                                        self._log.warning(
                                            f"{LOG_PREFIX} force_show: "
                                            f"HWND={hwnd} FORTFARANDE dold!"
                                        )
                        except Exception as e:
                            self._log.warning(
                                f"{LOG_PREFIX} force_show Win32 misslyckades: {e}"
                            )
                    # 4. Qt-niva: visa om dold — INTE raise/activate
                    # (activate/raise flyttar fönstret ÖVER andra appar)
                    try:
                        import threading as _th
                        on_gui = _th.current_thread() is _th.main_thread()
                        if on_gui:
                            if not w.isVisible():
                                w.show()
                        else:
                            from PySide6.QtCore import QMetaObject, Qt as _Qt
                            QMetaObject.invokeMethod(
                                w, "show", _Qt.ConnectionType.QueuedConnection,
                            )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} force_show Qt misslyckades: {e}"
                        )
                except Exception as e:
                    self._log.error(
                        f"{LOG_PREFIX} force_show misslyckades for widget: {e}"
                    )
            self._log.info(
                f"{LOG_PREFIX} force_show_all_widgets klar: "
                f"{n_shown}/{n_total} widgets synliga "
                f"(NOTOPMOST — ej över appar)"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} force_show_all_widgets FEL: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # BRING TO FRONT (BUGG 19/26)
    # -----------------------------------------------------------------------

    def bring_all_to_front(self) -> None:
        """
        BUGG 19: Visa alla fönster tillfälligt (användaren klickade på tray).
        BUGG 26: Auto-reposition om widget täcker skrivbordsikoner.

        Flöde:
          1. Hämta skrivbordsikoner-positioner (desktop.get_icon_rects)
          2. För varje fönster: kontrollera kollision, flytta om nödvändigt
          3. Visa fönster, raise, activate
          4. Sänk till botten igen (HWND_BOTTOM) så att andra fönster kan täcka
        """
        try:
            # Hämta ikonpositioner (BUGG 26)
            icon_rects: List[Tuple[int, int, int, int]] = []
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                get_icons = getattr(self._desktop_mod(desktop_status), "get_icon_rects", None)
                if get_icons:
                    with suppress(Exception):
                        icon_rects = get_icons() or []

            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                with suppress(Exception):
                    if hasattr(w, "bring_to_front"):
                        w.bring_to_front()
                    else:
                        w.show()
                        w.raise_()
                        w.activateWindow()
                        w.lower()
        except Exception as e:
            self._log.debug(f"bring_all_to_front misslyckades: {e}")
