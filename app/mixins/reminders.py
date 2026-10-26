# -*- coding: utf-8 -*-
"""Påminnelser för förfallna och dagens uppgifter."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, List

from app.constants import APP_NAME, LOG_PREFIX


class RemindersMixin:
    """Påminnelser för förfallna och dagens uppgifter."""

    def _init_reminder_service(self) -> None:
        """
        NY v7-fix64: Påminnelsetjänst — notiser för förfallna/dagens
        uppgifter (konkurrenternas kärnfunktion, gap 22.12.2).

        Kollar var 60:e sekund (QTimer på GUI-tråden):
          - Förfallna (due < idag) → "⚠ N uppgifter har passerat datum"
          - Dagens (due == idag)  → "📅 N uppgifter förfaller idag"
        Dedup: varje uppgift påminns EN gång per session.
        Snoozade uppgifter exkluderas. Av/på i tray-menyn.
        """
        try:
            self._reminded_ids = set()
            self._reminder_timer = self._QTimer()
            self._reminder_timer.setInterval(60000)  # 60 sek
            self._reminder_timer.timeout.connect(self._check_reminders)
            self._reminder_timer.start()
            # Första kontrollen efter 45 s (efter appstart, före/lägre än
            # auto-plugins på 30 s + notis på 45 s — utspritt)
            self._QTimer.singleShot(45000, self._check_reminders)
            self._QTimer.singleShot(4000, self._update_tray_badge)
            self._log.info(
                f"{LOG_PREFIX} Påminnelsetjänst aktiv (var 60:e sek) — v7-fix64"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _init_reminder_service: {e}", exc_info=True
            )

    def _check_reminders(self) -> None:
        """Kontrollera förfallna/dagens uppgifter → kort med knapparna Klar / Skjut 1 h (varje uppgift en gång/session)."""
        try:
            self._update_tray_badge()   # siffran på tray-ikonen följer alltid med (oberoende av notiser)
            # Av/på?
            try:
                _enabled = (
                    self.settings.reminders_enabled()
                    if hasattr(self.settings, "reminders_enabled")
                    else bool(
                        self.settings.get("reminders_enabled", True)
                    )
                )
            except Exception:
                _enabled = True
            if not _enabled or self._tray is None:
                return

            from core import reminder_logic as _rl
            if not hasattr(self, "_reminded_ids"):
                self._reminded_ids = set()

            new_items = []
            if hasattr(self.store, "active_tasks"):
                for task, kind, days in _rl.due_items(self.store.active_tasks()):
                    if task.get("id") in self._reminded_ids:
                        continue
                    new_items.append((task, kind, days))
            if not new_items:
                return
            for task, _k, _d in new_items:
                self._reminded_ids.add(task.get("id"))
            n_over = sum(1 for _t, k, _d in new_items if k == _rl.OVERDUE)
            self._log.info(
                f"{LOG_PREFIX} PÅMINNELSE: {n_over} förfallna, {len(new_items) - n_over} förfaller idag"
            )
            if not self._reminder_popup_show(
                [(str(t.get("id")), str(t.get("title", "?")), k, d) for t, k, d in new_items]
            ):
                self._reminder_tray_fallback(new_items)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _check_reminders: {e}")

    # ------------------------------------------------------------------
    # Kortet med knappar
    # ------------------------------------------------------------------
    def _reminder_popup_show(self, items: List[Any]) -> bool:
        """Visa påminnelsekortet (nere i hörnet, tar inte fokus). False om det inte gick."""
        try:
            pop = getattr(self, "_reminder_popup", None)
            if pop is None:
                from ui.reminder_popup import ReminderPopup
                pop = ReminderPopup(self._reminder_done, self._reminder_snooze, self._reminder_open)
                self._reminder_popup = pop
            pop.show_items(items)
            return True
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} påminnelsekortet kunde inte visas ({e}) — tray-notis i stället")
            self._reminder_popup = None
            return False

    def _reminder_tray_fallback(self, new_items: List[Any]) -> None:
        """Reserv: vanlig tray-notis (utan knappar) om kortet inte kan visas."""
        from core import reminder_logic as _rl
        for kind, head, icon in (
            (_rl.OVERDUE, "⚠ {n} uppgift(er) har passerat förfallodatum:", self._QSystemTrayIcon.MessageIcon.Warning),
            (_rl.TODAY, "📅 {n} uppgift(er) förfaller idag:", self._QSystemTrayIcon.MessageIcon.Information),
        ):
            sel = [t for t, k, _d in new_items if k == kind]
            if not sel:
                continue
            titles = ", ".join(f"'{t.get('title', '?')[:25]}'" for t in sel[:3])
            extra = f" (+{len(sel) - 3} till)" if len(sel) > 3 else ""
            self._tray.showMessage(APP_NAME, head.format(n=len(sel)) + f"\n{titles}{extra}", icon, 8000)

    def _reminder_done(self, task_id: str) -> None:
        """Knappen ✓ Klar: samma som att bocka av uppgiften i listan."""
        try:
            self.store.toggle_task(task_id)
            self._log.info(f"{LOG_PREFIX} PÅMINNELSE: {task_id!r} avbockad från kortet")
            self._QTimer.singleShot(0, self._update_tray_badge)
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _reminder_done: {e}")

    def _reminder_snooze(self, task_id: str, hours: int = 1) -> None:
        """Knappen ⏰ 1 h: uppgiften senareläggs en timme och påminner igen när tiden gått."""
        try:
            from datetime import datetime as _dt, timedelta as _td
            until = (_dt.now() + _td(hours=hours)).replace(microsecond=0).isoformat()
            self.store.snooze_task(task_id, until)
            if hasattr(self, "_reminded_ids"):
                self._reminded_ids.discard(task_id)   # får en ny påminnelse när snoozen gått ut
            self._log.info(f"{LOG_PREFIX} PÅMINNELSE: {task_id!r} skjuten till {until}")
            self._QTimer.singleShot(0, self._update_tray_badge)
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _reminder_snooze: {e}")

    def _reminder_open(self) -> None:
        """Knappen 'Öppna listan': lyft fönstret en stund (som ett klick på tray-ikonen)."""
        with suppress(Exception):
            self._lift_on_top_temporarily()

    # ------------------------------------------------------------------
    # Siffra på tray-ikonen (antal försenade + dagens)
    # ------------------------------------------------------------------
    _tray_badge_n = -1

    def _update_tray_badge(self) -> None:
        """Rita antalet försenade/dagens uppgifter på tray-ikonen (GUI-tråden). 0 = ren ikon."""
        try:
            if self._tray is None or self._app_icon is None or not hasattr(self.store, "active_tasks"):
                return
            from core import reminder_logic as _rl
            n_over, n_today = _rl.count_due(self.store.active_tasks())
            n = n_over + n_today
            if n == self._tray_badge_n:
                return
            self._tray_badge_n = n
            if n <= 0:
                self._tray.setIcon(self._app_icon)
                return
            from PySide6.QtCore import QRect, Qt
            from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
            size = 64
            pm = QPixmap(self._app_icon.pixmap(size, size))
            if pm.isNull():
                return
            p = QPainter(pm)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                r = 26
                rect = QRect(size - r, size - r, r, r)
                p.setPen(QColor("#ffffff"))
                p.setBrush(QColor("#dc2626" if n_over else "#d97706"))
                p.drawEllipse(rect)
                f = QFont()
                f.setBold(True)
                f.setPixelSize(18 if n < 10 else 15)
                p.setFont(f)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, _rl.badge_text(n))
            finally:
                p.end()
            self._tray.setIcon(QIcon(pm))
            with suppress(Exception):
                self._tray.setToolTip(f"{APP_NAME} — {n_over} försenade, {n_today} förfaller idag")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _update_tray_badge: {e}")

    def _toggle_reminders(self, checked: bool) -> None:
        """NY v7-fix64: tray-toggle för påminnelser."""
        try:
            if hasattr(self.settings, "set_reminders_enabled"):
                self.settings.set_reminders_enabled(bool(checked))
            if hasattr(self, "_reminder_timer"):
                with suppress(Exception):
                    if checked:
                        self._reminder_timer.start()
                    else:
                        self._reminder_timer.stop()
            self._log.info(
                f"{LOG_PREFIX} Påminnelser: {'PÅ' if checked else 'AV'}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_reminders: {e}")
