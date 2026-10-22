# -*- coding: utf-8 -*-
"""
ui/widget_parts/lifecycle.py — Start och uppbyggnad av fönstret: skärmanpassad storlek, förhandsdiagnostik, minimal/fas-2-UI och _init_ui.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class LifecycleMixin:
    """Start och uppbyggnad av fönstret: skärmanpassad storlek, förhandsdiagnostik, minimal/fas-2-UI och _init_ui."""

    # ====================================================================
    # INIT
    # ====================================================================

    @_log_call
    def _screen_adapted_size(self) -> Tuple[int, int]:
        """
        NY v7-fix24: beräkna widget-storlek anpassad efter AKTUELL skärm.

        Rickard 2026-09-29: "fönstret ska alltid anpassas efter
        skärmstorlek". Tidigare var DEFAULT_WIDGET_HEIGHT=650 hårkodad —
        på Rickards 864px-höga skärm överskred fönstret bottenkanten →
        CreateWindowEx 'Felaktig parameter' vid varje försök.

        Logik:
          Bredd: 340px standard, max 90% av skärmbredden
          Höjd:  650px standard, max 75% av skärmhöjden
          Minst: MIN_WIDGET_WIDTH x MIN_WIDGET_HEIGHT (280x400)
        """
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return (DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT)
            g = screen.geometry()
            sw, sh = g.width(), g.height()
            # Marginal för att alltid få plats
            margin = 40
            w = min(DEFAULT_WIDGET_WIDTH, sw - margin * 2)
            h = min(DEFAULT_WIDGET_HEIGHT, sh - margin * 2)
            # ALDRIG mindre än minimum (utom på extremt små skärmar)
            w = max(w, min(MIN_WIDGET_WIDTH, sw - margin))
            h = max(h, min(MIN_WIDGET_HEIGHT, sh - margin))
            logger.info(
                f"{LOG_PREFIX} _screen_adapted_size: skärm={sw}x{sh} "
                f"→ widget=({w}x{h})"
            )
            return (int(w), int(h))
        except Exception:
            return (DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT)

    def _preshow_diagnostic(self) -> bool:
        """
        NY v7-fix25: 100000000% bättre diagnostik — testar om ETT BART
        QWidget kan skapas på denna maskin FÖRE vi försöker med
        TodoWidget (som har barn, stilar, ikoner osv).

        Detta avgör OMEDELBART:
          BART FÖNSTER FUNGERAR → problemet är i TodoWidget:s setup
          BART FÖNSTER MISSLYCKAS → PySide6/Python kan INTE skapa
            fönster alls → åtgärd: pip install --upgrade PySide6

        Returnerar True om bart fönster skapades.
        """
        try:
            from PySide6.QtWidgets import QWidget as _QW
            test = _QW()
            test.setObjectName("DTPDiag")
            test.setWindowTitle("DTP-diag")
            test.resize(100, 50)
            test.show()

            # Kolla om fönstret faktiskt skapades
            _ok = False
            try:
                wh = test.windowHandle()
                _ok = wh is not None and int(wh.winId()) != 0
            except Exception:
                _ok = False

            if _ok:
                logger.info(
                    f"{LOG_PREFIX} ★ FÖRSHOW-DIAG: bart QWidget "
                    f"SKAPADES OK — miljön fungerar. Om TodoWidget "
                    f"misslyckas är problemet i vår widget-setup "
                    f"(barn/stilar/layout)."
                )
            else:
                logger.critical(
                    f"{LOG_PREFIX} ★★ FÖRSHOW-DIAG: bart QWidget "
                    f"MISSLYCKADES — PySide6/Python kan INTE skapa "
                    f"fönster på denna maskin! ÅTGÄRD: "
                    f"pip install --upgrade PySide6 (eller prova "
                    f"Python 3.12/3.13). Detta är INTE ett kod-fel."
                )
            with suppress(Exception):
                test.close()
                test.deleteLater()
            return _ok
        except Exception as e:
            logger.error(f"{LOG_PREFIX} förshow-diag fel: {e}")
            return False

    def _init_ui_minimal(self) -> None:
        """
        FIX v7-fix26 (FAS 1): Skapa ett MINIMALT fönster — inga barn,
        inga stilar, inga layouter. Visa DET FÖRST.

        FÖRSHOW-DIAG bevisade att bart QWidget funkar på Rickards maskin.
        Problemet var att TodoWidget byggde ALLA barn FÖRE show().
        Nu: visa tomt fönster → NÄR det syns → bygg innehållet (fas 2).
        """
        logger.info(
            f"{LOG_PREFIX} _init_ui_minimal START (win_id={self.win_id})"
        )
        self.setWindowTitle(self.DEFAULT_TITLE)
        _w, _h = self._screen_adapted_size()
        self.resize(_w, _h)
        self._restore_window_position()
        self._validate_position_on_screens()
        logger.info(
            f"{LOG_PREFIX} _init_ui_minimal: bart fönster klart "
            f"({self.width()}x{self.height()}) @ ({self.x()},{self.y()})"
        )

    def _initial_render(self) -> None:
        """
        FIX v8 (2026-10-12): visa sparade uppgifter DIREKT när appen öppnas.

        Listan ritades tidigare aldrig om efter att UI:t byggts — uppgifterna
        syntes först när man skrev en ny (som utlöste en ombyggnad). Nu ritas
        den en gång direkt, och en gång till när fönstret hunnit visas.
        """
        try:
            with suppress(Exception):
                logger.info(
                    f"{LOG_PREFIX} start: {len(self.store.active_tasks())} aktiva, "
                    f"{len(self.store.archive_tasks())} arkiverade uppgifter "
                    f"i datamappen {self.store.data_dir}"
                )
            self._rebuild_task_list()
            QTimer.singleShot(400, self._rebuild_task_list)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _initial_render misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _init_ui_phase2(self) -> None:
        """
        FIX v7-fix26 (FAS 2): Bygg HELA UI:et — körs NÄR fönstret syns.
        """
        if not getattr(self, "_phase2_pending", False):
            return
        self._phase2_pending = False
        logger.info(
            f"{LOG_PREFIX} _init_ui_phase2 START — fönster OK, bygger UI"
        )
        try:
            self._init_ui()
            self._build_search_index()
            self._apply_theme()
            self._initial_render()
            logger.info(
                f"{LOG_PREFIX} _init_ui_phase2 KLAR — full UI på plats"
            )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _init_ui_phase2 misslyckades: {e}",
                exc_info=True,
            )

    def _init_ui(self) -> None:
        """
        Bygg UI-träd (FAS 2 — körs EFTER att fönstret syns via showEvent).

        FIX v7-fix26: Titel/storlek/position sätts i _init_ui_minimal
        (fas 1). Här byggs BARA barn-layouten.
        """
        logger.info(
            f"{LOG_PREFIX} _init_ui START (win_id={self.win_id})"
        )
        _adapted_w, _adapted_h = self._screen_adapted_size()
        self.setMinimumSize(
            min(MIN_WIDGET_WIDTH, _adapted_w),
            min(MIN_WIDGET_HEIGHT, _adapted_h),
        )
        self.resize(_adapted_w, _adapted_h)
        logger.info(
            f"{LOG_PREFIX} _init_ui: skärm-anpassad size satt "
            f"(min={min(MIN_WIDGET_WIDTH, _adapted_w)}x"
            f"{min(MIN_WIDGET_HEIGHT, _adapted_h)}, "
            f"resize={_adapted_w}x{_adapted_h})"
        )
        # NY v6.4.1: Ladda sparad position från settings + validera mot skärmar
        # FIX: widget skapades tidigare på Qt:s default-position (ofta offscreen
        # på multi-monitor) — nu använder vi saved pos från window_configs.
        self._restore_window_position()
        self._validate_position_on_screens()
        logger.info(
            f"{LOG_PREFIX} _init_ui: position efter validering "
            f"=({self.x()},{self.y()}) size=({self.width()}x{self.height()})"
        )
        # NY v6.4: Storlekspolicy (Expanding = kan växa)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        # NY v6.4: Mouse cursor vid kanter (för att visa att fönstret kan resizeas)
        self.setMouseTracking(True)
        # Layout — luftigare glass-design (2026-09-24)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        # Title-rad: appnamn + drag-hint + lock (kompakt header)
        handle_row = QHBoxLayout()
        handle_row.setSpacing(8)
        title_lbl = QLabel(APP_NAME, self)
        title_lbl.setObjectName("dragHandle")
        title_lbl.setFixedHeight(28)
        title_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        title_lbl.setToolTip(
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Klicka och dra för att flytta.\n"
            "Esc = göm  •  F3 = Focus Mode  •  ← / → = prioritet"
        )
        self.drag_handle = title_lbl
        handle_row.addWidget(title_lbl)
        hint = QLabel("·  dra för att flytta", self)
        hint.setObjectName("dragHandle")
        hint.setFixedHeight(28)
        hint.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        handle_row.addWidget(hint, 1)
        # NY v7-fix17: live-stats-chip ("X aktiva · Y klara")
        self.stats_chip = QLabel("", self)
        self.stats_chip.setObjectName("statsChip")
        self.stats_chip.setToolTip(
            "Antal uppgifter — uppdateras automatiskt"
        )
        handle_row.addWidget(self.stats_chip)
        # Lock-knapp (toggle lås/lås upp)
        self.lock_btn = QPushButton("🔒", self)
        self.lock_btn.setObjectName("lockBtn")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setFixedSize(34, 28)
        self.lock_btn.setToolTip(
            "Lås fönstret (klicka igen för att låsa upp)\n\n"
            "Låst = fönstret kan INTE flyttas av misstag\n"
            "Shift+drag = tillfälligt förbigå låset\n"
            "Auto-relock efter 30s när du låser upp"
        )
        self.lock_btn.clicked.connect(self._toggle_lock)
        handle_row.addWidget(self.lock_btn)
        root.addLayout(handle_row)
        # NY v7-fix86: tunn progress-bar under headern — % klara av
        # aktiva uppgifter (visuell feedback i samma design-språk som
        # PDF-checklistan). Uppdateras i _update_stats_chip.
        self.progress_bar = QFrame(self)
        self.progress_bar.setObjectName("headerProgress")
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setProperty("pct", 0)
        root.addWidget(self.progress_bar)
        # Search
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(
            "🔍  Sök uppgifter (titel eller tagg)…"
        )
        self.search_input.setToolTip(
            "Sok i uppgiftstitlar och taggar. Tomt = visa alla."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        root.addWidget(self.search_input)
        # NY v6.4.1: StackedWidget med 2 sidor (Normal + Focus Mode)
        self.content_stack = QStackedWidget(self)
        self.content_stack.addTab = self.content_stack.addWidget  # alias
        # Sida 0: Normal (tabs)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_active_tab(), "Aktiva")
        self.tabs.addTab(self._build_archive_tab(), "Arkiverade")
        self.tabs.setTabToolTip(
            1, "Historik: klara uppgifter sparas här för alltid (de tas aldrig bort)"
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.content_stack.addWidget(self.tabs)
        # Sida 1: Focus Mode (1 task stort + nav-knappar)
        self._focus_view = self._build_focus_view()
        self.content_stack.addWidget(self._focus_view)
        self.content_stack.setCurrentIndex(0)  # Start: Normal
        root.addWidget(self.content_stack, 1)
        # Input + priority (Fas 2: 3 prickar + piltangenter för val)
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self.input_field = QLineEdit(self)
        # v7-fix10: objectName MÅSTE sättas här (i _init_ui) — sattes
        # tidigare först EFTER setStyleSheet() i _apply_theme, vilket
        # gjorde att QSS-regeln QLineEdit#inputField aldrig träffade
        # (synliga felet: ostylad VIT ruta längst ner i mörkt tema).
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText(
            "➕ Skriv ny uppgift här — Enter för att spara"
        )
        self.input_field.setToolTip(
            "Skriv en uppgift och tryck Enter.\n"
            "← / → byter prioritet fore save (rod → gul → gron → gra).\n"
            "Valfritt startdatum (för kalendern): skriv t.ex.\n"
            "  byt vindruta start nästa vecka   ·   start måndag   ·   start 19/10"
        )
        self.input_field.returnPressed.connect(self._on_input_submit)
        # Fas 2: Piltangenter ←/→ i input-fältet byter pending prioritet
        self.input_field.keyPressEvent = self._input_field_keypress  # type: ignore[assignment]
        input_row.addWidget(self.input_field, 1)
        # Fas 2: Input priority indicator (stor färgprick + 3 små prickar)
        self._pending_input_priority: str = "none"
        # Huvudpricken (stor, klickbar)
        self.input_priority_dot = PriorityDot(
            task_id="__input__",
            priority=self._pending_input_priority,
            parent=self,
        )
        self.input_priority_dot.setFixedSize(28, 28)
        self.input_priority_dot.priority_dot_clicked.connect(
            self._on_input_priority_dot_clicked
        )
        # Override paintEvent för större storlek
        original_paint = self.input_priority_dot.paintEvent
        def _big_paint(ev):
            p = QPainter(self.input_priority_dot)
            if not p.isActive():
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor(PRIORITY_COLORS.get(
                self._pending_input_priority, "#6b7280"
            ))
            cx, cy = 14, 14
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPoint(cx, cy), 8, 8)
            # Yttre ring
            ring = QColor(color)
            ring.setAlpha(60)
            p.setBrush(ring)
            p.drawEllipse(QPoint(cx, cy), 11, 11)
        self.input_priority_dot.paintEvent = _big_paint  # type: ignore[assignment]
        input_row.addWidget(self.input_priority_dot)
        # Fas 2: 3 små prickar (röd/gul/grön) för snabbval
        self._input_priority_dots: List[PriorityDot] = []
        for p in ("high", "medium", "low"):
            dot = PriorityDot(
                task_id=f"__input_{p}__",
                priority=p,
                parent=self,
            )
            dot.setFixedSize(18, 18)
            # Override paint för mindre storlek
            def _make_small_paint(prio):
                def _paint(ev, prio=prio):
                    p = QPainter(dot)
                    if not p.isActive():
                        return
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    color = QColor(PRIORITY_COLORS.get(prio, "#6b7280"))
                    cx, cy = 9, 9
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(color)
                    p.drawEllipse(QPoint(cx, cy), 5, 5)
                return _paint
            dot.paintEvent = _make_small_paint(p)  # type: ignore[assignment]
            dot.priority_dot_clicked.connect(
                lambda _tid, new_p, _p=p: self._set_input_priority(_p)
            )
            self._input_priority_dots.append(dot)
            input_row.addWidget(dot)
        # Fas 2: Enter bekräftar (alla prickar utlöser samma submit)
        self._update_input_priority_indicator()

        # NY v7-fix35: E-post-import-knapp 📧
        self.email_import_btn = QPushButton("📧", self)
        self.email_import_btn.setObjectName("emailImportBtn")
        self.email_import_btn.setFixedSize(28, 28)
        self.email_import_btn.setToolTip(
            "Importera e-post (.eml eller .msg) som uppgift —\n"
            "eller använd Thunderbird-tillägget / mappen data/inbox/\n"
            "(tray-menyn → 📧 E-post & Thunderbird)\n"
            "Outlook: spara mailet som .msg eller dra till skrivbordet\n"
            "Thunderbird: spara mailet som .eml"
        )
        self.email_import_btn.clicked.connect(self._on_email_import)
        input_row.addWidget(self.email_import_btn)
        # NY v7-fix81: PDF-export-knapp bredvid 📧 (samma som tray-menyn)
        self.pdf_export_btn = QPushButton("📄", self)
        self.pdf_export_btn.setObjectName("pdfExportBtn")
        self.pdf_export_btn.setFixedSize(28, 28)
        self.pdf_export_btn.setToolTip(
            "Exportera aktiva uppgifter som PDF-checklista\n"
            "(finns även i tray-menyn + högerklick på fönstret)"
        )
        self.pdf_export_btn.clicked.connect(self._on_export_pdf)
        input_row.addWidget(self.pdf_export_btn)
        root.addLayout(input_row)
        # NY v6.4: Resize-grip i nedre högra hörnet (synlig indikator)
        from PySide6.QtWidgets import QSizeGrip
        self.size_grip = QSizeGrip(self)
        # Lägg i en liten corner-layout
        corner_layout = QHBoxLayout()
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.addStretch(1)
        corner_layout.addWidget(self.size_grip)
        root.addLayout(corner_layout)
        # NY v6.4.1 v4: Window flags för sticky desktop-widget
        #
        # Krav fran Rickard 2026-09-18:
        #   1. Inte gomma vid Win+D (visa skrivbordet)
        #   2. Alltid synlig pa skrivbordet (overst, men inte over andra fönster)
        #   3. Kunna lyftas fram vid klick
        #
        # Teknik (NY v6.4.1 v4):
        #   - Tool = WS_EX_TOOLWINDOW (visas inte i taskbar/alt-tab)
        #   - Widgets kategoriseras som utility (inte som app)
        #   - Override WM_SYSCOMMAND för att blockera minimize
        #   - Periodic re-show timer som säkrar synlighet vid Win+D
        # NY v6.4.1 v5: Window flags för sticky desktop-widget
        #
        # Krav (Rickard 2026-09-18):
        #   - Alltid synlig pa SKRIVBORDET (aldrig gomd vid Win+D)
        #   - BAKOM andra fonster (vanligt z-beteende)
        #   - Lyssna pa klick → bring_to_front() tar fokus
        #
        # NY v6.4.1 v7-fix7: ENDAST Qt.Window — INTE Tool / FramelessWindowHint.
        # Orsak: Tool|FramelessWindowHint → WS_POPUP + WS_EX_TOOLWINDOW + alpha →
        #   CreateWindowEx misslyckas pa vissa Win10-skarmar ("Felaktig parameter"),
        #   och spammas 25+ ggr/100ms nar populate-loopen kor. WS_OVERLAPPED (Qt.Window)
        #   skapas alltid korrekt. Ram + header handlas av GlassFrame.paintEvent +
        #   custom titlebar-widget (drag-handtag + min/max/close). HWND_BOTTOM + z-order
        #   skots i _setup_bugg19_zorder precis som tidigare.
        #
        # Hur Win+D-skyddet fungerar:
        #   1. WS_EX_NOACTIVATE → fokuseras inte automatiskt vid klick
        #   2. nativeEvent() blockerar SC_MINIMIZE → Win+D ignorerar widget
        #   3. _periodic_zorder_check() re-show:ar om nagon app gomt oss
        # FIX v7-fix20: INGA explicita setWindowFlags/setAttribute här!
        # En föräldralös QWidget är REDAN ett fönster (default Qt.Window).
        # Den explicita flag-KONVERTERINGEN kan vara trasig i vissa
        # PySide6/Python 3.14-kombinationer → flags blir 0 (=
        # 'QFlags<Qt::WindowType>()' i fel-loggen!) → WS_CHILD utan
        # förälder → CreateWindowEx 'Felaktig parameter' vid varje
        # försök. Vi rör den inte — och loggar de effektiva flagsen.
        logger.info(
            f"{LOG_PREFIX} windowFlags (default, ej explicit satta): "
            f"{int(self.windowFlags())} "
            f"(Qt.Window={int(Qt.WindowType.Window)})"
        )
        # FIX 2026-09-23: app-ikon → aktivitetsfält + Aktivitetshanterare
        # (QIcon från data/app.ico om den finns — annars default)
        try:
            _ico = (
                getattr(__import__("pathlib"), "Path")(__file__)
                .resolve().parent.parent / "data" / "app.ico"
            )
            if _ico.is_file():
                from PySide6.QtGui import QIcon as _QI
                # FIX v7-fix19: validera — korrupt .ico kan ge ogiltig
                # HICON → CreateWindowEx 'Felaktig parameter'-storm
                _icon = _QI(str(_ico))
                if _icon.isNull() or _icon.pixmap(32, 32).isNull():
                    logger.warning(
                        f"{LOG_PREFIX} app.ico OGILTIG — hoppar över "
                        f"ikon (korrupt ikon kan ge "
                        f"CreateWindowEx-fel!)"
                    )
                else:
                    # FIX v7-fix22: ikonen sätts INTE här (före show) —
                    # en förgiftad ikon i fönsterklassen vid registrering
                    # dödar ALLA CreateWindowEx. main sätter den efter
                    # att fönstret faktiskt skapats.
                    logger.info(
                        f"{LOG_PREFIX} Widget-ikon förberedd (sätts "
                        f"efter show, v7-fix22): {_ico}"
                    )
        except Exception as _ico_err:
            logger.debug(f"{LOG_PREFIX} widget-ikon: {_ico_err}")
        # FIX 2026-09-23: WA_NoSystemBackground togs bort — gav
        # "QWidget::paintEngine: Should no longer be called" +
        # "QPainter::begin: engine == 0" med translucent + native HWND.
        # FIX v7-fix18: _setup_bugg19_zorder() körs INTE längre före
        # show() — den anropas från showEvent. Att tvinga fram ett nativt
        # fönster FÖRE show() (via winId()) är en CreateWindowEx-
        # omförsöksvektor när fönstret inte kan skapas.
        self._install_win_d_blocker()
        # FIX 2026-09-25: visa widgeten direkt vid start
        # (Rickard: "fönstret ska alltid synas på skrivbordet så fort man startar")
        try:
            self.show()
            logger.info(
                f"{LOG_PREFIX} _init_ui: show() anropad — "
                f"widget visas vid start"
            )
        except Exception as _se:
            logger.warning(f"{LOG_PREFIX} _init_ui show(): {_se}")
        # NY v6.4.1 v7: Verifiera att widgeten faktiskt är synlig
        # FIX v7-fix18: körs nu EFTER show() och ENDAST om fönstret finns
        # — winId() på ett trasigt fönster tvingar fram nya misslyckade
        # CreateWindowEx-försök (= logg-stormen).
        try:
            import ctypes
            if self._native_window_ok():
                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                is_visible = bool(user32.IsWindowVisible(hwnd))
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                logger.info(
                    f"{LOG_PREFIX} _init_ui: HWND={hwnd} visible={is_visible} "
                    f"rect=({rect.left},{rect.top})-({rect.right},{rect.bottom}) "
                    f"size={width}x{height}"
                )
            else:
                logger.warning(
                    f"{LOG_PREFIX} _init_ui: nativt fönster SAKNAS efter "
                    f"show() — karantän sköts av showEvent (v7-fix18)"
                )
        except Exception as _e:
            logger.warning(f"{LOG_PREFIX} _init_ui HWND-verifiering misslyckades: {_e}")
        logger.info(
            f"{LOG_PREFIX} _init_ui klar (v7: skrivbords-widget + z-order + Win+D-skydd)"
        )
