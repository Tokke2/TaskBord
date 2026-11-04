# -*- coding: utf-8 -*-
"""Påminnelser för förfallna och dagens uppgifter."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, List

from app.constants import APP_NAME, LOG_PREFIX, SCRIPT_DIR


class RemindersMixin:
    """Påminnelser för förfallna och dagens uppgifter."""

    def _init_reminder_service(self) -> None:
        """
        NY v7-fix64: Påminnelsetjänst — notiser för förfallna/dagens
        uppgifter (konkurrenternas kärnfunktion, gap 22.12.2).

        Kollar var 60:e sekund (QTimer på GUI-tråden):
          - Förfallna (due < idag) → "⚠ N uppgifter har passerat datum"
          - Dagens (due == idag)  → "📅 N uppgifter förfaller idag"
        Förfallodag: första påminnelsen 08:00, sedan var 30:e minut tills händelsen
        (klockslaget, annars 18:00); försenade från tidigare dagar en gång per dag.
        Snoozade uppgifter exkluderas. Av/på i tray-menyn.
        """
        try:
            self._reminder_last = {}
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

    def _reminder_now(self) -> Any:
        """Nuvarande tid för påminnelselogiken (egen metod så tester kan styra klockan)."""
        from datetime import datetime as _dt
        return _dt.now()

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
            if not hasattr(self, "_reminder_last"):
                self._reminder_last = {}
            now = self._reminder_now()

            # Förfallodag: första påminnelsen 08:00, sedan var 30:e minut tills händelsen (se reminder_logic)
            new_items = []
            if hasattr(self.store, "active_tasks"):
                for task, kind, days in _rl.due_items(self.store.active_tasks(), now):
                    if _rl.reminder_due(task, now, self._reminder_last.get(task.get("id"))):
                        new_items.append((task, kind, days))
            if not new_items:
                return
            for task, _k, _d in new_items:
                self._reminder_last[task.get("id")] = now
            n_over = sum(1 for _t, k, _d in new_items if k == _rl.OVERDUE)
            self._log.info(
                f"{LOG_PREFIX} PÅMINNELSE: {n_over} förfallna, {len(new_items) - n_over} förfaller idag"
            )
            if not self._reminder_popup_show(
                [(str(t.get("id")), str(t.get("title", "?")), k, d, _rl.detail_text(t, k, d, now))
                 for t, k, d in new_items]
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
        """
        Knappen ✓ Klar: bockar av uppgiften i listan. Har uppgiften flera datum från ett mail (delbetalningar,
        core/mail_dates.py) betyder Klar "den här gången är avklarad": uppgiften flyttas till nästa datum och
        bockas av först efter sista.
        """
        try:
            from core import reminder_logic as _rl
            task = self.store.find_task(task_id) if hasattr(self.store, "find_task") else None
            plan = _rl.plan_done(task, self._reminder_now().date()) if task else {"complete": True}
            if plan["complete"]:
                self.store.toggle_task(task_id)
                self._log.info(f"{LOG_PREFIX} PÅMINNELSE: {task_id!r} avbockad från kortet")
            else:
                if plan.get("set_due"):
                    self.store.set_due_date(task_id, plan["set_due"])
                self.store.set_task_metadata(task_id, "remind_dates", plan["remind_dates"])
                if hasattr(self, "_reminder_last"):
                    self._reminder_last.pop(task_id, None)
                self._log.info(f"{LOG_PREFIX} PÅMINNELSE: {task_id!r} klar för idag — nästa {plan.get('next')}")
                nxt = plan.get("next")
                if nxt is not None and nxt > self._reminder_now().date() and self._tray is not None:
                    with suppress(Exception):
                        self._tray.showMessage(
                            APP_NAME, f"Klart för idag. Nästa påminnelse: {nxt.day}/{nxt.month}.",
                            self._QSystemTrayIcon.MessageIcon.Information, 5000,
                        )
            self._QTimer.singleShot(0, self._update_tray_badge)
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _reminder_done: {e}")

    def _reminder_snooze(self, task_id: str, hours: int = 1) -> None:
        """Knappen ⏰ 1 h: uppgiften senareläggs en timme och påminner igen när tiden gått."""
        try:
            from datetime import timedelta as _td
            until = (self._reminder_now() + _td(hours=hours)).replace(microsecond=0).isoformat()
            self.store.snooze_task(task_id, until)
            if hasattr(self, "_reminder_last"):
                self._reminder_last.pop(task_id, None)   # får en ny påminnelse när snoozen gått ut
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
    _tray_err_n = 0            # antal nya fel i fel.log (röd prick)
    _tray_open_err_n = 0       # antal ännu inte åtgärdade felposter i fel.log
    _tray_badge_key = None

    def _update_tray_badge(self) -> None:
        """Rita antalet försenade/dagens uppgifter på tray-ikonen (GUI-tråden). 0 = ren ikon."""
        try:
            if self._tray is None or self._app_icon is None or not hasattr(self.store, "active_tasks"):
                return
            from core import reminder_logic as _rl
            n_over, n_today = _rl.count_due(self.store.active_tasks())
            n = n_over + n_today
            n_err = 0
            with suppress(Exception):
                from core import error_log as _el
                n_err = _el.count_unseen(SCRIPT_DIR / "loggar")
                self._tray_open_err_n = _el.open_error_count(SCRIPT_DIR / "loggar")
            self._tray_err_n = n_err
            self._refresh_errlog_action()
            if (n, n_err) == self._tray_badge_key:
                return
            self._tray_badge_key = (n, n_err)
            self._tray_badge_n = n
            if n <= 0 and n_err <= 0:
                self._tray.setIcon(self._app_icon)
                with suppress(Exception):
                    self._last_tooltip_update = 0.0
                    self._update_tray_tooltip()
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
                if n > 0:
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
                if n_err > 0:       # röd prick uppe till höger = nya fel i felloggen
                    d = 20
                    p.setPen(QColor("#ffffff"))
                    p.setBrush(QColor("#ef4444"))
                    p.drawEllipse(QRect(size - d - 1, 1, d, d))
            finally:
                p.end()
            self._tray.setIcon(QIcon(pm))
            with suppress(Exception):
                if n > 0:
                    tip = f"{APP_NAME} — {n_over} försenade, {n_today} förfaller idag"
                    if n_err > 0:
                        tip += f"\n🧯 {n_err} nya fel i felloggen"
                    self._tray.setToolTip(tip)
                else:
                    self._last_tooltip_update = 0.0
                    self._update_tray_tooltip()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _update_tray_badge: {e}")

    @staticmethod
    def _errlog_action_text(n_err: int) -> str:
        return f"🧯  Öppna felloggen — {n_err} nya fel" if n_err > 0 else "🧯  Öppna felloggen"

    @staticmethod
    def _resolve_action_text(n_open: int) -> str:
        return f"✅  Markera fel som åtgärdade — {n_open} öppna" if n_open > 0 else "✅  Inga öppna fel"

    def _refresh_errlog_action(self) -> None:
        """Menyraderna följer antalet nya/öppna fel (kallas från märket och när menyn byggs)."""
        with suppress(Exception):
            act = getattr(self, "_errlog_action", None)
            if act is not None:
                act.setText(self._errlog_action_text(int(self._tray_err_n)))
        with suppress(Exception):
            ra = getattr(self, "_resolve_action", None)
            if ra is not None:
                ra.setText(self._resolve_action_text(int(self._tray_open_err_n)))
                ra.setEnabled(int(self._tray_open_err_n) > 0)

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
