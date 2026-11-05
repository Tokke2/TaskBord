# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
calendar_view.py — 📆 Kalender: månadsrutnät som visar hur tunga dagarna är (uppgifter per förfallodag).

* Varje dag är en knapp: dagens nummer + antal uppgifter. Färgskalan (ingen → orange → röd) visar
  belastningen, men antalet står alltid som text också, så färgen är aldrig det enda tecknet.
* Röda dagar (``core/holidays_se.py``) har röd siffra; idag har accentfärgad ram; förfallna dagar
  med öppna uppgifter har röd ram.
* Klick på en dag visar dagens uppgifter i listan under; dubbelklick på en uppgift öppnar den i
  Aktiva-fliken; "➕ Ny uppgift" skapar en uppgift med den dagen som förfallodag.
* Kalendern bara VISAR — uppgifterna ändras i Aktiva-fliken. Rutnätslogiken ligger i
  core/calendar_grid.py (testas utan Qt).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from core import calendar_grid as cg
from core import holidays_se

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[KALENDER]"

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
        QSizePolicy, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[misc,assignment]

_PRIO_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢", "none": "⚪"}
_WEEKDAY_LONG = holidays_se.WEEKDAYS

# Färgskalan för belastning, nivå 1–4. Varje dag får en svag färgton (BAKGRUND — texten ska förbli
# läsbar, kontrastmäts i tester/calendar_view_test.py) och ett kraftigt färgstreck längst ner (BAR).
HEAT_DARK = {1: "rgba(245, 158, 11, 0.10)", 2: "rgba(245, 158, 11, 0.16)",
             3: "rgba(249, 115, 22, 0.20)", 4: "rgba(239, 68, 68, 0.24)"}
HEAT_LIGHT = {1: "rgba(245, 158, 11, 0.12)", 2: "rgba(245, 158, 11, 0.20)",
              3: "rgba(249, 115, 22, 0.24)", 4: "rgba(239, 68, 68, 0.28)"}
HEAT_BAR_DARK = {1: "#f5b942", 2: "#f59e0b", 3: "#f97316", 4: "#ef4444"}
HEAT_BAR_LIGHT = {1: "#a16207", 2: "#c2680a", 3: "#c2410c", 4: "#b91c1c"}
RED_TEXT_DARK = "#ffc9c9"
RED_TEXT_LIGHT = "#7f1d1d"


def day_label(d: date) -> str:
    return f"{_WEEKDAY_LONG[d.weekday()]} {d.day} {cg.MONTH_NAMES[d.month - 1]}"


def build_stylesheet(is_dark: bool, accent_hex: str, fg: str, muted: str, edge: str, surface: str,
                     px: int = 12) -> str:
    """QSS för vyn (ren sträng-funktion, så färgerna kan kontrastmätas i tester)."""
    heat = HEAT_DARK if is_dark else HEAT_LIGHT
    from core import tag_colors as _tc
    sel_text = _tc.text_color_for(accent_hex) if _tc.valid_hex(accent_hex) else "#000000"
    red = RED_TEXT_DARK if is_dark else RED_TEXT_LIGHT
    rules = [
        f"QLabel#calTitle {{ color: {fg}; font-size: {px + 3}px; font-weight: 700; }}",
        f"QLabel#calSummary, QLabel#calWeekday, QLabel#calWeekNo {{ color: {muted}; font-size: {px}px; }}",
        f"QLabel#calDayTitle {{ color: {fg}; font-size: {px + 1}px; font-weight: 700; }}",
        f"QPushButton#calNav {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; padding: 4px 10px; font-size: {px}px; font-weight: 600; }}",
        f"QPushButton#calNav:hover {{ border: 1px solid {accent_hex}; }}",
        f"QPushButton[calCell=\"true\"] {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; padding: 2px; font-size: {px}px; }}",
    ]
    for lvl, bg in heat.items():
        rules.append(f"QPushButton[calCell=\"true\"][heat=\"{lvl}\"] {{ background: {bg}; }}")
    rules += [
        f"QPushButton[calCell=\"true\"][redDay=\"true\"] {{ color: {red}; }}",
        f"QPushButton[calCell=\"true\"][otherMonth=\"true\"] {{ color: {muted}; }}",
        f"QPushButton[calCell=\"true\"][overdue=\"true\"] {{ border: 2px solid {red}; }}",
        f"QPushButton[calCell=\"true\"][today=\"true\"] {{ border: 2px solid {accent_hex}; font-weight: 700; }}",
        f"QPushButton[calCell=\"true\"]:hover {{ border: 2px solid {accent_hex}; }}",
        f"QPushButton[calCell=\"true\"][selected=\"true\"] {{ border: 3px solid {fg}; font-weight: 700; }}",
        # grannmånadens dagar: ingen färgton (muted text ska ligga på vanlig yta) — stapeln visas ändå
        f"QPushButton[calCell=\"true\"][otherMonth=\"true\"] {{ background: {surface}; }}",
        f"QListWidget#calDayList {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; font-size: {px + 1}px; }}",
        "QListWidget#calDayList::item { padding: 4px 6px; }",
        f"QListWidget#calDayList::item:selected {{ background: {accent_hex}; color: {sel_text}; }}",
    ]
    for lvl, bar in (HEAT_BAR_DARK if is_dark else HEAT_BAR_LIGHT).items():
        rules.append(f"QPushButton[calCell=\"true\"][heat=\"{lvl}\"] {{ border-bottom: 5px solid {bar}; }}")
    return "\n".join(rules)


