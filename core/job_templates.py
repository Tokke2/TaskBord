# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
job_templates.py — jobbmallar: ETT klick skapar alla uppgifterna för ett återkommande jobb, med datum
relativt jobbdagen. Ren stdlib (inget Qt) — dialogen finns i ui/job_template_dialog.py.

Exempel "Limojobb": Bekräfta bokning (−3 dagar) · Utför jobbet (0) · Skicka faktura (+1) · Bevaka betalning (+30).

* Mallarna ligger i ``mallar.json`` i datamappen (``js\\`` — alltså inne i appmappen, som allt annat).
* Titeln kan innehålla ``{kund}`` — ersätts med kundens namn. Saknas platshållaren läggs " — kund" till
  efter titeln (om ett namn angivits); utan namn försvinner platshållaren.
* Varje mall har valet ``gcal``: skicka de skapade uppgifterna automatiskt till Google Calendar.
  Det är ditt eget val per mall (och kan ändras vid varje användning); är Google inte kopplat hoppas det över
  med en notis och uppgifterna skapas ändå. Skickandet sker i en egen tråd — gränssnittet väntar aldrig.
  Uppgifter som skickats hamnar i kopplingstabellen, så senare datumändringar följer med automatiskt
  (core/gcal_autosync.py).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import threading
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import google_calendar as gcal
from core import payment_plan as pp

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[MALLAR]"

FILENAME = "mallar.json"
VERSION = 1
MAX_TEMPLATES = 40
MAX_STEPS = 30
MAX_NAME = 60
MAX_TITLE = 200
MIN_DAYS, MAX_DAYS = -365, 3650
PRIORITIES = ("none", "high", "medium", "low")
PLACEHOLDER = "{kund}"
RETRY_DELAYS = (30.0, 120.0, 600.0)

# Meddelanden från bakgrundstråden → tray-notiser (töms av appen på GUI-tråden). deque.append är trådsäkert.
EVENTS: "collections.deque[Dict[str, Any]]" = collections.deque(maxlen=20)


# ------------------------------------------------------------------------------ mallar -----------
def new_id() -> str:
    return uuid.uuid4().hex[:8]


def _step(title: str, days: int, priority: str = "none", tags: Optional[List[str]] = None,
          amount_cents: int = 0, workday: bool = False) -> Dict[str, Any]:
    return {"title": title, "days": days, "priority": priority, "tags": list(tags or []),
            "amount_cents": amount_cents, "workday": workday}


def default_templates() -> List[Dict[str, Any]]:
    """Två startmallar (egna ändringar och borttagning sparas). Skapas först när mallfilen saknas."""
    return [
        {"id": "limojobb", "name": "Limojobb", "gcal": False, "steps": [
            _step("Bekräfta bokning — {kund}", -3, "medium"),
            _step("Utför jobbet — {kund}", 0, "high"),
            _step("Skicka faktura — {kund}", 1, "high", ["faktura"], workday=True),
            _step("Bevaka betalning — {kund}", 31, "medium", ["faktura"], workday=True),
        ]},
        {"id": "bilstereo", "name": "Bilstereo-installation", "gcal": False, "steps": [
            _step("Beställ material — {kund}", -7, "medium"),
            _step("Installation — {kund}", 0, "high"),
            _step("Skicka faktura — {kund}", 1, "high", ["faktura"], workday=True),
            _step("Betalningspåminnelse om obetald — {kund}", 31, "medium", ["faktura"], workday=True),
        ]},
    ]


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def coerce_step(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = _clean(raw.get("title"), MAX_TITLE)
    if not title:
        return None
    try:
        days = int(raw.get("days", 0))
    except (TypeError, ValueError):
        days = 0
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    prio = str(raw.get("priority") or "none")
    if prio not in PRIORITIES:
        prio = "none"
    tags = pp.parse_tags(", ".join(raw["tags"]) if isinstance(raw.get("tags"), list) else raw.get("tags"))
    amount = raw.get("amount_cents")
    amount = amount if isinstance(amount, int) and not isinstance(amount, bool) and 0 < amount <= 10 ** 12 else 0
    return {"title": title, "days": days, "priority": prio, "tags": tags,
            "amount_cents": amount, "workday": bool(raw.get("workday", False))}


def coerce_template(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = _clean(raw.get("name"), MAX_NAME)
    if not name:
        return None
    steps_raw = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    steps = [s for s in (coerce_step(x) for x in steps_raw[:MAX_STEPS]) if s]
    tid = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("id") or ""))[:16] or new_id()
    return {"id": tid, "name": name, "gcal": bool(raw.get("gcal", False)), "steps": steps}


