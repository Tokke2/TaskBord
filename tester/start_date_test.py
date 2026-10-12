#!/usr/bin/env python3
"""
start_date_test.py — startdatum för uppgifter (kalenderexport) + fält som ska överleva omstart.

Kör:  python tester/start_date_test.py
Ingen Qt behövs (TaskStore körs mot en tillfällig mapp).
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import google_calendar as gcal  # noqa: E402
from core.calendar_export import (  # noqa: E402
    build_ics, event_dates, google_calendar_url, has_calendar_date, task_to_vevent, tasks_with_due,
)
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name}")


def _load_nl_parser():
    """Hämtar parse_natural_input ur ui/widget.py utan att importera Qt (libGL saknas i CI)."""
    import ast
    from typing import Any, Dict
    src = (ROOT / "ui" / "widget.py").read_text(encoding="utf-8")
    keep = []
    for node in ast.parse(src).body:
        if (isinstance(node, ast.FunctionDef) and node.name in ("_resolve_day_expr", "parse_natural_input")) or (
            isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_START_DAY_EXPR" for t in node.targets)
        ):
            keep.append(node)
    ns: dict = {"Any": Any, "Dict": Dict}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "widget_nl", "exec"), ns)
    return ns["parse_natural_input"]


def main() -> int:
    d = date.fromisoformat
    only_due = {"id": "a", "title": "Bara slut", "due_date": "2026-10-16"}
    only_start = {"id": "b", "title": "Bara start", "start_date": "2026-10-14"}
    both = {"id": "c", "title": "Båda", "start_date": "2026-10-14", "due_date": "2026-10-16"}
    backwards = {"id": "d", "title": "Bakvänd", "start_date": "2026-10-20", "due_date": "2026-10-16"}
    none = {"id": "e", "title": "Inget"}

    # --- event_dates ------------------------------------------------------------
    check("bara förfallodatum", event_dates(only_due) == (d("2026-10-16"), d("2026-10-16")))
    check("bara startdatum räcker", event_dates(only_start) == (d("2026-10-14"), d("2026-10-14")))
    check("start + förfallodatum = intervall", event_dates(both) == (d("2026-10-14"), d("2026-10-16")))
    check("start efter förfallodatum ignoreras", event_dates(backwards) == (d("2026-10-16"), d("2026-10-16")))
    check("inget datum → None", event_dates(none) is None and not has_calendar_date(none))
    check("datetime-format fungerar", event_dates({"start_date": "2026-10-14T08:00:00+00:00"}) is not None)
    check("skräp-datum → None", event_dates({"start_date": "inte ett datum"}) is None)
    check("tasks_with_due tar med start-uppgifter",
          [t["id"] for t in tasks_with_due([only_due, only_start, both, none])] == ["a", "b", "c"])

    # --- .ics -------------------------------------------------------------------
    v = "\n".join(task_to_vevent(both))
    check("ics: DTSTART = startdag", "DTSTART;VALUE=DATE:20261014" in v)
    check("ics: DTEND = dagen efter förfallodatum", "DTEND;VALUE=DATE:20261017" in v)
    v = "\n".join(task_to_vevent(only_start))
    check("ics: bara start → en dag", "DTSTART;VALUE=DATE:20261014" in v and "DTEND;VALUE=DATE:20261015" in v)
    v = "\n".join(task_to_vevent(only_due))
    check("ics: bara förfallodatum oförändrat", "DTSTART;VALUE=DATE:20261016" in v and "DTEND;VALUE=DATE:20261017" in v)
    check("ics: ingen händelse utan datum", task_to_vevent(none) == [])
    check("ics: hel fil har 3 händelser", build_ics([only_due, only_start, both, none]).count("BEGIN:VEVENT") == 3)

    # --- Google-länk --------------------------------------------------------------
    url = google_calendar_url(both) or ""
    check("länk: dates = start/dagen efter slut", "20261014/20261017" in url.replace("%2F", "/"))
    check("länk: bara start fungerar", google_calendar_url(only_start) is not None)
    check("länk: inget datum → None", google_calendar_url(none) is None)

    # --- Google API-kropp -----------------------------------------------------------
    body = gcal.build_event_body(both)
    check("api: start", body["start"]["date"] == "2026-10-14")
    check("api: slut exklusivt (dagen efter förfallodatum)", body["end"]["date"] == "2026-10-17")
    body = gcal.build_event_body(only_start)
    check("api: bara start → en dag", body["start"]["date"] == "2026-10-14" and body["end"]["date"] == "2026-10-15")
    try:
        gcal.build_event_body(none)
        check("api: fel utan datum", False)
    except gcal.GoogleCalendarError as e:
        check("api: fel utan datum", "startdatum" in e.user_message)
    check("resolve_task_date = första dagen", gcal.resolve_task_date(both) == d("2026-10-14"))

    rader = gcal.describe_tasks_for_picker([only_due, only_start, both, none])
    if rader:
        check("väljare: start-uppgift går att välja", rader[1]["sendable"] is True)
        check("väljare: intervall visas", rader[2]["span"] == "2026-10-14 → 2026-10-16")
        check("väljare: utan datum går inte", rader[3]["sendable"] is False and "startdatum" in rader[3]["reason"])

    # --- store: spara, läs in igen, ta bort -------------------------------------------
    tmp = tempfile.mkdtemp(prefix="start_test_")
    s = TaskStore(data_dir_override=tmp)
    tid = s.add_task("Med start")
    check("set_start_date", s.set_start_date(tid, "2026-10-14") is True)
    check("samma värde → ingen ändring", s.set_start_date(tid, "2026-10-14") is False)
    s.set_task_metadata(tid, "email_path", "/mail/x.eml")
    s.set_task_metadata(tid, "email_subject", "Hej")
    s.save()
    s2 = TaskStore(data_dir_override=tmp)
    t = s2.active_tasks()[0]
    check("startdatum överlever omstart", t.get("start_date") == "2026-10-14")
    check("mailfält överlever omstart (📧-ikonen)", t.get("email_path") == "/mail/x.eml" and t.get("email_subject") == "Hej")
    check("ta bort startdatum", s2.set_start_date(tid, None) is True and "start_date" not in s2.active_tasks()[0])
    check("okänd uppgift → False", s2.set_start_date("finns-ej", "2026-10-14") is False)

    # --- återkommande: startdatum följer med -------------------------------------------
    idag = date.today()
    s3 = TaskStore(data_dir_override=tempfile.mkdtemp(prefix="start_rec_"))
    rid = s3.add_task("Vecko", due_date=(idag + timedelta(days=2)).isoformat())
    s3.set_start_date(rid, idag.isoformat())
    s3.set_recurring(rid, "weekly")
    s3.toggle_task(rid)
    nya = [x for x in s3.active_tasks() if x["id"] != rid]
    check("återkommande ger ny aktiv uppgift", len(nya) == 1)
    if nya:
        n = nya[0]
        gap = (date.fromisoformat(n["due_date"]) - date.fromisoformat(n["start_date"])).days if n.get("start_date") else None
        check("ny uppgift behåller avståndet start→slut", gap == 2)

    # --- startdatum i vanlig text ("byt vindruta start nästa vecka") ------------------
    nl = _load_nl_parser()
    idag = date.today()
    nasta_man = idag + timedelta(days=7 - idag.weekday())
    r = nl("Byt vindruta start nästa vecka")
    check("start nästa vecka → måndag nästa vecka", r["start_date"] == nasta_man.isoformat())
    check("titeln blir ren", r["title"] == "Byt vindruta")
    check("inget förfallodatum sätts av start", r["due_date"] is None)
    r = nl("Byt vindruta start 2026-10-19")
    check("start ISO-datum", r["start_date"] == "2026-10-19" and r["title"] == "Byt vindruta" and r["due_date"] is None)
    r = nl("Boka tid start om 3 dagar #bil !hög")
    check("start om 3 dagar + tagg + prio", r["start_date"] == (idag + timedelta(days=3)).isoformat()
          and r["tags"] == ["bil"] and r["priority"] == "high" and r["title"] == "Boka tid")
    r = nl("Rapport från imorgon imorgon")
    check("start och förfallodatum kan kombineras", r["start_date"] == (idag + timedelta(days=1)).isoformat()
          and r["due_date"] == (idag + timedelta(days=1)).isoformat())
    r = nl("Köp mjölk imorgon")
    check("utan 'start' blir det förfallodatum som förut", r["start_date"] is None and r["due_date"] == (idag + timedelta(days=1)).isoformat())
    r = nl("Mail från Anna om budget")
    check("'från Anna' är inget datum", r["start_date"] is None and r["title"] == "Mail från Anna om budget")
    r = nl("Starta bilen")
    check("'Starta bilen' är bara text", r["start_date"] is None and r["title"] == "Starta bilen")
    r = nl("Fika start fredag")
    check("start veckodag", r["start_date"] is not None and date.fromisoformat(r["start_date"]).weekday() == 4)

    print(f"\nstart_date_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