if _QT:

    class CalendarView(QWidget):
        task_activated = Signal(str)   # uppgifts-id (dubbelklick i dagens lista)
        add_requested = Signal(str)    # ISO-datum (➕ Ny uppgift den här dagen)

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setObjectName("calendarView")
            today = date.today()
            self._year, self._month = today.year, today.month
            self._selected: date = today
            self._today: date = today
            self._tasks: List[Dict[str, Any]] = []
            self._by_day: Dict[date, List[Dict[str, Any]]] = {}
            self._cells: Dict[date, Any] = {}
            self._cell_buttons: List[Any] = []
            self._week_labels: List[Any] = []

            rot = QVBoxLayout(self)
            rot.setContentsMargins(4, 6, 4, 4)
            rot.setSpacing(6)

            top = QHBoxLayout()
            self.prev_btn = QPushButton("◀", self)
            self.prev_btn.setObjectName("calNav")
            self.prev_btn.setAccessibleName("Föregående månad")
            self.prev_btn.clicked.connect(lambda: self.step_month(-1))
            self.title = QLabel("", self)
            self.title.setObjectName("calTitle")
            self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.next_btn = QPushButton("▶", self)
            self.next_btn.setObjectName("calNav")
            self.next_btn.setAccessibleName("Nästa månad")
            self.next_btn.clicked.connect(lambda: self.step_month(1))
            self.today_btn = QPushButton("Idag", self)
            self.today_btn.setObjectName("calNav")
            self.today_btn.clicked.connect(self.go_today)
            for b in (self.prev_btn, self.next_btn, self.today_btn):
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            top.addWidget(self.prev_btn)
            top.addWidget(self.title, 1)
            top.addWidget(self.next_btn)
            top.addWidget(self.today_btn)
            rot.addLayout(top)

            self.summary = QLabel("", self)
            self.summary.setObjectName("calSummary")
            self.summary.setWordWrap(True)
            self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rot.addWidget(self.summary)

            grid = QGridLayout()
            grid.setSpacing(3)
            hdr = QLabel("v", self)
            hdr.setObjectName("calWeekday")
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(hdr, 0, 0)
            for i, name in enumerate(cg.WEEKDAYS_SHORT):
                lb = QLabel(name, self)
                lb.setObjectName("calWeekday")
                lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(lb, 0, i + 1)
            for r in range(6):
                wl = QLabel("", self)
                wl.setObjectName("calWeekNo")
                wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(wl, r + 1, 0)
                self._week_labels.append(wl)
                for c in range(7):
                    b = QPushButton("", self)
                    b.setProperty("calCell", True)
                    b.setMinimumHeight(40)
                    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                    b.clicked.connect(lambda _c=False, rr=r, cc=c: self._cell_clicked(rr, cc))
                    grid.addWidget(b, r + 1, c + 1)
                    self._cell_buttons.append(b)
            grid.setColumnStretch(0, 0)
            for c in range(1, 8):
                grid.setColumnStretch(c, 1)
            rot.addLayout(grid, 3)

            self.day_title = QLabel("", self)
            self.day_title.setObjectName("calDayTitle")
            self.day_title.setWordWrap(True)
            rot.addWidget(self.day_title)
            self.day_list = QListWidget(self)
            self.day_list.setObjectName("calDayList")
            self.day_list.setMinimumHeight(70)
            self.day_list.itemDoubleClicked.connect(self._item_activated)
            self.day_list.itemActivated.connect(self._item_activated)
            rot.addWidget(self.day_list, 2)
            self.add_btn = QPushButton("➕ Ny uppgift den här dagen", self)
            self.add_btn.setObjectName("calNav")
            self.add_btn.clicked.connect(lambda: self.add_requested.emit(self._selected.isoformat()))
            rot.addWidget(self.add_btn)

            self.apply_theme(True, "#818cf8", "#eef1fb", "#cfd6ec",
                             "rgba(151, 162, 216, 0.22)", "rgba(56, 62, 96, 120)")
            self.refresh()

        # ------------------------------------------------------------ data
        def set_tasks(self, tasks: List[Dict[str, Any]], today: Optional[date] = None) -> None:
            self._tasks = list(tasks or [])
            self._today = today or date.today()
            self._by_day = cg.tasks_by_day(self._tasks)
            self.refresh()

        def apply_theme(self, is_dark: bool, accent_hex: str, fg: str, muted: str, edge: str,
                        surface: str, px: int = 12) -> None:
            self._is_dark = is_dark
            self.setStyleSheet(build_stylesheet(is_dark, accent_hex, fg, muted, edge, surface, px))
            for b in self._cell_buttons:
                self._repolish(b)

        @staticmethod
        def _repolish(w: Any) -> None:
            st = w.style()
            st.unpolish(w)
            st.polish(w)

        # ------------------------------------------------------------ navigation
        def month(self) -> tuple:
            return (self._year, self._month)

        def selected_date(self) -> date:
            return self._selected

        def show_month(self, year: int, month: int) -> None:
            self._year, self._month = year, month
            if (self._selected.year, self._selected.month) != (year, month):
                self._selected = date(year, month, 1)
            self.refresh()

        def step_month(self, delta: int) -> None:
            y, m = cg.shift_month(self._year, self._month, delta)
            self.show_month(y, m)

        def go_today(self) -> None:
            t = date.today()
            self._today = t
            self._year, self._month, self._selected = t.year, t.month, t
            self.refresh()

        def select_date(self, d: date) -> None:
            self._selected = d
            if (d.year, d.month) != (self._year, self._month):
                self._year, self._month = d.year, d.month
            self.refresh()

        def _cell_clicked(self, r: int, c: int) -> None:
            weeks = cg.month_grid(self._year, self._month)
            if r < len(weeks):
                self.select_date(weeks[r][c])

        def _item_activated(self, item: Any) -> None:
            tid = item.data(Qt.ItemDataRole.UserRole)
            if tid:
                self.task_activated.emit(str(tid))

        # ------------------------------------------------------------ rendering
        def cell_info(self, d: date) -> Dict[str, Any]:
            """Det en dag visar (används av tester): antal, nivå, röd, förfallen …"""
            entries = self._by_day.get(d, [])
            due_n = sum(1 for e in entries if e["kind"] == "due")
            info = cg.day_info(d)
            return {
                "count": len(entries), "due": due_n, "heat": cg.heat(len(entries)),
                "red": info["red"], "holiday": info["holiday"], "today": d == self._today,
                "overdue": bool(entries) and d < self._today,
                "other": (d.year, d.month) != (self._year, self._month),
            }

        def refresh(self) -> None:
            weeks = cg.month_grid(self._year, self._month)
            self.title.setText(cg.month_title(self._year, self._month))
            self._cells = {}
            for r in range(6):
                visible = r < len(weeks)
                self._week_labels[r].setVisible(visible)
                if visible:
                    self._week_labels[r].setText(str(cg.iso_week(weeks[r][0])))
                for c in range(7):
                    b = self._cell_buttons[r * 7 + c]
                    b.setVisible(visible)
                    if not visible:
                        continue
                    d = weeks[r][c]
                    self._cells[d] = b
                    i = self.cell_info(d)
                    b.setText(f"{d.day}\n{i['count']} st" if i["count"] else f"{d.day}\n ")
                    for k, v in (("heat", str(i["heat"])), ("redDay", i["red"]), ("otherMonth", i["other"]),
                                 ("today", i["today"]), ("selected", d == self._selected),
                                 ("overdue", i["overdue"])):
                        b.setProperty(k, v)
                    tip = [day_label(d)]
                    if i["holiday"]:
                        tip.append(f"Röd dag: {i['holiday']}")
                    for e in self._by_day.get(d, [])[:8]:
                        tip.append(("🔔 " if e["kind"] == "remind" else "• ") + str(e["task"].get("title") or ""))
                    if i["count"] > 8:
                        tip.append(f"… och {i['count'] - 8} till")
                    b.setToolTip("\n".join(tip))
                    b.setAccessibleName(
                        f"{day_label(d)}, {i['count']} uppgifter" + (f", {i['holiday']}" if i["holiday"] else ""))
                    self._repolish(b)
            total = cg.month_total(self._by_day, self._year, self._month)
            best = cg.busiest(self._by_day, self._year, self._month)
            if total and best:
                self.summary.setText(
                    f"{total} uppgifter i {cg.MONTH_NAMES[self._month - 1]} · tyngsta dagen: "
                    f"{_WEEKDAY_LONG[best[0].weekday()][:3]} {best[0].day}/{best[0].month} ({best[1]} st)")
            else:
                self.summary.setText(f"Inga uppgifter med datum i {cg.MONTH_NAMES[self._month - 1]}.")
            self._fill_day_list()

        def _fill_day_list(self) -> None:
            d = self._selected
            entries = self._by_day.get(d, [])
            info = cg.day_info(d)
            head = day_label(d) + (f" — {info['holiday']}" if info["holiday"] else "")
            head += f" · {len(entries)} uppgifter" if entries else " · inga uppgifter"
            self.day_title.setText(head)
            self.day_list.clear()
            for e in entries:
                t = e["task"]
                icon = "🔔" if e["kind"] == "remind" else _PRIO_ICON.get(str(t.get("priority")), "⚪")
                text = f"{icon}  {t.get('title') or ''}" + ("   (påminnelse)" if e["kind"] == "remind" else "")
                it = QListWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, str(t.get("id") or ""))
                self.day_list.addItem(it)
else:  # pragma: no cover
    class CalendarView:  # type: ignore[no-redef]
        def __init__(self, *a: Any, **k: Any) -> None:
            pass
