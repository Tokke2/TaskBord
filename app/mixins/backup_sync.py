# -*- coding: utf-8 -*-
"""Automatisk backup, synk mellan processer, autospar och uppdatering av listor."""

from __future__ import annotations

import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.constants import AppMode, JS_DIR, LOG_PREFIX


class BackupSyncMixin:
    """Automatisk backup, synk mellan processer, autospar och uppdatering av listor."""

    # -----------------------------------------------------------------------
    # NY v7-fix90: E-POSTBRYGGA — Thunderbird-tillägg + inkorgsmapp
    # -----------------------------------------------------------------------
    #  Rickard 2026-10-11: "importera uppgifter från mail via thunderbird —
    #  om man kan göra tillägg till thunderbird som kan importera uppgift
    #  till appen. Uppgifter ska sparas i json-fil för att finnas kvar
    #  efter omstart av appen."
    #
    #  Lösning (två vägar in, alltid JSON-sparande):
    #    1. HTTP-brygga på 127.0.0.1 (Thunderbird-tillägget POST:ar mailet)
    #    2. Inkorgsmappen data/inbox/ (fungerar även om appen var avstängd)
    #  Se core/mail_bridge.py + katalogen thunderbird-tillagg/.
    # -----------------------------------------------------------------------

    # ------------------------------------------------------------------
    # NY v8 (2026-10-12): automatisk säkerhetskopia (data/backups/auto/)
    # ------------------------------------------------------------------
    def _user_data_dir(self) -> Path:
        """Mappen med active.json/archive.json/settings.json (js/)."""
        store = getattr(self, "store", None)
        d = getattr(store, "data_dir", None) if store is not None else None
        if callable(d):
            with suppress(Exception):
                d = d()
        return Path(str(d)) if d else JS_DIR

    def _restore_from_external_backup(self) -> None:
        from core import tasks_backup as _tb
        r = _tb.restore_if_missing(JS_DIR)
        if r.get("active") or r.get("settings"):
            self._log.warning(
                f"{LOG_PREFIX} ♻ Återställde från automatisk backup ({r.get('from')}): "
                f"uppgifter={r.get('active')}, inställningar={r.get('settings')}"
            )

    def _external_backup(self, reason: str = "") -> None:
        """Kopiera uppgifter + inställningar till data/backups/auto/ (hoppar över om oförändrat)."""
        try:
            if self._mode == AppMode.SAFE_MODE:
                return
            from core import tasks_backup as _tb
            p = _tb.snapshot_external(self._user_data_dir())
            if p is not None:
                self._log.info(f"{LOG_PREFIX} automatisk backup ({reason}): {p.name}")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} automatisk backup misslyckades ({reason}): {e}")

    def _init_external_backup(self) -> None:
        """Första kopian strax efter start, därefter var 5:e minut (bara ändringar sparas)."""
        if self._mode == AppMode.SAFE_MODE:
            return
        self._ext_backup_timer = self._QTimer(self._app)
        self._ext_backup_timer.setInterval(5 * 60 * 1000)
        self._ext_backup_timer.timeout.connect(lambda: self._external_backup("timer"))
        self._ext_backup_timer.start()
        self._QTimer.singleShot(15_000, lambda: self._external_backup("start"))
        # FIX v8: fånga upp uppgifter som en ANNAN process skrivit till filerna (3 s)
        self._ext_sync_timer = self._QTimer(self._app)
        self._ext_sync_timer.setInterval(3000)
        self._ext_sync_timer.timeout.connect(self._sync_external_store)
        self._ext_sync_timer.start()

    def _sync_external_store(self) -> None:
        """FIX v8: hämta in uppgifter från annan process (GUI-tråden); store emitterar 'changed'."""
        try:
            fn = getattr(self.store, "sync_external", None)
            if callable(fn):
                n = fn()
                if n:
                    self._log.warning(
                        f"{LOG_PREFIX} {n} uppgift(er) hämtades in från en annan TaskBord-process"
                    )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _sync_external_store: {e}")

    def _check_backup_status(self) -> None:
        """Kontrollera backup-status (auto-restore om tasks är trasiga)."""
        try:
            if hasattr(self, "backup_manager"):
                with suppress(Exception):
                    status = self.backup_manager.get_status()
                    if status.get("needs_restore"):
                        self._log.warning("Backup restore behövs — återställer…")
                        self.backup_manager.restore_latest()
                        if hasattr(self.store, "reload"):
                            self.store.reload()
        except Exception as e:
            self._log.debug(f"check_backup_status misslyckades: {e}")

    def _on_tasks_changed(self, *_args: Any) -> None:
        """Hantera task-ändring (uppdatera tray-tooltip + meny)."""
        try:
            if threading.current_thread() is not threading.main_thread():
                # FIX v8: mail-bryggan ändrar store från egen tråd — Qt (tray, timers)
                # får bara röras från GUI-tråden. Läggs i kö → _poll_mail_bridge.
                self._store_changed_in_thread = True
                return
            self._update_tray_tooltip()
            # Uppdatera inte menyn varje gång (för dyrt) — bara tooltip
        except Exception as e:
            self._log.debug(f"on_tasks_changed misslyckades: {e}")

    def _on_store_data_changed(self, *_args: Any) -> None:
        """
        NY v7-fix11: store-data ändrad → debounced lista-refresh + autospara.

        Bakgrund: INGEN kod anropade tidigare store.save() — alla ändringar
        (lägg till / bocka av / byta prioritet ...) levde bara i RAM och
        FÖRSVANN vid omstart. Denna handler kopplas till store.changed och
        startar två single-shot-timers (debounce):
          * 250 ms  → _refresh_task_lists (uppdatera alla widgets listor)
          * 1500 ms → _autosave_store (spara till disk om dirty)
        Loop-säkert: save() emiterar INTE 'changed' (fix i store.py v7-fix11).
        """
        try:
            if threading.current_thread() is not threading.main_thread():
                self._store_changed_in_thread = True  # FIX v8: se _on_tasks_changed
                return
            self._schedule_task_refresh()
            self._schedule_autosave()
        except Exception as e:
            self._log.debug(f"on_store_data_changed misslyckades: {e}")

    def _schedule_task_refresh(self) -> None:
        """Debounce (250 ms) av task-lists-refresh — många signals per batch."""
        timer = getattr(self, "_task_refresh_timer", None)
        if timer is None:
            if self._QTimer is None:
                return
            timer = (
                self._QTimer(self._app) if self._app else self._QTimer()
            )
            timer.setSingleShot(True)
            timer.setInterval(250)
            timer.timeout.connect(self._refresh_task_lists)
            self._task_refresh_timer = timer
        timer.start()

    def _refresh_task_lists(self) -> None:
        """
        NY v7-fix11: Uppdatera task-listor i ALLA befintliga widgets.

        _populate_windows skapar bara SAKNADE fönster — befintliga widgets
        fick aldrig nya tasks förrän omstart. Här renderas listorna om direkt
        (loop-säkert: _render_tasks skriver varken till settings eller store).
        """
        refreshed = 0
        with self._widget_lock:
            widgets = list(self._widgets.values())
        for w in widgets:
            try:
                if hasattr(w, "_rebuild_task_list"):
                    # FIX v8: SAMMA renderare som övriga flöden (sorterad pinned→prio→skapad,
                    # respekterar sökfilter). Tidigare ritade denna om listan osorterad
                    # → mail-uppgifter hoppade runt/hamnade utom synhåll efter ~250 ms.
                    w._rebuild_task_list()
                elif hasattr(w, "_render_tasks"):
                    w._render_tasks(
                        self.store.active_tasks(), archived=False
                    )
                    w._render_tasks(
                        self.store.archive_tasks(), archived=True
                    )
                    if hasattr(w, "_build_search_index"):
                        w._build_search_index()
                refreshed += 1
            except Exception as e:
                self._log.warning(
                    f"{LOG_PREFIX} task-lists-refresh misslyckades "
                    f"för en widget: {e}"
                )
        if refreshed:
            self._log.debug(
                f"{LOG_PREFIX} task-listor uppdaterade i {refreshed} widget(s)"
            )

    def _schedule_autosave(self) -> None:
        """Debounce (1500 ms) autospara av store — skyddar mot dataförlust."""
        timer = getattr(self, "_autosave_timer", None)
        if timer is None:
            if self._QTimer is None:
                return
            timer = (
                self._QTimer(self._app) if self._app else self._QTimer()
            )
            timer.setSingleShot(True)
            timer.setInterval(1500)
            timer.timeout.connect(self._autosave_store)
            self._autosave_timer = timer
        timer.start()

    def _autosave_store(self) -> None:
        """NY v7-fix11: Spara store om dirty (kallas av debounce-timer)."""
        try:
            if self.store is None:
                return
            if getattr(self.store, "is_dirty", False):
                ok = self.store.save()
                self._log.info(
                    f"{LOG_PREFIX} autosave: "
                    f"{'OK' if ok else 'MISSLYCKADES'} "
                    f"(active={len(self.store.active_tasks())}, "
                    f"archive={len(self.store.archive_tasks())})"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} autosave misslyckades: {e}", exc_info=True
            )

    def _open_backup_dialog(self) -> None:
        """NY v8: öppna backup-dialogen från tray-menyn."""
        try:
            from ui.backup_dialog import open_backup_dialog
            open_backup_dialog(None, store=getattr(self, "store", None))
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde inte öppna backup-dialogen: {e}")
