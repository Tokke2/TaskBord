# -*- coding: utf-8 -*-
"""Skrivbordsläge, glas/transparens och fönsternivå (Win32)."""

from __future__ import annotations

import sys
from contextlib import suppress
from typing import Any

from app.constants import LOG_PREFIX


class DesktopShellMixin:
    """Skrivbordsläge, glas/transparens och fönsternivå (Win32)."""

    def _apply_desktop_shell(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: Desktop-lager — Win+D-säkert skrivbordsläge.

        Rickard 2026-10-01:
          "win+d döljer fönstret, ska alltid vara synligt överst på
           skrivbordet + vara transparent så ej ikoner döljs"

        Windows "Visa skrivbordet" (Win+D) minimerar ALLA toppfönster —
        HWND_BOTTOM + SC_MINIMIZE-blockering räcker INTE (v7-fix32
        bevisade detta på Rickards maskin). Därför tre lägen
        (settings 'desktop_mode'):

          above  (default) — barn i skrivbordslagret, ÖVER ikonerna:
                    SetParent(Progman/ikon-ägare) + ovanför
                    SHELLDLL_DefView. Win+D kan ALDRIG gömma den
                    (den lever i skrivbordet, precis som tapeten).
                    Genomskinligt glas-skal → ikonerna syns igenom.
          behind — kila ovanför WorkerW (Rainmeter "On Desktop"):
                    skrivbordsikonerna målas OVANPÅ widgeten →
                    ikonerna döljs ALDRIG. Också Win+D-säkert.
          top    — (val i tray) ALLTID ÖVERST: vanligt HWND_TOPMOST-fönster
                    ovanpå alla andra fönster, se _apply_top_mode().
          legacy — v7-fix32-beteende: HWND_BOTTOM + NOACTIVATE +
                    TOOLWINDOW + SC_MINIMIZE-blockerare + 30s-timer.

        Fallback-kedja: above → behind → legacy (inga gamla
        funktioner tas bort — REGEL: behåll gamla + lägg till nya).
        """
        import ctypes as _ct_probe
        if sys.platform != "win32" and not hasattr(_ct_probe, "windll"):
            self._apply_portable_level(shell, wid)
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = int(shell.winId())
            if not hwnd:
                self._log.warning(
                    f"{LOG_PREFIX} _apply_desktop_shell: HWND=0 — hoppar"
                )
                shell._desktop_layer_pending = True
                return
            shell._desktop_wid = wid
            _prev_layer = str(getattr(shell, "_desktop_layer_mode", "") or "")

            # 1. Extended styles: NOACTIVATE + TOOLWINDOW (alla lägen)
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            old_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            _was_topmost = bool(old_ex & 0x8)  # WS_EX_TOPMOST (stilen rensas strax nedan)
            new_ex = (old_ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~0x8  # clear TOPMOST
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)

            # 1b. NY v7-fix43: WS_THICKFRAME → ÄKTA resize-kanter.
            # Krävs för att Windows ska starta resize-loopen när
            # WM_NCHITTEST returnerar HTLEFT/HTRIGHT/etc. Den osynliga
            # non-client-ramen tas bort via WM_NCCALCSIZE (se nedan) så
            # hela fönstret förblir klientyta — ingen synlig ram.
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            old_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(
                hwnd, GWL_STYLE, old_style | WS_THICKFRAME
            )

            # 2. nativeEvent-blockerare på skalet (extra Win+D-skydd)
            if not hasattr(shell, "_native_event_patched"):
                shell._native_event_patched = True
                _orig_native = shell.nativeEvent

                def _block_minimize(eventType, message):
                    """
                    Skal-fönstrets nativeEvent:

                    1. Blockera SC_MINIMIZE — Win+D ska ej gömma oss
                    2. NY v7-fix43: WM_NCCALCSIZE → 0 (frameless: hela
                       fönstret = klientyta trots WS_THICKFRAME)
                    3. NY v7-fix43: WM_NCHITTEST → resize-kanter (HT*)
                       när musen är ≤6 px från kanten/hörnen
                    """
                    try:
                        WM_SYSCOMMAND = 0x0112
                        SC_MINIMIZE = 0xF020
                        WM_NCCALCSIZE = 0x0083
                        WM_NCHITTEST = 0x0084
                        HTLEFT, HTRIGHT = 10, 11
                        HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
                        HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
                        _KANT = 8  # px från kanten som räknas som resize-zon (v7-fix51: 6→8 för 125% DPI)

                        class _MSG(ctypes.Structure):
                            _fields_ = [
                                ("hwnd", wintypes.HWND),
                                ("message", wintypes.UINT),
                                ("wParam", wintypes.WPARAM),
                                ("lParam", wintypes.LPARAM),
                                ("time", wintypes.DWORD),
                                ("pt_x", wintypes.LONG),
                                ("pt_y", wintypes.LONG),
                            ]

                        msg = _MSG.from_address(int(message))
                        if msg.message == WM_SYSCOMMAND:
                            cmd = msg.wParam & 0xFFF0
                            if cmd == SC_MINIMIZE:
                                self._log.info(
                                    f"{LOG_PREFIX} Win+D blockerat "
                                    f"(SC_MINIMIZE på skal-HWND)"
                                )
                                return True, 0  # Blockerad
                        elif msg.message == 0x0005 and msg.wParam == 1:
                            # NY v7-fix44: WM_SIZE + SIZE_MINIMIZED
                            # FIX v7-fix76: under pågående nedstängning är
                            # detta NORMALT (fönstret stängs) — tyst.
                            if not getattr(self, "_shutdown_initiated", False):
                                self._log.warning(
                                    f"{LOG_PREFIX} ⚠ FÖNSTRET MINIMERAS "
                                    f"(Win+D/Win+M?) — HWND={hwnd}, "
                                    f"läge={getattr(shell, '_desktop_layer_mode', '?')} "
                                    f"(återställs automatiskt i legacy-läge)"
                                )
                        elif msg.message == 0x0018 and not msg.wParam:
                            # NY v7-fix44: WM_SHOWWINDOW FALSE = göms
                            # FIX v7-fix76: samma — vid nedstängning SKA
                            # fönstret gömmas, alltså ingen varning.
                            if not getattr(self, "_shutdown_initiated", False):
                                self._log.warning(
                                    f"{LOG_PREFIX} ⚠ FÖNSTRET GÖMS av "
                                    f"systemet (WM_SHOWWINDOW=FALSE) — HWND={hwnd}"
                                )
                        elif msg.message == WM_NCCALCSIZE and msg.wParam:
                            # v7-fix43: hela fönstret = klientyta
                            # (annars stjäl THICKFRAME en osynlig ram)
                            return True, 0
                        elif msg.message == WM_NCHITTEST:
                            # lParam = skärmkoordinater (signerade 16-bit)
                            _lx = ctypes.c_short(
                                msg.lParam & 0xFFFF
                            ).value
                            _ly = ctypes.c_short(
                                (msg.lParam >> 16) & 0xFFFF
                            ).value
                            _hw = int(msg.hwnd) if msg.hwnd else hwnd
                            rect = wintypes.RECT()
                            user32.GetWindowRect(
                                _hw, ctypes.byref(rect)
                            )
                            _dl = _lx - rect.left
                            _dr = rect.right - _lx
                            _dt = _ly - rect.top
                            _db = rect.bottom - _ly
                            _ht = 0
                            if _dl <= _KANT and _dt <= _KANT:
                                _ht = HTTOPLEFT
                            elif _dr <= _KANT and _dt <= _KANT:
                                _ht = HTTOPRIGHT
                            elif _dl <= _KANT and _db <= _KANT:
                                _ht = HTBOTTOMLEFT
                            elif _dr <= _KANT and _db <= _KANT:
                                _ht = HTBOTTOMRIGHT
                            elif _dl <= _KANT:
                                _ht = HTLEFT
                            elif _dr <= _KANT:
                                _ht = HTRIGHT
                            elif _dt <= _KANT:
                                _ht = HTTOP
                            elif _db <= _KANT:
                                _ht = HTBOTTOM
                            if _ht:
                                return True, _ht
                    except Exception:
                        pass
                    return False, 0

                shell.nativeEvent = _block_minimize

            # 3. Timer: mode-medvetet underhåll var 30:e sekund
            if not hasattr(shell, "_zorder_timer"):
                _timer = self._QTimer(shell)
                _timer.setInterval(30000)  # 30 sek
                _timer.timeout.connect(
                    lambda: self._maintain_desktop_level(shell)
                )
                _timer.start()
                shell._zorder_timer = _timer

            # 4. Desktop-lager enligt läge (med fallback-kedja)
            mode = self._desktop_mode()
            # v7-fix72: lyft pågår? — applicera inte skrivbordslager
            if str(getattr(shell, "_desktop_layer_mode", "")) == "_lift":
                return
            # NY: ALLTID ÖVERST (val i tray → Skrivbordsläge). Vanligt toppfönster som
            # ligger ovanpå alla andra fönster; lossas från skrivbordslagret om det satt där.
            if mode == "top":
                self._apply_top_mode(shell, hwnd, wid)
                return
            # Inte 'visa över andra appar' → fönstret får ALDRIG vara topmost (kom från 'alltid överst'
            # eller blev kvar topmost efter en tillfällig lyftning)
            self._clear_topmost(hwnd, force=_prev_layer == "top" or _was_topmost)
            desktop_status = self._imports.get("desktop")
            if mode in ("above", "behind") and desktop_status and desktop_status.ok:
                if mode == "above":
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "attach_window_above_desktop_icons", None,
                    )
                    if fn is None:
                        # NY v7-fix40: tyst fn-None dolde att desktop.py
                        # är gammal — säg det TYDLIGT
                        # NY v7-fix42: visa OCKSÅ vilken fil som laddats
                        _dfile = getattr(
                            self._desktop_mod(desktop_status), "__file__", "?"
                        )
                        self._log.critical(
                            f"{LOG_PREFIX} core/desktop.py är GAMMAL — "
                            f"'attach_window_above_desktop_icons' saknas! "
                            f"Inläst fil: {_dfile} — ersätt den med nya "
                            f"core/desktop.py från workspacen (v7-fix38/40)"
                        )
                    if fn and fn(hwnd):
                        shell._desktop_layer_mode = "above"  # experimentellt
                        # NY v7-fix48: spara förälderns origo — widgeten
                        # komponerar alla flyttar mot SKÄRM-koordinater
                        _dm = self._desktop_mod(desktop_status)
                        _org = (0, 0)
                        if _dm is not None and hasattr(
                            _dm, "get_desktop_parent_origin"
                        ):
                            _org_fys = (
                                _dm.get_desktop_parent_origin(hwnd)
                                or (0, 0)
                            )
                            # FIX v7-fix54: konvertera FYSISKT origo →
                            # LOGISKT (Qt:s koordinatrum, t.ex. 125% DPI).
                            # Qt-move konverterar logiskt→fysikt självt,
                            # därför måste kompenseringen ske i logiskt
                            # rum: fys_skärm = (log - origo_log)*dpr.
                            _dpr = 1.0
                            with suppress(Exception):
                                _dpr = float(
                                    shell.devicePixelRatioF() or 1.0
                                ) or 1.0
                            _org = (
                                _org_fys[0] / _dpr,
                                _org_fys[1] / _dpr,
                            )
                        shell._parent_origin = _org
                        self._log.info(
                            f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: OVANPÅ IKONERNA "
                            f"═══ Win+D-säkert ✅ (barn i skrivbordet) "
                            f"skal {wid!r} HWND={hwnd} origo={_org} (komp. aktiv)"
                        )
                        return
                    self._log.warning(
                        f"{LOG_PREFIX} Skal {wid!r}: läget 'ovanpå ikoner' "
                        f"misslyckades → provar 'bakom ikoner'"
                    )
                fn = getattr(
                    self._desktop_mod(desktop_status),
                    "wedge_window_behind_desktop_icons", None,
                )
                if fn is None:
                    _dfile2 = getattr(
                        self._desktop_mod(desktop_status), "__file__", "?"
                    )
                    self._log.critical(
                        f"{LOG_PREFIX} core/desktop.py är GAMMAL — "
                        f"'wedge_window_behind_desktop_icons' saknas! "
                        f"Inläst fil: {_dfile2} — ersätt med nya "
                        f"core/desktop.py (v7-fix38/40)"
                    )
                if fn and fn(hwnd):
                    shell._desktop_layer_mode = "behind"
                    self._log.info(
                        f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: BAKOM IKONERNA "
                        f"═══ Win+D-säkert ✅ (WorkerW-kil) "
                        f"skal {wid!r} HWND={hwnd}"
                    )
                    return
                # NY v7-fix70: behind-kilen misslyckades (t.ex. ingen
                # WorkerW på denna dator) — PROVA ABOVE automatiskt!
                # Above = barn i skrivbordet, ÖVER ikonerna, Win+D-säkert
                # (Rickard 2026-10-06: "fönstret ligger överst" när bakom-
                # läget faller tillbaka på vanligt toppfönster — ge en
                # SYNLIG återväg i stället).
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: behind-kilen misslyckades "
                    f"→ provar OVANPÅ IKONERNA automatiskt (v7-fix70)"
                )
                _dm70 = self._desktop_mod(desktop_status)
                _fn70 = getattr(
                    _dm70, "attach_window_above_desktop_icons", None
                )
                if _fn70 and _fn70(hwnd):
                    shell._desktop_layer_mode = "above"  # experimentellt
                    _org70 = (0, 0)
                    with suppress(Exception):
                        if hasattr(_dm70, "get_desktop_parent_origin"):
                            _of = (
                                _dm70.get_desktop_parent_origin(hwnd)
                                or (0, 0)
                            )
                            _dpr70 = float(
                                shell.devicePixelRatioF() or 1.0
                            ) or 1.0
                            _org70 = (_of[0] / _dpr70, _of[1] / _dpr70)
                    shell._parent_origin = _org70
                    self._log.info(
                        f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: OVANPÅ IKONERNA "
                        f"═══ Win+D-säkert ✅ (behind misslyckades → "
                        f"automatisk återväg) skal {wid!r} HWND={hwnd} "
                        f"origo={_org70}"
                    )
                    return
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: desktop-lager otillgängligt "
                    f"(behind+above misslyckades) — körs som vanligt "
                    f"toppfönster med Win+D-bevakning (v7-fix56/70)"
                )

            # 5. NY v7-fix56: LEGACY ÄR BORTTAGET (Rickards beslut —
            # above fungerar bevisat + behind är fallback). Om BÅDA
            # skrivbordslagren misslyckas körs fönstret som vanligt
            # toppfönster (NOACTIVATE+TOOLWINDOW redan satta) — synligt
            # och användbart, bevakas av _maintain_desktop_level.
            shell._desktop_layer_mode = "normal"
            self._log.warning(
                f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: VANLIGT FÖNSTER ═══ "
                f"(skrivbordslagret ej tillgängligt — extremely ovanligt; "
                f"Win+D-bevakning aktiv). Skal {wid!r} HWND={hwnd}"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _apply_desktop_shell misslyckades: {e}",
                exc_info=True,
            )

    @staticmethod
    def _clear_topmost(hwnd: int, force: bool = False) -> bool:
        """Ta bort WS_EX_TOPMOST från fönstret om det har den (eller alltid med force). True om något ändrades."""
        if not hwnd:
            return False
        try:  # utanför Windows saknas ctypes.windll → AttributeError → False
            import ctypes
            user32 = ctypes.windll.user32
            if force or user32.GetWindowLongW(hwnd, -20) & 0x00000008:  # GWL_EXSTYLE & WS_EX_TOPMOST
                user32.SetWindowPos(
                    hwnd, -2, 0, 0, 0, 0, 0x0010 | 0x0001 | 0x0002,
                )  # HWND_NOTOPMOST | NOACTIVATE|NOSIZE|NOMOVE
                return True
        except Exception:
            pass
        return False

    def _apply_portable_level(self, shell: Any, wid: str) -> None:
        """
        macOS/Linux: fönsternivå via Qt-flaggor (Win32-lagren finns bara på Windows).

          top            → alltid överst (WindowStaysOnTopHint)
          behind/above   → längst bak (WindowStaysOnBottomHint; fungerar på X11 och de flesta
                           Linux-skrivbord — macOS och vissa Wayland-miljöer ignorerar det)

        Fönstret tas inte med i aktivitetsfältet (Qt.Tool) och behåller tangentbordsfokus.
        """
        try:
            from PySide6.QtCore import Qt as _Qt

            mode = self._desktop_mode()
            want_top = mode == "top"
            T = _Qt.WindowType
            flags = shell.windowFlags()
            new = flags | T.Tool
            new = (new | T.WindowStaysOnTopHint) & ~T.WindowStaysOnBottomHint if want_top \
                else (new | T.WindowStaysOnBottomHint) & ~T.WindowStaysOnTopHint
            shell._desktop_layer_mode = "top" if want_top else "behind"
            shell._desktop_wid = wid
            if new != flags:
                was_visible = shell.isVisible()
                shell.setWindowFlags(new)
                if was_visible:
                    shell.show()  # flaggor kräver ny show()
            self._log.info(f"{LOG_PREFIX} portabelt fönsterläge ({sys.platform}): {mode} (Qt-flaggor)")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _apply_portable_level misslyckades: {e}")

    def _apply_top_mode(self, shell: Any, hwnd: int, wid: str) -> None:
        """
        ALLTID ÖVERST: fönstret är ett vanligt toppfönster (HWND_TOPMOST) ovanför alla appar.

        Lossas från skrivbordslagret (om det satt som barn i Progman), får behålla fokusförmågan
        (WS_EX_NOACTIVATE tas bort så man kan skriva i det) och ligger kvar utanför aktivitetsfältet
        (WS_EX_TOOLWINDOW). Win+D-skyddet (SC_MINIMIZE blockeras + återställning var 5:e sekund)
        gäller fortfarande.
        """
        import ctypes
        user32 = ctypes.windll.user32
        with suppress(Exception):
            if user32.GetParent(hwnd):
                from ctypes import wintypes as _wt
                _pre = _wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(_pre))
                user32.SetParent(hwnd, 0)
                user32.SetWindowPos(
                    hwnd, 0, _pre.left, _pre.top, 0, 0, 0x0004 | 0x0010 | 0x0001,
                )  # NOZORDER | NOACTIVATE | NOSIZE — bevara skärmpositionen
        with suppress(Exception):
            GWL_EXSTYLE = -20
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~0x08000000)  # utan NOACTIVATE
        user32.SetWindowPos(
            hwnd, -1, 0, 0, 0, 0, 0x0040 | 0x0010 | 0x0001 | 0x0002,
        )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
        shell._parent_origin = (0, 0)
        shell._desktop_layer_mode = "top"
        with suppress(Exception):  # tätare bevakning (Win+D) direkt, inte först efter 30 s
            _tm = getattr(shell, "_zorder_timer", None)
            if _tm is not None and _tm.interval() != 5000:
                _tm.setInterval(5000)
        self._log.info(
            f"{LOG_PREFIX} ═══ LÄGE: ALLTID ÖVERST ═══ ovanpå alla fönster "
            f"(skal {wid!r} HWND={hwnd})"
        )

    def _maintain_desktop_level(self, shell: Any) -> None:
        """
        NY v7-fix38: Mode-medvetet underhåll (var 30:e sekund).

        above  → återfäst i skrivbordslagret om Explorer tappat oss
        behind → re-kila ovanför WorkerW
        normal → vanligt toppfönster (v7-fix56: legacy borttaget) —
                  re-show om gömt, tätare bevakning (5 s)
        """
        try:
            if self._is_hidden_to_tray() or getattr(shell, "_hidden_to_tray", False):
                return   # gömd till tray med knappen – / ✕: visa inte igen av sig själv
            import ctypes
            user32 = ctypes.windll.user32
            mode = getattr(shell, "_desktop_layer_mode", "normal")
            wid = getattr(shell, "_desktop_wid", "?")

            # NY v7-fix70: om läget är "_push" men push INTE är aktiv
            # (t.ex. släpp-detektering missad) → återfäst nu
            if (
                mode == "_push"
                and not getattr(self, "_push_show_active", False)
            ):
                self._log.info(
                    f"{LOG_PREFIX} Skal {wid!r}: kvarvarande push-läge "
                    f"utan aktiv push → återfäster"
                )
                with suppress(Exception):
                    self._push_show_release()
                return
            # FIX v7-fix51: force_show-skip gäller NUMERA ENDAST legacy-
            # z-ordern. Iconic-restore + desktop-lager-återfästning måste
            # ALLTID köras — annars kunde Win+D gömma fönstret permanent
            # (force_show är default PÅ vid start!).
            _w = None
            with suppress(Exception):
                _w = self._widgets.get(wid)

            hwnd = 0
            with suppress(Exception):
                hwnd = int(shell.winId())
            if not hwnd or not user32.IsWindow(hwnd):
                # Fönstret dött (t.ex. Explorer-omstart) → återskapa
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: HWND saknas/död — "
                    f"återskapar fönstret (Explorer-omstart?)"
                )
                with suppress(Exception):
                    shell._desktop_layer_mode = None
                    shell.show()
                with suppress(Exception):
                    self._QTimer.singleShot(
                        1500, lambda: self._apply_desktop_shell(shell, wid)
                    )
                return

            # NY v7-fix44: MINIMERAD? (Win+D/Win+M i legacy-läge) → ÅTERSTÄLL!
            # OBS: IsWindowVisible är TRUE för minimerade fönster — därför
            # upptäckte inte gamla koden detta och fönstret kom aldrig tillbaka.
            with suppress(Exception):
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    self._log.warning(
                        f"{LOG_PREFIX} ⚠ FÖNSTRET VAR MINIMERAT (t.ex. Win+D) "
                        f"→ ÅTERSTÄLLT NU — skal {wid!r}, läge={mode}"
                    )

            # NY v7-fix44: legacy-läge = sårbart för Win+D → bevaka TÄTARE
            # (5 s) så fönstret alltid kommer tillbaka automatiskt.
            with suppress(Exception):
                _tm = getattr(shell, "_zorder_timer", None)
                if _tm is not None:
                    _want = 5000 if mode in ("normal", "top") else 30000
                    if _tm.interval() != _want:
                        _tm.setInterval(_want)

            if mode == "top":
                # alltid överst: se till att vi ligger kvar överst och syns
                # (men rör inte ett fönster som användaren själv har dolt)
                with suppress(Exception):
                    if not shell.isVisible():
                        return
                    user32.SetWindowPos(
                        hwnd, -1, 0, 0, 0, 0, 0x0040 | 0x0010 | 0x0001 | 0x0002,
                    )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
                return
            self._clear_topmost(hwnd)  # urkryssad 'Visa över andra appar' → aldrig topmost
            desktop_status = self._imports.get("desktop")
            if mode in ("above", "behind") and desktop_status and desktop_status.ok:
                if mode == "above":
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "attach_window_above_desktop_icons", None,
                    )
                    if fn and fn(hwnd):
                        with suppress(Exception):
                            if not user32.IsWindowVisible(hwnd):
                                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                        return
                else:
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "wedge_window_behind_desktop_icons", None,
                    )
                    if fn and fn(hwnd):
                        return

            # NY v7-fix56: legacy är BORTTAGET — utan desktop-lager
            # kör fönstret som vanligt toppfönster. Bevakning: endast
            # re-show om gömt/minimerat (ingen HWND_BOTTOM-push någonsin).
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                self._log.info(
                    f"{LOG_PREFIX} Desktop-shell re-show (var gömd)"
                )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # NY v7-fix38: SKAL-UTSEENDE (frameless + genomskinligt glas-skal)
    # -----------------------------------------------------------------------

    def _window_transparency_value(self) -> float:
        """NY v7-fix38: fönstertransparens 0.0–1.0 (0 = helt opak)."""
        try:
            if hasattr(self.settings, "window_transparency"):
                raw = float(self.settings.window_transparency())
            else:
                raw = float(self.settings.get("window_transparency", 0.85))
        except Exception:
            raw = 0.85
        if raw != raw:  # NaN-skydd
            raw = 0.85
        return max(0.0, min(1.0, raw))

    def _desktop_mode(self) -> str:
        """NY v7-fix38: aktuellt skrivbordsläge (above|behind|legacy)."""
        try:
            if hasattr(self.settings, "desktop_mode"):
                mode = str(self.settings.desktop_mode()).strip().lower()
            else:
                mode = str(
                    self.settings.get("desktop_mode", "above")
                ).strip().lower()
        except Exception:
            mode = "above"
        # v7-fix56: legacy är BORTTAGET — ogiltiga/legacy-värden → above
        return mode if mode in ("above", "behind", "top") else "above"

    def _apply_shell_appearance(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: frameless + genomskinligt glas-skal.

        MÅSTE anropas FÖRE show() — fönsterflaggor sätts innan det
        nativa fönstret skapas (inget extra CreateWindowEx-byte senare).

        transparens > 0 → WA_TranslucentBackground + WA_NoSystemBackground:
        hela fönstret blir ett genomskinligt glas-skal — skrivbordet och
        ikonerna syns igenom de rundade hörnen och den tonade panelen.
        """
        try:
            from PySide6.QtCore import Qt as _Qt
            transp = self._window_transparency_value()
            shell.setWindowFlag(_Qt.WindowType.FramelessWindowHint, True)
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_TranslucentBackground, transp > 0.0
            )
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_NoSystemBackground, transp > 0.0
            )
            shell._shell_transparency = transp
            self._log.info(
                f"{LOG_PREFIX} Skal {wid!r}: frameless + "
                f"transparens={transp:.2f} (v7-fix38)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _apply_shell_appearance misslyckades: {e}",
                exc_info=True,
            )

    def _schedule_shell_native_check(self, shell: Any, wid: str) -> None:
        """NY v7-fix38: fördröjd säkerhetskontroll av skal-fönstret."""
        try:
            self._QTimer.singleShot(
                900, lambda: self._verify_shell_native_window(shell, wid)
            )
        except Exception:
            pass

    def _verify_shell_native_window(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: verifiera att det genomskinliga skalet skapades.

        Historik (v7-fix7): Frameless+alpha kunde ge CreateWindowEx-fel
        på Rickards maskin (fönster-stormen). Skulle det hända igen
        nedgraderas skalet AUTOMATISKT till opak + desktop-lagret
        startas om — appen får aldrig dö av design-flaggor.
        """
        try:
            hwnd = 0
            with suppress(Exception):
                wh = shell.windowHandle()
                hwnd = int(wh.winId()) if wh is not None else 0
            ok = False
            if hwnd:
                import ctypes
                ok = bool(ctypes.windll.user32.IsWindow(hwnd))
            if ok:
                # Fönstret lever — komplettera med desktop-lager om det väntar
                if getattr(shell, "_desktop_layer_pending", False):
                    shell._desktop_layer_pending = False
                    self._apply_desktop_shell(shell, wid)
                return
            # FALLBACK: transparent skal kunde ej skapas
            self._log.critical(
                f"{LOG_PREFIX} Skal {wid!r}: nativt fönster SAKNAS efter "
                f"show() (CreateWindowEx-fel?) → faller tillbaka på opak "
                f"skal (v7-fix38 auto-fallback)"
            )
            from PySide6.QtCore import Qt as _Qt
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_TranslucentBackground, False
            )
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_NoSystemBackground, False
            )
            shell.setWindowFlag(_Qt.WindowType.FramelessWindowHint, False)
            shell._shell_transparency = 0.0
            with suppress(Exception):
                shell.show()
            self._apply_desktop_shell(shell, wid)
            # Widgeten ska måla om med opaka design-tokens
            _w = None
            with suppress(Exception):
                _w = self._widgets.get(wid)
            if _w is not None and hasattr(_w, "_apply_theme"):
                with suppress(Exception):
                    _w._apply_theme()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _verify_shell_native_window: {e}",
                exc_info=True,
            )

    def _reapply_shell_appearance(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: applicera om skal-utseendet LIVE.

        (dölj → nya flaggor → visa → desktop-lager igen)
        """
        try:
            with suppress(Exception):
                shell.hide()
            self._apply_shell_appearance(shell, wid)
            with suppress(Exception):
                shell.show()
            self._apply_desktop_shell(shell, wid)
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _reapply_shell_appearance misslyckades: {e}",
                exc_info=True,
            )

    def _reapply_desktop_shells(self) -> None:
        """NY v7-fix38: applicera skrivbordsläge + transparens live på alla skal."""
        try:
            with self._widget_lock:
                items = [
                    (wid, getattr(w, "_shell", None), w)
                    for wid, w in self._widgets.items()
                ]
            for _wid, _shell, _w in items:
                if _shell is not None:
                    self._reapply_shell_appearance(_shell, _wid)
            # Måla om widget-ytorna med nya alfa-tokens
            for _wid, _shell, _w in items:
                with suppress(Exception):
                    if hasattr(_w, "_apply_theme"):
                        _w._apply_theme()
            self._log.info(
                f"{LOG_PREFIX} _reapply_desktop_shells klar "
                f"(läge={self._desktop_mode()!r}, "
                f"transparens={self._window_transparency_value():.2f})"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _reapply_desktop_shells misslyckades: {e}",
                exc_info=True,
            )

    def _set_desktop_mode(self, mode: str) -> None:
        """NY v7-fix38: tray-handler — sätt skrivbordsläge live."""
        try:
            # v7-fix56: legacy borta — bara above/behind
            mode = mode if mode in ("above", "behind", "top") else "above"
            if hasattr(self.settings, "set_desktop_mode"):
                self.settings.set_desktop_mode(mode)
            self._reapply_desktop_shells()
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_desktop_mode misslyckades: {e}",
                exc_info=True,
            )

    def _set_window_transparency(self, value: float) -> None:
        """NY v7-fix38: tray-handler — sätt fönstertransparens live."""
        try:
            if hasattr(self.settings, "set_window_transparency"):
                self.settings.set_window_transparency(value)
            self._reapply_desktop_shells()
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_window_transparency misslyckades: {e}",
                exc_info=True,
            )

    def _desktop_mod(self, status: Any = None) -> Any:
        """
        NY v7-fix46: hämta desktop-MODULEN ur ImportStatus.

        ImportStatus.instance är en DICT ({modulnamn: modul}) när from_items
        ej angavs — ALL koden gjorde getattr() på själva dicten, vilket
        ALLTID misslyckades! Det gav falska "core/desktop.py är GAMMAL"-
        alarm trots att modulen var ny (och osynliggjorde ALL desktop-
        funktionalitet: desktop-lager, ikon-kollisioner m.m.).
        """
        try:
            st = status if status is not None else self._imports.get("desktop")
            if not st or not st.ok:
                return None
            inst = st.instance
            if isinstance(inst, dict):
                if "desktop" in inst:
                    return inst["desktop"]
                for _v in inst.values():
                    if _v is not None:
                        return _v
                return None
            return inst
        except Exception:
            return None

    def _float_window_above_apps(self) -> None:
        """
        NY v7-fix57: visa fönstret OVANPÅ appar tills vidare.

        Lossar fönstret från skrivbordslagret (ovanpå ikonerna) och
        gör det till ett vanligt fönster som du ser bland dina appar —
        praktiskt när du vill "hitta" widgeten eller jobba med den.
        Återgå med "📌 Fäst på skrivbordet igen".
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                if sys.platform == "win32":
                    with suppress(Exception):
                        import ctypes
                        from ctypes import wintypes as _wt
                        _u = ctypes.windll.user32
                        _hw = int(shell.winId())
                        if _hw and _u.GetAncestor(_hw, 2):
                            # FIX v7-fix62: las SKARM-positionen FORE
                            # lossningen — annars behaller Windows de
                            # Progman-relativa koordinaterna som tolkas
                            # som skarm-koordinater → fönstret hoppar
                            # +1920 px UTANFOR skärmen (osynligt)!
                            _pre = _wt.RECT()
                            _u.GetWindowRect(_hw, ctypes.byref(_pre))
                            _u.SetParent(_hw, 0)
                            # Aterstall exakt skarm-position
                            _u.SetWindowPos(
                                _hw, 0,
                                _pre.left, _pre.top, 0, 0,
                                0x0004 | 0x0010 | 0x0001,
                            )  # NOZORDER | NOACTIVATE | NOSIZE
                        # Visa + lyft (HWND_TOP — ej TOPMOST, ej påträngande)
                        _u.SetWindowPos(
                            _hw, 0, 0, 0, 0, 0,
                            0x0040 | 0x0010 | 0x0001 | 0x0002,
                        )  # SHOWWINDOW | NOACTIVATE | NOSIZE | NOMOVE
                shell._desktop_layer_mode = "normal"
                with suppress(Exception):
                    shell.show()
                    shell.raise_()
                self._log.info(
                    f"{LOG_PREFIX} {wid!r}: FLYTANDE LÄGE — ovanpå appar "
                    f"tills du väljer 'Fäst på skrivbordet' (v7-fix57)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _float_window_above_apps: {e}", exc_info=True
            )

    def _pin_window_to_desktop(self) -> None:
        """
        NY v7-fix57: fäst fönstret på skrivbordet igen (above-läget).
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                shell._desktop_layer_mode = None
                self._apply_desktop_shell(shell, wid)
                self._log.info(
                    f"{LOG_PREFIX} {wid!r}: FÄST PÅ SKRIVBORDET igen (v7-fix57)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _pin_window_to_desktop: {e}", exc_info=True
            )
