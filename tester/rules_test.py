#!/usr/bin/env python3
"""
rules_test.py — tester för core/rules.py (regler: villkor → åtgärder).

Kör:  python tester/rules_test.py
Använder en riktig TaskStore i en tillfällig mapp. Ingen Qt behövs.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import rules as rl  # noqa: E402
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name}")


def rule(name, conds, actions, **kw):
    r, p = rl.normalize_rule({"name": name, "conditions": conds, "actions": actions, **kw})
    assert r, p
    return r


def get(store, tid):
    return next(t for t in store.active_tasks() if t["id"] == tid)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rules_test_"))
    store = TaskStore(data_dir_override=str(tmp / "store"))
    data = tmp / "data"

    # --- normalize_rule -----------------------------------------------------
    r, p = rl.normalize_rule({"name": "", "conditions": [], "actions": {}})
    check("tom regel avvisas", r is None and p)
    r, p = rl.normalize_rule({"name": "x", "conditions": [{"field": "title", "op": "contains", "value": "a"}],
                              "actions": {}})
    check("regel utan åtgärd avvisas", r is None)
    r, p = rl.normalize_rule({"name": "x", "conditions": [{"field": "title", "op": "regex", "value": "("}],
                              "actions": {"pin": True}})
    check("ogiltigt regex avvisas", r is None)
    r, p = rl.normalize_rule({"name": "x", "conditions": [{"field": "title", "op": "contains", "value": "a"}],
                              "actions": {"add_tags": "Jobb, ekonomi,jobb"}})
    check("taggar från kommatext, utan dubbletter", r and r["actions"]["add_tags"] == ["jobb", "ekonomi"])

    # --- uppgifter ----------------------------------------------------------
    a = store.add_task("Betala faktura")
    b = store.add_task("Fråga om semester")
    c = store.add_task("Vanlig uppgift")
    d = store.add_task("Mailad uppgift")
    store.set_task_metadata(d, "email_from", "Chef <chef@firma.se>")
    store.set_task_metadata(d, "email_subject", "Brådskande: rapport")
    e = store.add_task("Faktura-mail utan datum")
    store.set_task_metadata(e, "email_subject", "Faktura 123")
    store.set_due_date(e, "2030-01-01")

    rs = rl.load_rules(data)
    check("tomt regelset", rs.all() == [] and rs.last_run() is None)
    res = rl.run_rules(store, rs, trigger="manual")
    check("inga regler → inget händer", res["rules"] == 0 and res["changed"] == 0)
    check("summering utan regler", "inga aktiva" in rl.summarize(res).lower())

    rs.upsert(rule("Fakturor", [{"field": "title", "op": "contains", "value": "faktura"},
                                {"field": "subject", "op": "contains", "value": "faktura"}],
                   {"priority": "high", "add_tags": ["ekonomi"], "due_in_days": 3}, match="any"))
    rs.upsert(rule("Från chefen", [{"field": "from", "op": "contains", "value": "chef@"}],
                   {"priority": "high", "pin": True}, mail_only=True))
    rs.upsert(rule("Semester", [{"field": "title", "op": "regex", "value": "^fråga.*semester$"}],
                   {"priority": "low", "add_tags": ["hr"]}))
    check("tre regler sparade", len(rl.load_rules(data).all()) == 3)

    today = date(2026, 10, 12)
    res = rl.run_rules(store, rs, trigger="manual", today=today)
    check("alla aktiva kontrollerade", res["checked"] == 5)
    check("4 ändrade", res["changed"] == 4)
    ta = get(store, a)
    check("faktura: prio high", ta["priority"] == "high")
    check("faktura: tagg", "ekonomi" in ta["tags"])
    check("faktura: förfallodatum +3 dagar", ta["due_date"] == (today + timedelta(days=3)).isoformat())
    check("semester: low + tagg", get(store, b)["priority"] == "low" and "hr" in get(store, b)["tags"])
    check("ej matchande orörd", get(store, c)["priority"] == "none" and not get(store, c)["tags"])
    td = get(store, d)
    check("mail från chef: prio + nålad", td["priority"] == "high" and td.get("pinned") is True)
    check("befintligt datum skrivs aldrig över", get(store, e)["due_date"] == "2030-01-01")

    # mail_only: manuell uppgift med 'chef@' i titel ska inte matcha
    f = store.add_task("chef@firma.se ringer")
    rl.run_rules(store, rs, trigger="manual", today=today)
    check("mail_only matchar inte vanlig uppgift", get(store, f)["priority"] == "none" and not get(store, f).get("pinned"))

    # idempotent
    res3 = rl.run_rules(store, rs, trigger="manual", today=today)
    check("andra körningen ändrar inget", res3["changed"] == 0)

    # --- senast körd / timkörning ---------------------------------------------
    check("last_run sparas", rs.last_run() is not None)
    check("last_run överlever omladdning", rl.load_rules(data).last_run() is not None)
    now = datetime.now(timezone.utc)
    check("ej dags direkt efter körning", not rl.due_for_hourly(rs, now + timedelta(minutes=30)))
    check("dags efter en timme", rl.due_for_hourly(rs, now + timedelta(minutes=61)))
    check("dags om aldrig körd", rl.due_for_hourly(rl.load_rules(tmp / "annan")))

    # --- mailkörning: bara angivna uppgifter, rör inte last_run -------------------
    before = rs.last_run()
    g = store.add_task("Ny faktura")
    h = store.add_task("Faktura som inte ska röras")
    rm = rl.run_for_tasks(store, rs, [g])
    check("mailkörning: bara angiven uppgift", rm["checked"] == 1 and get(store, g)["priority"] == "high"
          and get(store, h)["priority"] == "none")
    check("mailkörning skjuter inte upp timkörningen", rs.last_run() == before)

    # --- redigering --------------------------------------------------------------
    ids = [x["id"] for x in rs.all()]
    check("flytta ner", rs.move(ids[0], 1) and rs.all()[1]["id"] == ids[0])
    check("slå av", rs.set_enabled(ids[0], False) and len(rs.enabled()) == 2)
    check("ta bort", rs.remove(ids[0]) and len(rs.all()) == 2)
    check("describe_rule ger text", isinstance(rl.describe_rule(rs.all()[0]), str) and rl.describe_rule(rs.all()[0]))

    # trasig fil
    (data / rl.RULES_FILENAME).write_text("{inte json", encoding="utf-8")
    check("trasig fil → tomt, ingen krasch", rl.load_rules(data).all() == [])

    print(f"\nrules_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