def templates_path(data_dir: Any) -> Path:
    return Path(str(data_dir)) / FILENAME


def load_templates(data_dir: Any) -> List[Dict[str, Any]]:
    """Mallarna. Saknas filen → startmallarna. Trasig fil → startmallarna (filen rörs inte förrän du sparar)."""
    p = templates_path(data_dir)
    if not p.exists():
        return default_templates()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("templates") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ValueError("fel format")
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} {FILENAME} kunde inte läsas ({e}) — använder startmallarna")
        return default_templates()
    out: List[Dict[str, Any]] = []
    seen = set()
    for r in raw[:MAX_TEMPLATES]:
        t = coerce_template(r)
        if t and t["id"] not in seen:
            seen.add(t["id"])
            out.append(t)
    return out


def save_templates(data_dir: Any, templates: List[Dict[str, Any]]) -> bool:
    """Atomisk skrivning (tmp + replace) — en avbruten sparning lämnar den gamla filen hel."""
    try:
        clean = [t for t in (coerce_template(x) for x in (templates or [])[:MAX_TEMPLATES]) if t]
        p = templates_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": VERSION, "templates": clean}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte spara mallarna: {e}")
        return False


# ------------------------------------------------------------------------- bygga uppgifter -------
def render_title(title: str, customer: str = "") -> str:
    """'Skicka faktura — {kund}' + 'Anna' → 'Skicka faktura — Anna'. Utan namn tas platshållaren bort snyggt."""
    cust = _clean(customer, 80)
    t = str(title or "")
    if PLACEHOLDER in t:
        if cust:
            t = t.replace(PLACEHOLDER, cust)
        else:
            t = re.sub(r"\s*[—–-]?\s*" + re.escape(PLACEHOLDER), "", t)
            t = t.replace(PLACEHOLDER, "")
    elif cust:
        t = f"{t} — {cust}"
    return _clean(t, 500)


def build_tasks(template: Dict[str, Any], job_date: date, customer: str = "") -> List[Dict[str, Any]]:
    """Uppgifterna som mallen ger för en viss jobbdag (förhandsvisning och skapande använder samma lista)."""
    out: List[Dict[str, Any]] = []
    for s in (template or {}).get("steps", []):
        d = job_date + timedelta(days=int(s.get("days", 0)))
        if s.get("workday"):
            d = pp.shift_to_workday(d, "next")
        out.append({"title": render_title(s.get("title", ""), customer), "due_date": d.isoformat(),
                    "priority": s.get("priority") or "none", "tags": list(s.get("tags") or []),
                    "amount_cents": int(s.get("amount_cents") or 0)})
    return [x for x in out if x["title"]]


def create_tasks(store: Any, items: List[Dict[str, Any]]) -> List[str]:
    """Skapa uppgifterna i butiken. Returnerar id:n (stannar om butiken är full)."""
    ids: List[str] = []
    for it in items:
        tid = store.add_task(it["title"], priority=it.get("priority") or "none", due_date=it["due_date"],
                             tags=list(it.get("tags") or []))
        if not tid:
            break
        ids.append(tid)
        if it.get("amount_cents") and hasattr(store, "set_amount"):
            store.set_amount(tid, int(it["amount_cents"]))
    return ids


def unique_name(templates: List[Dict[str, Any]], base: str) -> str:
    """'Ny mall' → 'Ny mall' om ledigt, annars 'Ny mall 2', 'Ny mall 3' …"""
    names = {t["name"].lower() for t in templates}
    cand, n = base, 2
    while cand.lower() in names:
        cand = f"{base} {n}"
        n += 1
    return cand[:MAX_NAME]


def duplicate_name(templates: List[Dict[str, Any]], base: str) -> str:
    names = {t["name"].lower() for t in templates}
    cand = f"{base} (kopia)"
    n = 2
    while cand.lower() in names:
        cand = f"{base} (kopia {n})"
        n += 1
    return cand[:MAX_NAME]


