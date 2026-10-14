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
            self._log.info(
                f"{LOG_PREFIX} Påminnelsetjänst aktiv (var 60:e sek) — v7-fix64"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _init_reminder_service: {e}", exc_info=True
            )

    def _check_reminders(self) -> None:
        """NY v7-fix64: kontrollera förfallna/dagens uppgifter → notis."""
        try:
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

            from datetime import datetime as _dt, date as _d
            _today = _d.today()
            _now = _dt.now()
            if not hasattr(self, "_reminded_ids"):
                self._reminded_ids = set()

            overdue_new: List[Any] = []
            today_new: List[Any] = []
            if hasattr(self.store, "active_tasks"):
                for task in self.store.active_tasks():
                    tid = task.get("id")
                    due = task.get("due_date")
                    if not tid or not due or task.get("done"):
                        continue
                    # Snoozad? (gömd tills vidare — påminn ej)
                    sn = task.get("snoozed_until")
                    if sn:
                        try:
                            if _dt.fromisoformat(str(sn)) > _now:
                                continue
                        except (ValueError, TypeError):
                            pass
                    try:
                        d = _dt.fromisoformat(str(due)).date()
                    except (ValueError, TypeError):
                        continue
                    if tid in self._reminded_ids:
                        continue
                    if d < _today:
                        overdue_new.append(task)
                    elif d == _today:
                        today_new.append(task)

            if overdue_new:
                for task in overdue_new:
                    self._reminded_ids.add(task.get("id"))
                titles = ", ".join(
                    f"'{t.get('title', '?')[:25]}'"
                    for t in overdue_new[:3]
                )
                extra = (
                    f" (+{len(overdue_new) - 3} till)"
                    if len(overdue_new) > 3 else ""
                )
                self._tray.showMessage(
                    APP_NAME,
                    f"⚠ {len(overdue_new)} uppgift(er) har passerat "
                    f"förfallodatum:\n{titles}{extra}\n"
                    f"(högerklicka tray → 📋 Statistik eller öppna listan)",
                    self._QSystemTrayIcon.MessageIcon.Warning,
                    8000,
                )
                self._log.info(
                    f"{LOG_PREFIX} PÅMINNELSE: {len(overdue_new)} "
                    f"förfallna uppgifter"
                )
            if today_new:
                for task in today_new:
                    self._reminded_ids.add(task.get("id"))
                titles = ", ".join(
                    f"'{t.get('title', '?')[:25]}'"
                    for t in today_new[:3]
                )
                extra = (
                    f" (+{len(today_new) - 3} till)"
                    if len(today_new) > 3 else ""
                )
                self._tray.showMessage(
                    APP_NAME,
                    f"📅 {len(today_new)} uppgift(er) förfaller idag:\n"
                    f"{titles}{extra}",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
                self._log.info(
                    f"{LOG_PREFIX} PÅMINNELSE: {len(today_new)} "
                    f"uppgifter förfaller idag"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _check_reminders: {e}")

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
