# -*- coding: utf-8 -*-
"""
ui/widget_atoms.py — små UI-klasser till TodoWidget (delad ur ui/widget.py):
EditableLabel, InlineTitleEdit, TagChip, PriorityBadge, PriorityDot, DueDateLabel, GlassFrame.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403


# ===========================================================================
# EDITABLE LABEL (dubbelklick → edit)
# ===========================================================================

if _QT_AVAILABLE:
    class EditableLabel(QLabel):
        """Label med inline-redigering (dubbelklick)."""

        editing_finished = Signal(str)  # Emitteras vid Enter/Esc
        editing_started = Signal()

        @_log_call
        def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
            super().__init__(text, parent)
            self._editor: Optional[QLineEdit] = None
            self._original_text: str = text
            self.setMouseTracking(True)
            self._apply_style()

        @_log_event("editable_label:start_edit")
        def _start_edit(self) -> None:
            if self._editor is not None:
                return
            self._original_text = self.text()
            self._editor = QLineEdit(self._original_text, self)
            self._editor.setFrame(False)
            self._editor.selectAll()
            self._editor.setStyleSheet(
                "QLineEdit { background: transparent; border: 1px solid #818cf8; }"
            )
            self._editor.setGeometry(self.rect())
            self._editor.show()
            self._editor.setFocus()
            self._editor.editingFinished.connect(self._on_editing_finished)
            self._editor.returnPressed.connect(self._finish_edit)
            self.editing_started.emit()
            logger.trace(f"{LOG_PREFIX} EditableLabel: start edit")

        @_log_event("editable_label:finish_edit")
        def _finish_edit(self) -> None:
            if self._editor is None:
                return
            new_text = self._editor.text().strip()
            self._cleanup_editor()
            self.setText(new_text)
            self.editing_finished.emit(new_text)
            logger.trace(
                f"{LOG_PREFIX} EditableLabel: finish edit → {new_text!r}"
            )

        @_log_event("editable_label:cancel_edit")
        def _cancel_edit(self) -> None:
            if self._editor is None:
                return
            self._cleanup_editor()
            self.setText(self._original_text)
            self.editing_finished.emit(self._original_text)
            logger.trace(f"{LOG_PREFIX} EditableLabel: cancel edit")

        def _on_editing_finished(self) -> None:
            if self._editor is not None and not self._editor.hasFocus():
                self._finish_edit()

        def _cleanup_editor(self) -> None:
            if self._editor is not None:
                with suppress(Exception):
                    self._editor.deleteLater()
                self._editor = None

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            self._start_edit()
            event.accept()

        def keyPressEvent(self, event: QKeyEvent) -> None:
            get_throttle().notify_activity()
            if self._editor is not None and event.key() == Qt.Key.Key_Escape:
                self._cancel_edit()
                event.accept()
            else:
                super().keyPressEvent(event)

        def _apply_style(self) -> None:
            self.setStyleSheet("QLabel { padding: 4px; }")

else:
    class EditableLabel:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        editing_finished = None
        editing_started = None


# ===========================================================================
# INLINE TITEL-EDITOR (dubbelklick / F2 på ett kort)
# ===========================================================================

if _QT_AVAILABLE:
    class InlineTitleEdit(QLineEdit):
        """
        Redigerar en uppgiftstitel PÅ PLATS (läggs ovanpå titeln på kortet).

        Enter sparar, Esc avbryter, klick utanför sparar. ``committed`` skickas högst en gång
        (``by_enter`` säger om det var Enter) och ``cancelled`` skickas vid Esc.
        Alltid mörk text på ljus botten → läsbar i både mörkt och ljust tema.
        """

        committed = Signal(str)
        cancelled = Signal()

        def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
            super().__init__(text, parent)
            self._done = False
            self.by_enter = False
            self.setObjectName("inlineTitleEdit")
            self.setMaxLength(500)
            self.setToolTip("Enter = spara · Esc = avbryt")
            self.setStyleSheet(
                "QLineEdit#inlineTitleEdit { background: #ffffff; color: #111827; "
                "border: 2px solid #818cf8; border-radius: 6px; padding: 2px 6px; "
                "selection-background-color: #c7d2fe; selection-color: #111827; }"
            )
            self.returnPressed.connect(self._on_return)
            self.editingFinished.connect(self._commit)

        def _on_return(self) -> None:
            self.by_enter = True
            self._commit()

        def _commit(self) -> None:
            if self._done:
                return
            self._done = True
            self.committed.emit(self.text().strip())

        def event(self, e: QEvent) -> bool:
            # Enter/Esc får inte stjälas av fönstrets kortkommandon — rutan tar dem själv
            if e.type() == QEvent.Type.ShortcutOverride and e.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
            ):
                e.accept()
                return True
            return super().event(e)

        def keyPressEvent(self, event: QKeyEvent) -> None:
            if event.key() == Qt.Key.Key_Escape:
                if not self._done:
                    self._done = True
                    self.cancelled.emit()
                event.accept()
                return
            super().keyPressEvent(event)

else:
    class InlineTitleEdit:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass


# ===========================================================================
# TAG CHIP
# ===========================================================================

if _QT_AVAILABLE:
    class TagChip(QLabel):
        """Färgkodad tag-chip (klickbar)."""

        clicked = Signal(str)

        @_log_call
        def __init__(
            self, text: str, color_index: int = 0, parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(text, parent)
            self._text: str = text
            self._color_index: int = color_index % len(TAG_COLORS)
            self._active: bool = False
            self.setMouseTracking(True)
            self._apply_style()

        def set_active(self, active: bool) -> None:
            self._active = active
            self._apply_style()
            logger.trace(
                f"{LOG_PREFIX} TagChip {self._text!r}: active={active}"
            )

        def _apply_style(self) -> None:
            # Etapp 10 (v7-fix10): moderna glas-chips — tonad färgyta +
            # kant i samma kulör, vit text läsbar på mörkt/ljust.
            # OBS: rgba()-strängar (ej QColor.NameFormat) — funkar i
            # PySide6/PyQt6/PyQt5 utan versionsberoende.
            base = _qcolor_from_rgba(TAG_COLORS[self._color_index])
            bg_a = 205 if self._active else 150
            edge_a = 255 if self._active else 170
            self.setStyleSheet(
                f"QLabel {{ "
                f"background-color: rgba({base.red()}, {base.green()}, "
                f"{base.blue()}, {bg_a}); "
                f"color: #ffffff; "
                f"border: 1px solid rgba({base.red()}, {base.green()}, "
                f"{base.blue()}, {edge_a}); "
                f"padding: 2px 9px; border-radius: 9px; "
                f"font-size: {_scaled_px(10)}px; font-weight: 600; }}"
            )

        def mousePressEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            self.clicked.emit(self._text)
            event.accept()


# ===========================================================================
# LINK / ATTACHMENT CHIP (🔗 länk, 📎 bilaga)
# ===========================================================================

if _QT_AVAILABLE:
    class LinkChip(QLabel):
        """Klickbar chip för en länk (🔗) eller bilaga (📎). Vänsterklick öppnar, högerklick ger menyn.

        Stilen kommer från temat (objectName ``linkChip`` / ``attachChip``) så texten alltid är läsbar.
        """

        clicked = Signal(str)                 # key (url eller filens relativa sökväg)
        menu_requested = Signal(str, object)  # key, global position
        MAX_CHARS: ClassVar[int] = 30

        def __init__(
            self, text: str, key: str, kind: str = "link", tooltip: str = "",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self._key = key
            self._kind = kind
            self.setObjectName("attachChip" if kind == "attachment" else "linkChip")
            self.setProperty("chipKind", kind)
            self.setText(self.elide(text, self.MAX_CHARS))
            self.setToolTip(tooltip or key)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        @staticmethod
        def elide(text: str, n: int) -> str:
            t = " ".join(str(text or "").split())
            if len(t) <= n:
                return t
            head = (n - 1) * 2 // 3
            return t[:head] + "…" + t[-(n - 1 - head):]

        def key(self) -> str:
            return self._key

        def mousePressEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            if event.button() == Qt.MouseButton.RightButton:
                self.menu_requested.emit(self._key, event.globalPosition().toPoint())
            elif event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self._key)
            event.accept()


# ===========================================================================
# PRIORITY BADGE
# ===========================================================================

if _QT_AVAILABLE:
    class PriorityBadge(QWidget):
        """Färgad 4px vertikal remsa (vänsterkant)."""

        @_log_call
        def __init__(
            self, priority: str = "medium", parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(parent)
            self._priority: str = priority
            self.setFixedWidth(4)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self._apply_style()

        def set_priority(self, priority: str) -> None:
            self._priority = priority
            self._apply_style()
            logger.trace(f"{LOG_PREFIX} PriorityBadge: {priority}")

        def _apply_style(self) -> None:
            color = PRIORITY_COLORS.get(self._priority, "#94a3b8")
            self.setStyleSheet(f"background-color: {color}; border: none;")


    class PriorityDot(QWidget):
        """
        Fas 2 (v6.4): Klickbar färgprick (12px cirkel) som visar prioritet.

        Beteende:
          • Visar färg baserat på prioritet (grå om 'none')
          • Klick → cyklar prioritet (none → high → medium → low → none)
          • Högerklick → context-meny med alla 4 alternativ
          • Sänder signal priority_dot_clicked(task_id, new_priority) till förälder

        Allt synligt alltid (även 'none'/grå), så användaren ser att den finns.
        """

        # Signal: (task_id, new_priority)
        priority_dot_clicked = Signal(str, str)
        priority_dot_right_clicked = Signal(str, str)  # (task_id, current_priority)

        @_log_call
        def __init__(
            self,
            task_id: str,
            priority: str = "none",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self._task_id: str = task_id
            self._priority: str = priority
            self.setFixedSize(20, 20)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(self._tooltip_text())
            self._apply_style()

        def set_priority(self, priority: str) -> None:
            self._priority = priority
            self._apply_style()
            self.setToolTip(self._tooltip_text())
            logger.trace(
                f"{LOG_PREFIX} PriorityDot({self._task_id!r}): {priority}"
            )

        def priority(self) -> str:
            return self._priority

        def _tooltip_text(self) -> str:
            return (
                f"Prioritet: {self._priority.upper()}\n"
                f"Klicka för att byta  •  Högerklick för meny"
            )

        def _apply_style(self) -> None:
            color = PRIORITY_COLORS.get(self._priority, "#6b7280")
            # 12px rund prick, centrerad, med subtil ring runt om
            self.setStyleSheet(
                f"background: transparent; border: none;"
            )
            # Själva pricken ritas i paintEvent för att kunna ha anti-aliasing

        def paintEvent(self, event: QPaintEvent) -> None:
            get_throttle().notify_activity()
            p = QPainter(self)
            if not p.isActive():
                # FIX 2026-09-23: paintEngine==0 (native/translucent) → hoppa över
                logger.debug(f"{LOG_PREFIX} PriorityDot.paintEvent: QPainter ej aktiv")
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color_hex = PRIORITY_COLORS.get(self._priority, "#6b7280")
            cx, cy, r = 10, 10, 6
            if self._priority == "none":
                # NY: ihålig ring för "ingen prioritet" (skiljer sig i form, inte bara färg)
                ring_pen = QPen(QColor(color_hex))
                ring_pen.setWidthF(1.6)
                p.setPen(ring_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPoint(cx, cy), r, r)
                return
            # Yttre ring (subtil, alltid synlig — visar att det är interaktivt)
            ring_color = QColor(color_hex)
            ring_color.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color_hex))
            # Inre pricken (12px diameter, centrerad i 20x20)
            p.drawEllipse(QPoint(cx, cy), r, r)
            # Yttre ring (16px diameter, svag alpha)
            p.setBrush(ring_color)
            p.drawEllipse(QPoint(cx, cy), r + 2, r + 2)
            # NY: symbol per prioritet (text i vitt inuti pricken)
            glyph = PRIORITY_SYMBOLS.get(self._priority, "")
            if glyph:
                sym_font = QFont(p.font())
                sym_font.setBold(True)
                sym_font.setPixelSize(9)
                p.setFont(sym_font)
                p.setPen(QColor("#ffffff"))
                p.drawText(
                    QRect(0, 0, 20, 20), Qt.AlignmentFlag.AlignCenter, glyph
                )

        def mousePressEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            if event.button() == Qt.MouseButton.LeftButton:
                # Cykla prioritet: none → high → medium → low → none
                idx = PRIORITY_CYCLE.index(self._priority) if self._priority in PRIORITY_CYCLE else 0
                new_p = PRIORITY_CYCLE[(idx + 1) % len(PRIORITY_CYCLE)]
                logger.info(
                    f"{LOG_PREFIX} PriorityDot klick: {self._task_id!r} "
                    f"{self._priority} → {new_p}"
                )
                self.priority_dot_clicked.emit(self._task_id, new_p)
                event.accept()
            elif event.button() == Qt.MouseButton.RightButton:
                self.priority_dot_right_clicked.emit(
                    self._task_id, self._priority
                )
                event.accept()
            else:
                super().mousePressEvent(event)

        def enterEvent(self, event):
            """Hover: förstorar pricken något."""
            self.setFixedSize(22, 22)
            super().enterEvent(event)
            self.update()

        def leaveEvent(self, event):
            """Lämna hover: återställ storlek."""
            self.setFixedSize(20, 20)
            super().leaveEvent(event)
            self.update()


# ===========================================================================
# DUE DATE LABEL
# ===========================================================================

if _QT_AVAILABLE:
    class DueDateLabel(QLabel):
        """Etikett med due_date-formatering."""

        @_log_call
        def __init__(
            self,
            due_date: Optional[str] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__("", parent)
            self._due_date: Optional[str] = None
            self.set_due_date(due_date)

        def set_due_date(self, due_date: Optional[str]) -> None:
            self._due_date = due_date
            self._apply()

        def _apply(self) -> None:
            if not self._due_date:
                self.setText("")
                self.setStyleSheet("color: transparent;")
                return
            try:
                d = datetime.fromisoformat(self._due_date).date()
            except (ValueError, TypeError):
                self.setText(self._due_date)
                return
            today = datetime.now().date()
            delta = (d - today).days
            if delta < 0:
                color = "#ef4444"
                text = f"⚠ Förfallen {abs(delta)}d"
            elif delta == 0:
                color = "#f59e0b"
                text = "📅 I dag"
            elif delta == 1:
                color = "#f59e0b"
                text = "📅 Imorgon"
            elif delta < 7:
                color = "#94a3b8"
                text = f"📅 {delta}d"
            else:
                color = "#94a3b8"
                text = f"📅 {d.strftime('%Y-%m-%d')}"
            self.setText(text)
            # Etapp 10 (v7-fix10): tydligare datum-etikett (vikt 600 + genomskinlig bakgrund)
            self.setStyleSheet(
                f"color: {color}; font-size: {_scaled_px(10)}px; font-weight: 600; "
                f"border: none; background: transparent; padding: 0 2px;"
            )


# ===========================================================================
# GLASS FRAME
# ===========================================================================

if _QT_AVAILABLE:
    class GlassFrame(QFrame):
        """
        Frosted glass-ram — målade lager, ingen OS-transparens (Etapp 10).

        RIKTIG glas-känsla målas i paintEvent (lager uppifrån och ner):
          1. Vertikal bas-gradient (ljusare topp, djup botten)
          2. Radial accent-glow uppe i centrum ("aurora", svag)
          3. Rundad huvudyta med anti-aliasing
          4. 1px ram i tonad accentfärg
          5. Specular-highlight — 1px ljus linje längs överkanten (glaskant)
          6. Inner-skugga — 1px mörk linje längs nederkanten (djup)

        OBS: WA_TranslucentBackground är medvetet AV (v7-fix7) — frosted-
        känslan målas helt med QPainter på en ogenomskinlig yta. Inga
        WS_POPUP/alpha-krav → CreateWindowEx kan aldrig faila av designen.
        """

        @_log_call
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._is_dark: bool = True
            self._accent_color: str = "#818cf8"
            self._radius: int = 14
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        def set_theme(self, is_dark: bool, accent: str) -> None:
            self._is_dark = is_dark
            self._accent_color = accent
            self.update()

        def paintEvent(self, event: QPaintEvent) -> None:
            get_throttle().notify_activity()
            p = QPainter(self)
            if not p.isActive():
                logger.debug(f"{LOG_PREFIX} GlassFrame.paintEvent: QPainter ej aktiv")
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect()
            if rect.width() < 4 or rect.height() < 4:
                return
            t = _glass_tokens(self._is_dark)
            accent = QColor(self._accent_color)
            body = rect.adjusted(1, 1, -1, -1)
            radius = float(self._radius)

            # --- Lager 1: vertikal bas-gradient -----------------------------
            grad = QLinearGradient(0.0, 0.0, 0.0, float(rect.height()))
            grad.setColorAt(0.0, _qcolor_from_rgba(t["bg_top"]))
            grad.setColorAt(1.0, _qcolor_from_rgba(t["bg_bottom"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 2: radial accent-glow ("aurora") uppe i centrum ------
            glow = QRadialGradient(
                float(body.center().x()), float(body.top()),
                max(float(body.width()) * 0.75, 1.0),
            )
            glow_c = QColor(accent)
            glow_c.setAlpha(30 if self._is_dark else 46)
            glow_end = QColor(accent)
            glow_end.setAlpha(0)
            glow.setColorAt(0.0, glow_c)
            glow.setColorAt(1.0, glow_end)
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 3: tonad 1px ram i accent ----------------------------
            frame_c = QColor(accent)
            frame_c.setAlpha(110 if self._is_dark else 130)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(frame_c, 1))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 4: specular-highlight (glaskant längs överkanten) ----
            spec = QColor(255, 255, 255)
            spec.setAlpha(40 if self._is_dark else 220)
            p.setPen(QPen(spec, 1))
            p.drawLine(
                QPoint(int(body.left() + radius), int(body.top() + 1.5)),
                QPoint(int(body.right() - radius), int(body.top() + 1.5)),
            )

            # --- Lager 5: inner-skugga längs nederkanten (djup) -------------
            shadow = QColor(0, 0, 0)
            shadow.setAlpha(70 if self._is_dark else 28)
            p.setPen(QPen(shadow, 1))
            p.drawLine(
                QPoint(int(body.left() + radius), int(body.bottom() - 1)),
                QPoint(int(body.right() - radius), int(body.bottom() - 1)),
            )


__all__ = [
    _n for _n in ("EditableLabel", "InlineTitleEdit", "TagChip", "LinkChip", "PriorityBadge", "PriorityDot", "DueDateLabel", "GlassFrame")
    if _n in globals()
]
