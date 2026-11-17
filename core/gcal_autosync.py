# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
gcal_autosync.py — ändrar du start- eller förfallodatum på en uppgift som redan finns i Google Calendar
flyttas händelsen automatiskt dit också (t.ex. "vindrutebyte idag, kunden var sjuk → nästa vecka").

Regler (medvetet försiktiga):
  • Bara uppgifter som du SJÄLV tidigare skickat till kalendern (de finns i event_map) följer med.
    En uppgift som aldrig skickats skapas aldrig av sig själv — du väljer fortfarande vad som skickas.
  • Bara datumfälten (start/slut) skrivs. Rubrik, beskrivning och färg du ändrat i Google lämnas orörda.
  • Är händelsen borttagen i Google skapas den INTE på nytt; kopplingen släpps bara.
  • Flera ändringar i rad (t.ex. start + förfallodatum) slås ihop till ETT anrop (2 s).
  • Går det inte (inget nät) provas igen efter 30 s, 2 min och 10 min, och sedan vid nästa programstart.
  • Allt sker i en egen tråd — gränssnittet väntar aldrig på Google. Inget Qt här.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import google_calendar as gcal

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[GCAL-SYNC]"

DEBOUNCE_SEC = 2.0
RETRY_DELAYS = (30.0, 120.0, 600.0)
_WD = ("mån", "tis", "ons", "tors", "fre", "lör", "sön")
_MON = ("jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


def pending_path(data_dir: Any) -> Path:
    return gcal.google_dir(data_dir) / "pending_sync.json"


def fmt_day(d: _date) -> str:
    return f"{_WD[d.weekday()]} {d.day} {_MON[d.month - 1]}"


def describe_dates(task: Dict[str, Any]) -> str:
    """'mån 19 okt' eller 'mån 19 okt – tis 20 okt' (samma dagar som kalenderhändelsen får)."""
    dagar = gcal.resolve_task_dates(task)
    if not dagar:
        return ""
    a, b = dagar
    return fmt_day(a) if a == b else f"{fmt_day(a)} – {fmt_day(b)}"


def date_patch(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Bara start/slut för PATCH (heldagshändelse, slutdatum exklusivt). None om uppgiften saknar datum."""
    dagar = gcal.resolve_task_dates(task)
    if not dagar:
        return None
    a, b = dagar
    return {"start": {"date": a.isoformat()}, "end": {"date": (b + timedelta(days=1)).isoformat()}}


def options_from_settings(settings: Any, data_dir: Any) -> Dict[str, Any]:
    """Läs aktuella val (kalender, färg, 'klar'-stil, av/på) — alltid färska, så ändringar slår igenom direkt."""
    def call(name: str, default: Any) -> Any:
        try:
            f = getattr(settings, name, None)
            return f() if callable(f) else default
        except Exception:
            return default
    try:
        enabled = bool(settings.pref("gcal_autosync"))
    except Exception:
        enabled = True
    cid = str(call("google_calendar_id", "") or "").strip()
    if not cid:
        konto = gcal.load_account_info(data_dir) or {}
        cid = str(konto.get("calendar_id") or gcal.DEFAULT_CALENDAR_ID)
    return {"enabled": enabled, "calendar_id": cid,
            "color": bool(call("google_calendar_color_by_priority", True)),
            "done_style": str(call("google_calendar_done_style", gcal.DEFAULT_DONE_STYLE))}


class AutoSync:
    def __init__(
        self,
        data_dir: Any,
        find_task: Callable[[str], Optional[Dict[str, Any]]],
        get_options: Callable[[], Dict[str, Any]],
        notify: Optional[Callable[[Dict[str, Any]], None]] = None,
        service_factory: Optional[Callable[[Any], Any]] = None,
        connected: Optional[Callable[[Any], bool]] = None,
        debounce: float = DEBOUNCE_SEC,
        retry_delays: tuple = RETRY_DELAYS,
    ) -> None:
        self.data_dir = Path(str(data_dir))
        self._find = find_task
        self._opts = get_options
        self._notify = notify or (lambda r: None)
        self._service = service_factory or gcal.build_calendar_service
        self._connected = connected or gcal.is_connected
        self.debounce = float(debounce)
        self.retry_delays = tuple(retry_delays)
        self._cond = threading.Condition()
        self._due: Dict[str, float] = {}        # task_id → när den ska köras
        self._attempts: Dict[str, int] = {}
        self._busy = False
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        self.log: List[Dict[str, Any]] = []     # senaste resultat (för tester/diagnos)

    # ------------------------------------------------------------------ in
    def is_synced_task(self, task_id: str) -> bool:
        try:
            return bool(gcal.load_event_map(self.data_dir).get(str(task_id)))
        except Exception:
            return False

    def request(self, task_id: str) -> bool:
        """Datum ändrat på task_id. True om ett anrop köats (uppgiften finns i kalendern och funktionen är på)."""
        tid = str(task_id or "")
        if not tid:
            return False
        try:
            if not self._opts().get("enabled", True):
                return False
        except Exception:
            return False
        if not self.is_synced_task(tid):
            return False
        self._enqueue(tid, self.debounce, fresh=True)
        return True

    def resume(self, delay: float = 20.0) -> int:
        """Vid programstart: gör om sådant som inte hann/gick före förra avslutet."""
        n = 0
        try:
            raw = json.loads(pending_path(self.data_dir).read_text(encoding="utf-8"))
            for tid in (raw.get("tasks") or []):
                self._enqueue(str(tid), delay)
                n += 1
        except Exception:
            pass
        return n

    def _enqueue(self, tid: str, delay: float, fresh: bool = False) -> None:
        with self._cond:
            self._due[tid] = time.monotonic() + max(0.0, delay)
            if fresh:
                self._attempts.pop(tid, None)   # ny ändring av användaren → börja om med försöken
            if self._thread is None or not self._thread.is_alive():
                self._stop = False
                self._thread = threading.Thread(target=self._run, name="gcal-autosync", daemon=True)
                self._thread.start()
            self._cond.notify_all()
        self._persist()

    # ------------------------------------------------------------- tråden
    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._stop:
                    if not self._due:
                        self._busy = False
                        self._cond.notify_all()
                        if not self._cond.wait(timeout=30.0) and not self._due:
                            self._thread = None
                            return
                        continue
                    nu = time.monotonic()
                    klara = [t for t, w in self._due.items() if w <= nu]
                    if klara:
                        break
                    self._cond.wait(timeout=max(0.05, min(self._due.values()) - nu))
                if self._stop:
                    self._busy = False
                    self._cond.notify_all()
                    return
                self._busy = True
                for t in klara:
                    self._due.pop(t, None)
            for t in klara:
                try:
                    self._sync_one(t)
                except Exception as e:  # tråden får aldrig dö
                    logger.warning(f"{LOG_PREFIX} oväntat fel: {type(e).__name__}: {e}")

    def flush(self, timeout: float = 10.0) -> bool:
        """Vänta tills allt köat är kört (tester). Retry-väntan hoppas över."""
        slut = time.monotonic() + timeout
        with self._cond:
            for t in list(self._due):
                self._due[t] = 0.0
            self._cond.notify_all()
            while (self._due or self._busy) and time.monotonic() < slut:
                self._cond.wait(timeout=0.05)
            return not self._due and not self._busy

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    # ------------------------------------------------------------ kärnan
    def _persist(self) -> None:
        try:
            with self._cond:   # läs OCH skriv under samma lås, annars kan en gammal lista skriva över en ny
                ids = sorted(self._due)
                p = pending_path(self.data_dir)
                if ids:
                    gcal._atomic_write_json(p, {"tasks": ids})
                elif p.exists():
                    p.unlink()
        except Exception:
            pass

    def _result(self, tid: str, task: Optional[Dict[str, Any]], ok: bool, action: str, msg: str, final: bool = True) -> Dict[str, Any]:
        r = {"task_id": tid, "title": str((task or {}).get("title") or ""), "ok": ok, "action": action,
             "message": msg, "when": describe_dates(task or {}), "final": final}
        self.log.append(r)
        del self.log[:-50]
        if final and action != "ingen":
            try:
                self._notify(r)
            except Exception:
                pass
        return r

    def _retry(self, tid: str, task: Optional[Dict[str, Any]], msg: str) -> Dict[str, Any]:
        n = self._attempts.get(tid, 0)
        if n < len(self.retry_delays):
            self._attempts[tid] = n + 1
            logger.info(f"{LOG_PREFIX} försöker igen om {self.retry_delays[n]:.0f} s ({msg[:80]})")
            with self._cond:
                self._due[tid] = time.monotonic() + self.retry_delays[n]
            self._persist()
            return self._result(tid, task, False, "väntar", msg, final=False)
        self._attempts.pop(tid, None)
        with self._cond:
            self._due.pop(tid, None)
        try:   # ligger kvar på disk → nästa programstart provar igen
            ids = set(json.loads(pending_path(self.data_dir).read_text(encoding="utf-8")).get("tasks") or []) | {tid}
            gcal._atomic_write_json(pending_path(self.data_dir), {"tasks": sorted(ids)})
        except Exception:
            try:
                gcal._atomic_write_json(pending_path(self.data_dir), {"tasks": [tid]})
            except Exception:
                pass
        return self._result(tid, task, False, "fel", msg + " Provar igen nästa gång Ledgebord startar.")

    def _sync_one(self, tid: str) -> Dict[str, Any]:
        opts = self._opts()
        task = self._find(tid)
        if not opts.get("enabled", True) or not task:
            self._persist()
            return self._result(tid, task, True, "ingen", "av eller borttagen")
        em = gcal.load_event_map(self.data_dir)
        eid = em.get(tid)
        if not eid:
            self._persist()
            return self._result(tid, task, True, "ingen", "inte i kalendern")
        patch = date_patch(task)
        if patch is None:
            self._persist()
            return self._result(tid, task, True, "hoppad", "Uppgiften har inget datum kvar — händelsen i kalendern lämnades som den var.")
        try:
            if not gcal.is_google_library_available() or not self._connected(self.data_dir):
                self._persist()
                return self._result(tid, task, False, "hoppad", "Google Calendar är inte kopplat just nu, så händelsen flyttades inte.")
            service = self._service(self.data_dir)
            cid = str(opts.get("calendar_id") or gcal.DEFAULT_CALENDAR_ID)
            svar = gcal.patch_event(service, cid, eid, patch)
        except gcal.GoogleCalendarError as e:
            tekn = e.technical or ""
            borta = any(k in tekn for k in ("404", "410", "Not Found", "Gone")) or "finns inte kvar" in e.user_message
            if borta:
                em.pop(tid)
                self._attempts.pop(tid, None)
                self._persist()
                try:
                    gcal._record_history(gcal.load_history(self.data_dir), cid, task, {"ok": False, "action": "hoppad",
                                         "message": "Händelsen var borttagen i Google — kopplingen släpptes.", "event_id": eid})
                except Exception:
                    pass
                return self._result(tid, task, False, "borttagen", "Händelsen var borttagen i Google Calendar, så den flyttades inte (och skapades inte på nytt).")
            return self._retry(tid, task, e.user_message)
        except Exception as e:
            return self._retry(tid, task, f"{type(e).__name__}: {e}")
        self._attempts.pop(tid, None)
        self._persist()
        try:
            gcal._record_history(gcal.load_history(self.data_dir), cid, task, {
                "ok": True, "action": "uppdaterad", "event_id": svar.get("id") or eid, "html_link": svar.get("htmlLink", ""),
                "message": f"Datum flyttades automatiskt till {describe_dates(task)}."})
        except Exception:
            pass
        logger.info(f"{LOG_PREFIX} '{str(task.get('title'))[:40]}' flyttad i kalendern → {describe_dates(task)}")
        return self._result(tid, task, True, "uppdaterad", f"Flyttad i Google Calendar till {describe_dates(task)}.")