# ------------------------------------------------------------------------------- Google ----------
def google_ready(data_dir: Any) -> bool:
    """Är Google Calendar kopplat (token finns och biblioteken är installerade)? Inget nätverk."""
    try:
        return bool(gcal.is_google_library_available() and gcal.is_connected(data_dir))
    except Exception:
        return False


def _notify(cb: Optional[Callable[[Dict[str, Any]], None]], title: str, ok: bool, message: str) -> None:
    ev = {"ok": ok, "action": "mall", "title": title, "message": message}
    try:
        (cb or EVENTS.append)(ev)
    except Exception:
        pass


def export_worker(data_dir: Any, find_task: Callable[[str], Optional[Dict[str, Any]]], ids: List[str],
                  options: Dict[str, Any], label: str, notify: Optional[Callable[[Dict[str, Any]], None]] = None,
                  service_factory: Optional[Callable[[Any], Any]] = None,
                  connected: Optional[Callable[[Any], bool]] = None,
                  delays: tuple = RETRY_DELAYS, sleep: Callable[[float], None] = None) -> Dict[str, Any]:
    """Skicka uppgifterna till Google Calendar (körs i en tråd). Försöker igen vid nätfel; skickar aldrig
    något som inte är med i ``ids``. Returnerar sammanställningen (för tester)."""
    import time
    sleep = sleep or time.sleep
    is_conn = connected or google_ready
    svc_factory = service_factory or gcal.build_calendar_service
    cid = str(options.get("calendar_id") or gcal.DEFAULT_CALENDAR_ID)
    if not is_conn(data_dir):
        msg = "Google Calendar är inte kopplat, så uppgifterna skickades inte (de är skapade). Koppla under ☁️ Google Calendar."
        _notify(notify, label, False, msg)
        return {"ok": False, "reason": "inte kopplat"}
    attempt = 0
    while True:
        try:
            tasks = [t for t in (find_task(i) for i in ids) if t]
            if not tasks:
                return {"ok": True, "skapade": 0, "total": 0}
            service = svc_factory(data_dir)
            res = gcal.push_tasks(service, cid, tasks, gcal.load_event_map(data_dir),
                                  color_by_priority=bool(options.get("color", True)),
                                  done_style=str(options.get("done_style") or gcal.DEFAULT_DONE_STYLE),
                                  history=gcal.load_history(data_dir))
        except gcal.GoogleCalendarError as e:
            err = e.user_message
            res = None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            res = None
        if res is not None:
            ok_n = res.get("skapade", 0) + res.get("uppdaterade", 0)
            bad = res.get("misslyckade", 0)
            if bad and ok_n < res.get("total", 0) and attempt < len(delays):
                pass  # en del misslyckades (t.ex. nät) → nytt försök nedan; redan skickade uppdateras, dubbleras inte
            else:
                _notify(notify, label, bad == 0,
                        f"{ok_n} uppgifter skickade till Google Calendar." if not bad
                        else f"{ok_n} av {res.get('total', 0)} uppgifter skickades; {bad} misslyckades "
                             f"(skicka resten via ☁️ Google Calendar).")
                logger.info(f"{LOG_PREFIX} '{label}': {ok_n} skickade, {bad} misslyckade")
                return {"ok": bad == 0, **{k: res.get(k) for k in ("skapade", "uppdaterade", "hoppade", "misslyckade", "total")}}
        if attempt >= len(delays):
            _notify(notify, label, False, f"Kunde inte skicka till Google Calendar: {err if res is None else 'se loggen'}. "
                                          f"Skicka via ☁️ Google Calendar när nätet är tillbaka.")
            return {"ok": False, "reason": "gav upp"}
        sleep(delays[attempt])
        attempt += 1


def export_async(data_dir: Any, find_task: Callable[[str], Optional[Dict[str, Any]]], ids: List[str],
                 options: Dict[str, Any], label: str, **kw: Any) -> Optional[threading.Thread]:
    """Starta exporten i en daemon-tråd (ingen Qt, ingen väntan i gränssnittet)."""
    if not ids:
        return None
    t = threading.Thread(target=export_worker, args=(data_dir, find_task, list(ids), dict(options), label),
                         kwargs=kw, daemon=True, name="mall-gcal")
    t.start()
    return t
