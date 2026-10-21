# -*- coding: utf-8 -*-
"""
ui/widget_parts/keys_position.py — Sök-token, tangenttryck, z-ordning (BUGG 19) samt återställning och validering av fönsterposition.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class KeysPositionMixin:
    """Sök-token, tangenttryck, z-ordning (BUGG 19) samt återställning och validering av fönsterposition."""

    def _tokenize_task(self, task: Dict[str, Any]) -> Set[str]:
        """Tokenize en task (title + tags)."""
        tokens: Set[str] = set()
        title = task.get("title", "")
        if title:
            tokens.update(self._tokenize_cached(title))
        for tag in task.get("tags", []):
            tokens.add(tag.lower())
        return tokens

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def _tokenize_cached(text: str) -> FrozenSet[str]:
        """NY v6.4.1 v7-fix: Cache-ad tokenisering for snabbare sokning."""
        return frozenset(
            tok.lower()
            for tok in re.split(r"[\s\.,;:!\?\-/]+", text)
            if tok
        )

    def _focus_search(self) -> None:
        """Fokusera sokfaltet."""
        if hasattr(self, "search_input"):
            self.search_input.setFocus()
            self.search_input.selectAll()
            logger.debug(f"{LOG_PREFIX} sokfaltet fokuserat")

    # ====================================================================
    # EVENT HANDLERS (NY v6.4.1 v7 - forbattrade med AI-felsökning)
    # ====================================================================

    @_log_event("event:key_press")
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """NY v6.4.1 v7: Tangentbord (med full spårning 2026-09-24).
        Hanterar: Esc→stäng, ↑/↓→navigera, ←/→→prioritet."""
        try:
            get_throttle().notify_activity()
            # FIX 2026-09-24: logga ALLA tangenter (Rickard 199999%)
            # FIX v7-fix39: crash-säker — Qt.Key(_k) kan kasta för
            # okända tangentkoder; int() på enum finns ej i PySide6
            _k = event.key()
            _kn = f"key={_k}"
            with suppress(Exception):
                _kn = getattr(Qt.Key(_k), "name", None) or _kn
            _mods = []
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                _mods.append("Shift")
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                _mods.append("Ctrl")
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                _mods.append("Alt")
            _txt = event.text() if hasattr(event, "text") else ""
            logger.debug(
                f"{LOG_PREFIX} keyPress key={_kn} text={_txt!r} "
                f"mods={'+'.join(_mods) or '-'} "
                f"focus={'search' if self.search_input.hasFocus() else 'content'}"
            )
            if self._handle_nav_key(event):
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape and not self.search_input.hasFocus():
                logger.debug(f"{LOG_PREFIX} Esc → _on_close_clicked")
                self._on_close_clicked()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._navigate_tasks(event.key())
                event.accept()
                return
            super().keyPressEvent(event)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} keyPressEvent misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    def _setup_bugg19_zorder(self) -> None:
        """
        NY v6.4.1 v7-fix6: HWND_BOTTOM + WS_EX_NOACTIVATE
        (sitter alltid på skrivbordet, under fokuserade appar).

        Rickard 2026-09-25: "syns men försvinner när man klickar
        någonstans, ska alltid ligga överst på skrivbordet".

        Approach (v7-fix6):
          1. Sätt WS_EX_NOACTIVATE (TOOLWINDOW borta i v7-fix7 — vi använder Qt.Window)
             → fönstret på desktop-root, fokuseras INTE automatiskt
          2. Sätt HWND_BOTTOM (under andra windows UTAN TOPMOST-läget)
             → Fokuserade appar går naturligt Ovanpå widgeten
          3. Reparenta från WorkerW (om vi blivit parentad dit)
          4. Diagnostik post: HWND, visible, pos, monitor
        """
        # FIX 2026-09-25 v7-fix7: reentrancy-skydd (showEvent→zorder→moveEvent→save
        # → signal → populate → show() → showEvent → zorder… kan loopa).
        if getattr(self, "_zorder_running", False):
            logger.debug(
                f"{LOG_PREFIX} _setup_bugg19_zorder: redan igång, skip"
            )
            return
        self._zorder_running = True
        try:
            if sys.platform != "win32":
                return
            # FIX v7-fix29: barn → SKALET hanterar z-order, vi hoppar över
            if self._is_child():
                logger.debug(
                    f"{LOG_PREFIX} zorder: barn-läge, skalet hanterar"
                )
                return
            # FIX v7-fix18: tvinga ALDRIG fram fönster-skapande här —
            # om fönstret är trasigt går vi i karantän i stället.
            if not self._native_window_ok():
                self._handle_window_creation_failure()
                return
            import ctypes
            hwnd = int(self.winId())
            logger.info(
                f"{LOG_PREFIX} _setup_bugg19_zorder START: HWND={hwnd}, "
                f"win_id={self.win_id}, _force_show={self._force_show}"
            )
            if hwnd == 0:
                logger.warning(
                    f"{LOG_PREFIX} _setup_bugg19_zorder: HWND=0"
                )
                return
            user32 = ctypes.windll.user32
            # === Reparenta från WorkerW (Explorer-ikon-lager) ===
            try:
                current_parent = user32.GetParent(hwnd)
                if current_parent:
                    user32.SetParent(hwnd, 0)
                    logger.info(
                        f"{LOG_PREFIX} _setup_bugg19_zorder: "
                        f"HWND={hwnd} reparentad till desktop-rot "
                        f"(var parentad till 0x{int(current_parent):X})"
                    )
            except Exception as _rp_err:
                logger.debug(f"{LOG_PREFIX} reparent: {_rp_err}")

            # === Sätt Extended Style: NOACTIVATE ===
            # NY v6.4.1 v7-fix7: WS_EX_TOOLWINDOW borttagen — vi anvander Qt.Window
            # (WS_OVERLAPPED), inte Qt.Tool (WS_POPUP+TOOLWINDOW). Toolwindow behovs
            # inte langre eftersom vi inte vill gomma i alt-tab (icke-Tool fonster
            # ar redan dar synligt). NOACTIVATE kvar sa att klick pa widgeten inte
            # stjal fokus fran andra appar — Rickards krav: ligga pa skrivbordet
            # UTAN att stora.
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_TOPMOST = 0x00000008
            try:
                current_ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            except Exception:
                current_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_ex = current_ex
            # Rensa TOPMOST, Rensa TOOLWINDOW (om Qt satte det via WindowFlags), sätt NOACTIVATE
            new_ex = (new_ex & ~WS_EX_TOPMOST) & ~WS_EX_TOOLWINDOW
            new_ex = new_ex | WS_EX_NOACTIVATE
            if new_ex != current_ex:
                try:
                    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_ex)
                except Exception:
                    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)
                logger.info(
                    f"{LOG_PREFIX} _setup_bugg19_zorder: "
                    f"WS_EX (0x{current_ex:X} → 0x{new_ex:X})"
                )

            # === Z-order: HWND_BOTTOM (under fokuserade appar) ===
            # HWND_BOTTOM (1) = längst ner i normal z-order.
            # Andra appar som fokuseras hamnar naturligt ovanför.
            # Rickard 2026-09-25: "ska alltid ligga överst på skrivbordet"
            # — här menas skrivbords-nivån, inte över alla appar.
            HWND_BOTTOM = 1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            ret = user32.SetWindowPos(
                hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            # ShowWindow garanterar synlig även om SetWindowPos misslyckades
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            user32.ShowWindow(hwnd, 5)  # SW_SHOW

            # Diagnostik
            try:
                is_visible = bool(user32.IsWindowVisible(hwnd))
                rect_post = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect_post))
                width = rect_post.right - rect_post.left
                height = rect_post.bottom - rect_post.top
                class _MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.c_ulong),
                        ("rcMonitor", ctypes.wintypes.RECT),
                        ("rcWork", ctypes.wintypes.RECT),
                        ("dwFlags", ctypes.c_ulong),
                    ]
                monitor = user32.MonitorFromWindow(hwnd, 2)
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
                widget_on_monitor = (
                    rect_post.left < mi.rcMonitor.right
                    and rect_post.right > mi.rcMonitor.left
                    and rect_post.top < mi.rcMonitor.bottom
                    and rect_post.bottom > mi.rcMonitor.top
                )
                logger.info(
                    f"{LOG_PREFIX} _setup_bugg19_zorder DIAGNOSTIK POST: "
                    f"HWND={hwnd} visible={is_visible} "
                    f"rect=({rect_post.left},{rect_post.top})-{rect_post.right},{rect_post.bottom})"
                    f"size={width}x{height} "
                    f"mon_rect=({mi.rcMonitor.left},{mi.rcMonitor.top})-"
                    f"({mi.rcMonitor.right},{mi.rcMonitor.bottom}) "
                    f"widget_on_monitor={widget_on_monitor} "
                    f"setpos_ret={ret} z=BOTTOM"
                )
                if not widget_on_monitor:
                    new_x = mi.rcMonitor.left + 100
                    new_y = mi.rcMonitor.top + 100
                    user32.SetWindowPos(
                        hwnd, 0, new_x, new_y, 0, 0,
                        0x0040 | 0x0010,
                    )
                    logger.info(
                        f"{LOG_PREFIX} _setup_bugg19_zorder: "
                        f"flyttad till ({new_x},{new_y})"
                    )
            except Exception as _post_err:
                logger.warning(
                    f"{LOG_PREFIX} post-diagnostik misslyckades: {_post_err}"
                )
            logger.info(
                f"{LOG_PREFIX} BUGG 19 v7-fix6 z-order: HWND={hwnd} "
                f"→ HWND_BOTTOM (skrivbordet, under appar) ret={ret}"
            )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _setup_bugg19_zorder misslyckades: {e}",
                exc_info=True,
            )
        finally:
            # FIX 2026-09-25 v7-fix7: släpp reentrancy-lås alltid
            self._zorder_running = False

    def _restore_window_position(self) -> None:
        """NY v6.4.1: Ladda sparad (x,y,w,h) fran settings.window_configs()."""
        x, y = 100, 100
        w, h = DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT
        try:
            if not hasattr(self.settings, "window_configs"):
                logger.info(f"{LOG_PREFIX} _restore_window_position: settings saknar window_configs()")
            else:
                configs = self.settings.window_configs() or []
                for conf in configs:
                    if isinstance(conf, dict) and conf.get("id") == self.win_id:
                        x = int(conf.get("x", x))
                        y = int(conf.get("y", y))
                        w = int(conf.get("w", w))
                        h = int(conf.get("h", h))
                        logger.info(f"{LOG_PREFIX} _restore_window_position: win_id={self.win_id} → ({x},{y}) {w}x{h}")
                        break
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _restore_window_position misslyckades: {e}")
        # NY v7-fix47: x/y < 0 = centrerings-sentinel (första start)
        # → barnet sätter INGEN egen geometri; main centrerar SKALET.
        if x < 0 or y < 0:
            logger.info(
                f"{LOG_PREFIX} _restore_window_position: centrerings-"
                f"läge (första start) — main positionerar skalet"
            )
            return
        # FIX v7-fix18: HÅRDA GRÄNSER på geometrin. Ogiltiga värden från
        # settings.json (w=0, negativa eller enorma tal) gör att
        # CreateWindowEx misslyckas med "Felaktig parameter" vid VARJE
        # försök — det är den eviga fönster-stormen i loggen.
        _orig = (x, y, w, h)
        w = max(MIN_WIDGET_WIDTH, min(w, MAX_RESTORE_WIDTH))
        h = max(MIN_WIDGET_HEIGHT, min(h, MAX_RESTORE_HEIGHT))
        x = max(-30000, min(x, 30000))
        y = max(-30000, min(y, 30000))
        # FIX v7-fix24: storleken FÅR ALDRIG överskrida skärmen —
        # "fönstret ska alltid anpassas efter skärmstorlek"
        try:
            _scr = QGuiApplication.primaryScreen()
            if _scr is not None:
                _sg = _scr.geometry()
                # Bredd: max 90% av skärmen
                w = min(w, int(_sg.width() * 0.9))
                # Höjd: max 75% av skärmen (marginal för aktivitetsfält)
                h = min(h, int(_sg.height() * 0.75))
                w = max(w, min(MIN_WIDGET_WIDTH, _sg.width() - 60))
                h = max(h, min(MIN_WIDGET_HEIGHT, _sg.height() - 60))
                # Position: HELA fönstret måste synas
                y = min(y, _sg.y() + _sg.height() - h - 30)
                x = min(x, _sg.x() + _sg.width() - w - 30)
                y = max(y, _sg.y() + 30)
                x = max(x, _sg.x() + 30)
        except Exception:
            pass  # ingen skärm tillgänglig ännu
        # FIX v7-fix23: y+h FÅR INTE överskrida skärmens höjd —
        # AdjustWindowRectExForDpi() vid 125% kan annars producera
        # ogiltig rektangel → CreateWindowEx ERROR_INVALID_PARAMETER.
        try:
            _scr = QGuiApplication.primaryScreen()
            if _scr is not None:
                _sg = _scr.geometry()
                _max_y = _sg.y() + _sg.height() - h - 30
                if y > _max_y:
                    logger.warning(
                        f"{LOG_PREFIX} _restore_window_position: "
                        f"y={y} + h={h} överskrider skärm "
                        f"(höjd={_sg.height()}) → klamrar y till {_max_y}"
                    )
                    y = max(_sg.y() + 30, _max_y)
                _max_x = _sg.x() + _sg.width() - w - 30
                if x > _max_x:
                    x = max(_sg.x() + 30, _max_x)
        except Exception:
            pass  # ingen skärm tillgänglig ännu — _validate tar hand om det
        if (x, y, w, h) != _orig:
            logger.warning(
                f"{LOG_PREFIX} _restore_window_position: OGILTIG geometri "
                f"{_orig} → klamrad till ({x},{y}) {w}x{h} (orsakar "
                f"'CreateWindowEx failed' vid varje försök!)"
            )
            with suppress(Exception):
                if hasattr(self.settings, "update_window_position"):
                    self.settings.update_window_position(
                        self.win_id, x, y
                    )
        _shell_r = getattr(self, "_shell", None)
        if _shell_r is not None:
            _shell_r.move(x, y)
            _shell_r.resize(w, h)
        else:
            self.move(x, y)
            self.resize(w, h)

    def _validate_position_on_screens(self) -> None:
        """
        Validera att HELA fönstret (x, y, x+w, y+h) syns på en skärm.

        FIX v7-fix23 (CreateWindowEx-stormen DEL 5 — ROTEN!):
        Tidigare kontrollerades bara att ÖVRE VÄNSTRA hörnet (x,y) var
        på skärmen. Men en widget vid (1121,545) med höjd 650 på en
        864px-hög skärm överskrider botten med 331px! Vid dpr=1.25 blir
        den fysiska bottenkanten 1494px men skärmen är bara 1080px →
        AdjustWindowRectExForDpi() producerar ogiltig rektangel →
        CreateWindowEx ERROR_INVALID_PARAMETER = den eviga stormen.

        Nu: kontrollera att HELA fönstret får plats. Om inte → flytta
        till en position där det gör det (primära skärmens topp-vänster
        + marginal), och spara den korrigerade positionen.

        FIX v7-fix76 (Rickards logg 2026-10-06 16:40 — 3 buggar):
          a) BARN-LÄGE (skal-mönstret, v7-fix27): self.x()/y() är LOKALA
             koordinater (relativt skalet) men jämfördes mot GLOBALA
             skärm-rectar → falsk "ÖVERSKRIDER SKÄRM" vid varje start,
             barnet flyttades till (30,30) INUTI skalet och lokala
             koordinater sparades i settings! Nu: barnet valideras ej —
             SKALET (main) äger den globala positionen (v7-fix47/62).
          b) Margin-kravet (30 px in från kanten) gjorde helt giltiga
             kant-/hörnpositioner "ogiltiga" — t.ex. (0,0) =
             skrivbordshörnen, helt normal plats för en desktop-widget!
             Marginal fordras numera ENDAST för räddningspositionen.
          c) Varningsraden tryckte "botten=648 > höjd=1080" (matematiskt
             osant — det var X-ledet mot fel skärm som misslyckades).
             Raden redovisar nu verklig global rect + närmaste skärm.
        """
        try:
            # FIX v7-fix76a: BARN-LÄGE — hoppa över helt. Skalet äger
            # positionen; main har eget off-screen-skydd (v7-fix62) och
            # barnet fyller alltid skalet (0,0 → skalstorlek).
            if self.parentWidget() is not None:
                logger.info(
                    f"{LOG_PREFIX} _validate_position: BARN-LÄGE — "
                    f"skalet (main) äger global position, barnet "
                    f"valideras/flyttas ej (v7-fix76)"
                )
                return
            screens = QGuiApplication.screens()
            x, y = self.x(), self.y()
            w, h = self.width(), self.height()
            screen_rects = []
            for screen in screens:
                g = screen.geometry()
                screen_rects.append((g.x(), g.y(), g.width(), g.height()))
            logger.info(
                f"{LOG_PREFIX} _validate_position: {len(screen_rects)} "
                f"skärmar, pos=({x},{y}) size=({w}x{h}), rects={screen_rects}"
            )
            # FIX v7-fix23: HELA fönstret måste få plats (inte bara hörnet)
            # FIX v7-fix76b: kantflush ÄR giltigt (x == sx räcker) —
            # ingen marginal fordras för giltigheten.
            fully_visible = False
            for sx, sy, sw, sh in screen_rects:
                if (
                    x >= sx
                    and y >= sy
                    and (x + w) <= (sx + sw)
                    and (y + h) <= (sy + sh)
                ):
                    fully_visible = True
                    break
            if fully_visible:
                logger.info(
                    f"{LOG_PREFIX} _validate_position: ({x},{y}) {w}x{h} "
                    f"HELT synlig ✓"
                )
                return
            # Fönstret överskrider skärm — flytta + logga tydligt
            primary = QGuiApplication.primaryScreen()
            if primary is not None:
                pg = primary.geometry()
                # Räddningsposition: primära skärmens topp-vänster +
                # 30 px marginal (om fönstret är större än skärmen
                # hamnar det ändå längst upp-vänster och Qt klipper)
                new_x = pg.x() + 30
                new_y = pg.y() + 30
                # FIX v7-fix76c: redovisa VERKLIG orsak — skärmen med
                # störst överlapp + vilka mått som faktiskt spricker
                _best = None
                _best_area = -1
                for sx, sy, sw, sh in screen_rects:
                    _ov = max(0, min(x + w, sx + sw) - max(x, sx)) * max(
                        0, min(y + h, sy + sh) - max(y, sy)
                    )
                    if _ov > _best_area:
                        _best_area = _ov
                        _best = (sx, sy, sw, sh)
                if _best is not None:
                    bsx, bsy, bsw, bsh = _best
                    logger.warning(
                        f"{LOG_PREFIX} _validate_position: global "
                        f"({x},{y}) {w}x{h} får inte plats helt på någon "
                        f"skärm (närmaste {_best}: höger {x + w} vs "
                        f"{bsx + bsw}, botten {y + h} vs {bsy + bsh}) "
                        f"→ flyttar till ({new_x},{new_y}) så hela "
                        f"fönstret syns (v7-fix23/76)"
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} _validate_position: global "
                        f"({x},{y}) {w}x{h} ligger utanför alla skärmar "
                        f"→ flyttar till ({new_x},{new_y}) (v7-fix23/76)"
                    )
                self.move(new_x, new_y)
                if hasattr(self.settings, "update_window_position"):
                    try:
                        self.settings.update_window_position(
                            self.win_id, new_x, new_y
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"{LOG_PREFIX} _validate_position misslyckades: {e}", exc_info=True)
