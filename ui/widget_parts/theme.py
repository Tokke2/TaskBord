# -*- coding: utf-8 -*-
"""
ui/widget_parts/theme.py — Tema och utseende: automatiskt tema och _apply_theme (QSS, textstorlek, densitet).

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class ThemeMixin:
    """Tema och utseende: automatiskt tema och _apply_theme (QSS, textstorlek, densitet)."""

    @_log_call
    def _check_auto_theme(self) -> None:
        """
        NY v7-fix82: klockstyrt tema — växla utan omstart.

        Körs var 10:e minut (se _init_timers). Gäller ENDAST när
        användaren valt 'Auto' i tray-menyn (settings theme='auto'):
        07:00–18:59 = ljust, 19:00–06:59 = mörkt. theme()/is_dark()
        i settings löser värdet; här detekteras GRÄNSÖVERSKRIDANDET
        (sparat _theme_is_dark ≠ aktuellt) → _apply_theme() om.
        """
        try:
            raw = None
            with suppress(Exception):
                if hasattr(self.settings, "theme_raw"):
                    raw = self.settings.theme_raw()
            if raw != "auto":
                return  # auto ej valt — gör ingenting
            want_dark = None
            with suppress(Exception):
                if hasattr(self.settings, "is_dark"):
                    want_dark = bool(self.settings.is_dark())
            if want_dark is None:
                return
            current = bool(getattr(self, "_theme_is_dark", not want_dark))
            if want_dark != current:
                logger.info(
                    f"{LOG_PREFIX} Auto-tema: klockan passerade "
                    f"gränsen → växlar till "
                    f"{'mörkt' if want_dark else 'ljust'} (v7-fix82)"
                )
                self._apply_theme()
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _check_auto_theme: {e}")

    def _apply_theme(self) -> None:
        """
        NY v6.4.1 v7: Applicera tema + proffsig glass-design (2026-09-24).

        Rickard: "designen på fönstret ska vara bättre".
        Använder settings.stylesheet() som bas + widget-specifik QSS
        (header, tabs, sök, input, uppgiftskort) — färger via accent-palette (R3).
        """
        try:
            is_dark = (
                self.settings.is_dark()
                if hasattr(self.settings, "is_dark")
                else True
            )
            accent = (
                self.settings.accent_color()
                if hasattr(self.settings, "accent_color")
                else "indigo"
            )
            # Etapp 10 (v7-fix10): design-tokens + accent via GLASS_ACCENTS
            accent_hex = GLASS_ACCENTS.get(accent, "#818cf8")
            t = _glass_tokens(is_dark)
            # NY v7-fix38: genomskinligt skal → skala panelens bas-alfa
            # så skrivbordsikonerna syns igenom glaset
            self._transparency_factor: float = self._window_transparency_factor()
            t = _tokens_with_transparency(t, self._transparency_factor)
            _radius_css: str = (
                "border-radius: 14px;" if self._transparency_factor > 0.0 else ""
            )
            # NY v7-fix17: spara tema för paintEvent-auroran + accent-tinter
            self._theme_is_dark: bool = is_dark
            self._theme_accent_hex: str = accent_hex
            tab_tint = _hex_rgba(accent_hex, 0.17 if is_dark else 0.14)
            tab_edge = _hex_rgba(accent_hex, 0.45)

            base_qss = ""
            if hasattr(self.settings, "stylesheet"):
                try:
                    base_qss = self.settings.stylesheet()
                except Exception:
                    base_qss = ""

            # Prioritets-regler genereras ur PRIORITY_COLORS + tint-dictar
            # (ett enda ställe att justera kulörerna på).
            prio_rules = ""
            # NY v8: ALLA rader (även "ingen prio") får färgad vänsterkant.
            # Hög prioritet får tjockare kant (5px) för tydligare markering.
            for _prio in ("high", "medium", "low", "none"):
                _edge = PRIORITY_COLORS[_prio]
                _edge_w = 5 if _prio == "high" else 3
                prio_rules += (
                    f'QFrame[taskCard="true"][taskPriority="{_prio}"] {{ '
                    f"background-color: {PRIORITY_ROW_TINT[_prio]}; "
                    f"border: 1px solid {t['surface_edge']}; "
                    f"border-left: {_edge_w}px solid {_edge}; }} "
                    f'QFrame[taskCard="true"][taskPriority="{_prio}"]:hover {{ '
                    f"background-color: {PRIO_HOVER_TINT[_prio]}; "
                    f"border: 1px solid {t['edge_hov']}; "
                    f"border-left: {_edge_w}px solid {_edge}; }} "
                )

            # NY v7-fix41: deadline-ring (röd=övertruten, orange=idag)
            due_rules = (
                'QFrame[taskCard="true"][taskDue="overdue"] { '
                "background-color: rgba(239, 68, 68, 0.15); "
                "border: 1px solid rgba(239, 68, 68, 0.65); "
                "border-left: 3px solid #ef4444; } "
                'QFrame[taskCard="true"][taskDue="today"] { '
                "background-color: rgba(245, 158, 11, 0.12); "
                "border: 1px solid rgba(245, 158, 11, 0.55); "
                "border-left: 3px solid #f59e0b; } "
            )

            # NY v7-fix41: ⋯-knapp, snooze/återkommande-badges, delmoment
            fix41_rules = (
                "QPushButton#taskMenuBtn { "
                f"background: {t['surface']}; "
                f"border: 1px solid {t['surface_edge']}; "
                "border-radius: 9px; "
                "font-size: 13px; font-weight: 700; "
                f"color: {t['muted']}; }} "
                "QPushButton#taskMenuBtn:hover { "
                f"background: {t['surface_hov']}; "
                f"border: 1px solid {t['edge_hov']}; }} "
                "QLabel#snoozeBadge { "
                "background: rgba(129, 140, 248, 0.16); "
                "border: 1px solid rgba(129, 140, 248, 0.35); "
                f"color: {t['muted']}; "
                "border-radius: 8px; padding: 1px 7px; "
                "font-size: 10px; font-weight: 600; } "
                "QLabel#recBadge { background: transparent; "
                "font-size: 12px; } "
                f"QLabel#subtaskTitle {{ color: {t['muted']}; "
                "font-size: 12px; } "
                f"QLabel#subtaskProgress {{ color: {t['muted']}; "
                "font-size: 10px; font-weight: 600; } "
                "QLabel#subtaskDoneAll { color: #34d399; "
                "font-size: 10px; font-weight: 600; } "
                f"QLabel#taskDate {{ color: {t['muted']}; "
                "font-size: 10px; font-weight: 500; } "
            )

            self.setObjectName("TodoWidget")
            _dp_qss = _density_profile(self.settings)
            _sel_bg = _hex_rgba(accent_hex, 0.20 if is_dark else 0.14)
            widget_qss = f"""
                /* ============ ETAPP 10 — MODERN FROSTED GLASS (v7-fix10) ===== */
                QWidget#TodoWidget {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['bg_top']}, stop:1 {t['bg_bottom']});
                    color: {t['fg']};
                    border: none;
                    {_radius_css}
                    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
                    font-size: 13px;
                }}
                QLabel#dragHandle {{
                    background: transparent;
                    color: {t['fg']};
                    font-size: 12px;
                    font-weight: 700;
                    border: none;
                    padding: 2px 4px;
                }}
                QLabel#dragHint {{
                    background: transparent;
                    color: {t['hint']};
                    font-size: 10px;
                    font-weight: 400;
                    border: none;
                    padding: 2px 0;
                }}
                QLabel#statsChip {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    color: {t['muted']};
                    border-radius: 9px;
                    padding: 3px 9px;
                    font-size: 10px;
                    font-weight: 600;
                }}
                QPushButton#lockBtn {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 9px;
                    font-size: 13px;
                    padding: 2px 6px;
                    min-width: 28px;
                }}
                QPushButton#lockBtn:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#lockBtn:checked {{
                    background: {accent_hex};
                    color: white;
                    border: 1px solid {accent_hex};
                }}
                QLineEdit#searchInput, QLineEdit#inputField {{
                    background: {t['field_bg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 12px;
                    padding: 9px 14px;
                    font-size: 13px;
                    color: {t['fg']};
                    placeholder-text-color: {t['muted']};
                    selection-background-color: {accent_hex};
                    selection-color: white;
                }}
                QLineEdit#searchInput:hover, QLineEdit#inputField:hover {{
                    border: 1px solid {t['edge_hov']};
                }}
                QLineEdit#searchInput:focus, QLineEdit#inputField:focus {{
                    border: 1.5px solid {accent_hex};
                    background: {t['field_focus']};
                }}
                QTabWidget::pane {{
                    border: none;
                    border-top: 1px solid {t['divider']};
                    background: transparent;
                    top: -1px;
                }}
                QTabBar {{ background: transparent; border: none; }}
                QTabBar::tab {{
                    background: transparent;
                    color: {t['muted']};
                    padding: 7px 16px;
                    margin: 2px 3px 2px 0;
                    border: 1px solid transparent;
                    border-radius: 10px;
                    font-weight: 600;
                    font-size: 12px;
                }}
                QTabBar::tab:selected {{
                    background: {tab_tint};
                    color: {accent_hex};
                    border: 1px solid {tab_edge};
                }}
                QTabBar::tab:hover:!selected {{
                    color: {t['fg_hov']};
                    background: {t['surface']};
                }}
                QScrollArea {{ border: none; background: transparent; }}
                QScrollArea > QWidget > QWidget {{ background: transparent; }}
                QScrollBar:vertical {{
                    background: transparent;
                    width: 10px;
                    margin: 2px;
                }}
                QScrollBar::handle:vertical {{
                    background: {t['surface_edge']};
                    border-radius: 5px;
                    min-height: 28px;
                }}
                QScrollBar::handle:vertical:hover {{ background: {accent_hex}; }}
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {{ height: 0; }}
                /* --- Uppgiftskort (glas-cards) -------------------------------- */
                QFrame[taskCard="true"] {{
                    background-color: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 12px;
                    padding: {_dp_qss['card_pad']};
                    margin: {_dp_qss['card_margin']};
                }}
                QFrame[taskCard="true"]:hover {{
                    background-color: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                {prio_rules}
                {due_rules}
                {fix41_rules}
                /* Fästa (pinned) uppgifter — amber-glas; kommer EFTER
                   prioritets-reglerna = vinner vid konflikt. */
                QFrame[taskCard="true"][pinned="true"] {{
                    background-color: rgba(251, 191, 36, 0.10);
                    border: 1px solid rgba(251, 191, 36, 0.55);
                    border-left: 3px solid #fbbf24;
                }}
                QFrame[taskCard="true"][pinned="true"]:hover {{
                    background-color: rgba(251, 191, 36, 0.17);
                    border: 1px solid rgba(251, 191, 36, 0.80);
                    border-left: 3px solid #fbbf24;
                }}
                /* Markerad uppgift (tangentbordsnavigering ↑/↓) */
                QFrame[taskCard="true"][taskSelected="true"],
                QFrame[taskCard="true"][taskSelected="true"]:hover {{
                    background-color: {_sel_bg};
                    border-top: 2px solid {accent_hex};
                    border-right: 2px solid {accent_hex};
                    border-bottom: 2px solid {accent_hex};
                }}
                QLabel#taskTitle {{
                    color: {t['fg']};
                    font-size: 12px;
                    font-weight: 600;
                    border: none;
                    background: transparent;
                    padding: 0;
                }}
                QFrame[taskCard="true"][taskDone="true"] QLabel#taskTitle {{
                    color: {t['muted']};
                    font-weight: 400;
                    text-decoration: line-through;
                }}
                QLabel#pinBadge {{
                    background: transparent;
                    color: #fbbf24;
                    font-size: 12px;
                    border: none;
                    padding: 0;
                }}
                QLabel#emptyHint {{
                    color: {t['muted']};
                    font-style: italic;
                    padding: 24px;
                    border: none;
                    background: transparent;
                }}
                /* --- Checkbox (målad glas-indikator) -------------------------- */
                QCheckBox {{
                    background: transparent;
                    spacing: 0;
                }}
                QCheckBox::indicator {{
                    width: 22px;
                    height: 22px;
                    border-radius: 7px;
                    border: 2px solid {t['edge_hov']};
                    background: {t['field_bg']};
                }}
                QCheckBox::indicator:hover {{
                    border: 2px solid {accent_hex};
                }}
                QCheckBox::indicator:checked {{
                    background: {accent_hex};
                    border: 2px solid {accent_hex};
                }}
                /* --- Focus Mode-knappar --------------------------------------- */
                QPushButton#emailImportBtn, QPushButton#emailBadge {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 9px;
                    font-size: 14px;
                    padding: 2px;
                }}
                QPushButton#emailImportBtn:hover, QPushButton#emailBadge:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#focusNav {{
                    background: {t['surface']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 10px;
                    padding: 8px 12px;
                    font-weight: 600;
                }}
                QPushButton#focusNav:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#focusDone {{
                    background: rgba(16, 185, 129, 0.78);
                    color: white;
                    border: 1px solid rgba(16, 185, 129, 0.95);
                    border-radius: 10px;
                    padding: 8px 14px;
                    font-weight: 700;
                }}
                QPushButton#focusDone:hover {{
                    background: rgba(16, 185, 129, 0.95);
                }}
                /* --- Menyer + tooltips (prioritetsmeny m.m.) ------------------ */
                QMenu {{
                    background: {t['field_focus']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 10px;
                    padding: 4px;
                }}
                QMenu::item {{ padding: 6px 24px; border-radius: 6px; }}
                QMenu::item:selected {{ background: {accent_hex}; color: white; }}
                QToolTip {{
                    background: {t['field_focus']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 6px;
                    padding: 4px 8px;
                }}
                QSizeGrip {{
                    background: transparent;
                    width: 14px;
                    height: 14px;
                }}
                """
            # v7-fix10: objectNames MÅSTE vara satta FÖRE setStyleSheet()
            # (annars hinner QSS-reglerna #inputField m.fl. aldrig träffa).
            import contextlib as _ctx
            with _ctx.suppress(Exception):
                if hasattr(self, "drag_handle"):
                    self.drag_handle.setObjectName("dragHandle")
                if hasattr(self, "lock_btn"):
                    self.lock_btn.setObjectName("lockBtn")
                    self.lock_btn.setCheckable(True)
                if hasattr(self, "search_input"):
                    self.search_input.setObjectName("searchInput")
                if hasattr(self, "input_field"):
                    self.input_field.setObjectName("inputField")
                if getattr(self, "_glass", None) is not None:
                    self._glass.set_theme(is_dark, accent_hex)

            # NY: textstorlek (Kompakt/Normal/Stor) skalar alla font-size i widget-QSS
            # (skalan ligger kvar i widget_base — där läses den av _scaled_px)
            _ui_scale = set_ui_font_scale(_dp_qss["font"])
            widget_qss = _scale_font_sizes(widget_qss, _ui_scale)
            self.setStyleSheet(base_qss + widget_qss)

            logger.info(
                f"{LOG_PREFIX} tema+design applicerat: "
                f"dark={is_dark}, accent={accent}"
            )
            self._audit.add(
                "theme_applied", {"is_dark": is_dark, "accent": accent}
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _apply_theme misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
            try:
                self.setStyleSheet(
                    "QWidget { background-color: #1a1a2e; color: white; }"
                )
            except Exception:
                pass
