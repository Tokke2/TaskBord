#!/usr/bin/env python3
"""
natural_dates_test.py — naturliga datum ("fre 14", "om 3 dagar", "nästa mån") i core/natural_dates.py
och i uppgiftsinmatningen (ui/widget_base.py parse_natural_input).

Kör:  python tester/natural_dates_test.py      (ingen Qt behövs)
"""
from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import natural_dates as nd  # noqa: E402

_ok = _fail = 0


def ck(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


T = date(2026, 11, 18)   # onsdag


def loader():
    src = (ROOT / "ui" / "widget_base.py").read_text(encoding="utf-8")
    keep = []
    for node in ast.parse(src).body:
        if (isinstance(node, ast.FunctionDef) and node.name in ("_resolve_day_expr", "parse_natural_input", "parse_compact_date")) or (
            isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_START_DAY_EXPR" for t in node.targets)
        ):
            keep.append(node)
    ns: dict = {"Any": Any, "Dict": Dict}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "widget_nl", "exec"), ns)
    return ns["parse_natural_input"]


def main() -> None:
    P = lambda s: nd.parse_date(s, T)   # noqa: E731
    ck("onsdag är veckodag 2", T.weekday() == 2)
    ck("idag/imorgon/övermorgon/igår", (P("idag"), P("imorgon"), P("i morgon"), P("övermorgon"), P("igår")) ==
       (T, date(2026, 11, 19), date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 17)))
    ck("fredag = närmaste fredag", P("fredag") == date(2026, 11, 20))
    ck("fre = fredag", P("fre") == date(2026, 11, 20))
    ck("onsdag idag räknas", P("onsdag") == T)
    ck("nästa onsdag = en vecka fram", P("nästa ons") == date(2026, 11, 25))
    ck("nästa mån", P("nästa mån") == date(2026, 11, 23))
    ck("nästa fredag", P("nästa fredag") == date(2026, 11, 20))
    ck("på fredag / senast fredag", P("på fredag") == P("senast fredag") == date(2026, 11, 20))
    ck("fre nästa vecka", P("fre nästa vecka") == date(2026, 11, 27))
    ck("nästa vecka = måndag", P("nästa vecka") == date(2026, 11, 23))
    ck("nästa månad = den 1:a", P("nästa månad") == date(2026, 12, 1))
    ck("om 3 dagar", P("om 3 dagar") == date(2026, 11, 21))
    ck("om 1 dag", P("om 1 dag") == date(2026, 11, 19))
    ck("om en vecka", P("om en vecka") == date(2026, 11, 25))
    ck("om två veckor", P("om två veckor") == date(2026, 12, 2))
    ck("om 2 månader", P("om 2 månader") == date(2027, 1, 18))
    ck("om en månad klämmer dagen", nd.parse_date("om en månad", date(2026, 1, 31)) == date(2026, 2, 28))
    ck("slutet av månaden", P("slutet av månaden") == date(2026, 11, 30))
    ck("15 nov (passerat → nästa år)", P("15 nov") == date(2027, 11, 15))
    ck("25 dec", P("25 dec") == date(2026, 12, 25))
    ck("15 november 2026", P("15 november 2026") == date(2026, 11, 15))
    ck("1 jan 2027", P("1 jan 2027") == date(2027, 1, 1))
    ck("vecka 47 = måndag", P("vecka 47") == date(2026, 11, 16))
    ck("vecka 2 → nästa år", P("v 2") == date(2027, 1, 11))
    ck("ISO", P("2026-12-24") == date(2026, 12, 24))
    ck("ÅÅMMDD", P("261130") == date(2026, 11, 30))
    ck("d/m", P("3/12") == date(2026, 12, 3))
    ck("d/m passerat → nästa år", P("3/11") == date(2027, 11, 3))
    ck("d/m-ÅÅ", P("3/11-26") == date(2026, 11, 3))
    ck("ogiltigt datum 31/2", P("31/2") is None)
    ck("ett tal = nästa den:e", P("20") == date(2026, 11, 20) and P("14") == date(2026, 12, 14))
    ck("ett tal 31 i november hoppar till dec", P("31") == date(2026, 12, 31))
    ck("fre 14: ingen fredag den 14:e inom 3 mån → närmaste 14:e", P("fre 14") == date(2026, 12, 14))
    ck("tors 26: 26 nov är torsdag", P("tors 26") == date(2026, 11, 26))
    ck("fre 20: 20 nov är fredag", P("fre 20") == date(2026, 11, 20))
    ck("lör 28", P("lör 28") == date(2026, 11, 28))
    ck("fredag 20 (hel veckodag + dag)", P("fredag 20") == date(2026, 11, 20))
    ck("fre 14/11 (datum vinner)", P("fre 14/11") == date(2027, 11, 14))
    ck("skräp → None", P("bla") is None and P("") is None and P("32") is None and P("0") is None)
    ck("versaler och mellanslag", P("  Fre   20 ") == date(2026, 11, 20))
    ck("klockslag kl", nd.parse_datetime("fre 20 kl 15", T) == (date(2026, 11, 20), "15:00"))
    ck("klockslag 9:30", nd.parse_datetime("imorgon 9:30", T) == (date(2026, 11, 19), "09:30"))
    ck("klockslag 15.30", nd.parse_datetime("2026-12-01 15.30", T) == (date(2026, 12, 1), "15:30"))
    ck("blott tal efter datum utan kl = ingen tid", nd.parse_datetime("imorgon 15", T) == (None, None))
    ck("datum utan tid", nd.parse_datetime("om 3 dagar", T) == (date(2026, 11, 21), None))
    ck("ogiltig tid", nd.parse_datetime("imorgon kl 25", T) == (None, None))
    F = lambda s: nd.find_in_text(s, T)   # noqa: E731
    ck("i titel: nästa mån", F("ring kund nästa mån")[0] == date(2026, 11, 23))
    ck("i titel: fre 14", F("faktura fre 20 betala")[0] == date(2026, 11, 20))
    ck("i titel: om 3 dagar", F("jobb om 3 dagar")[0] == date(2026, 11, 21))
    ck("i titel: 14 nov", F("möte 14 nov")[0] == date(2027, 11, 14))
    ck("i titel: vecka 47", F("avsluta vecka 47")[0] == date(2026, 11, 16))
    ck("i titel: ensam förkortning ignoreras", F("mån") is None and F("tis ons") is None and F("han fre sig") is None)
    ck("i titel: ensamt tal ignoreras", F("Faktura 14 st") is None)
    ck("i titel: fredag 15 lämnas åt klockslagstolkningen", F("fredag 15") is None)
    ck("i titel: positionerna stämmer", (lambda r: "ring nästa mån x"[r[1]:r[2]] == "nästa mån")(F("ring nästa mån x")))
    ck("describe", nd.describe(date(2026, 11, 20), T) == "fredag 20 november 2026 (om 2 dagar)")
    ck("add_months", nd.add_months(date(2026, 12, 31), 2) == date(2027, 2, 28))

    # --- uppgiftsinmatningen (ui/widget_base.py) ---
    pn = loader()
    today = date.today()
    r = pn("ring kund nästa mån")
    nm = nd.next_weekday(today, 0, after=True)
    ck("inmatning: nästa mån → datum + ren titel", r["due_date"] == nm.isoformat() and r["title"] == "ring kund", repr(r))
    r = pn("betala om 3 dagar kl 15 !hög #hem")
    ck("inmatning: om 3 dagar + tid + prio + tagg",
       r["due_date"] == f"{(today.fromordinal(today.toordinal() + 3)).isoformat()}T15:00" and r["priority"] == "high"
       and r["tags"] == ["hem"] and r["title"] == "betala", repr(r))
    r = pn("möte 25 dec")
    ck("inmatning: 25 dec", r["due_date"] and r["due_date"][5:10] == "12-25" and r["title"] == "möte", repr(r))
    r = pn("fredag 15")
    ck("inmatning: 'fredag 15' är fortfarande fredag kl 15", (r["due_date"] or "").endswith("T15:00"), repr(r))
    r = pn("köp mjölk imorgon")
    ck("inmatning: imorgon som förut", r["due_date"] == nd.parse_date("imorgon", today).isoformat(), repr(r))
    r = pn("byt vindruta start nästa mån")
    ck("inmatning: start nästa mån", r["start_date"] == nd.next_weekday(today, 0, after=True).isoformat()
       and r["title"] == "byt vindruta", repr(r))
    r = pn("planera start om en vecka")
    ck("inmatning: start om en vecka", r["start_date"] == nd.parse_date("om en vecka", today).isoformat(), repr(r))
    r = pn("vanlig titel utan datum")
    ck("inmatning: ingen gissning i vanlig titel", r["due_date"] is None and r["title"] == "vanlig titel utan datum", repr(r))

    r = pn("9 december julmiddag hemma hos hasse", date_as_start=True)
    ck("snabbinmatning: datum blir startdatum och titeln behålls",
       r["start_date"][5:] == "12-09" and r["due_date"] is None
       and r["title"] == "julmiddag hemma hos hasse", repr(r))
    r = pn("vanlig titel utan datum", date_as_start=True)
    ck("snabbinmatning: utan datum finns inget startdatum", r["start_date"] is None, repr(r))

    r = pn("9 december julmiddag hemma hos hasse kl 18", date_as_start=True)
    ck("snabbinmatning: datum och klockslag", r["start_date"][5:] == "12-09"
       and r["due_date"] == r["start_date"] + "T18:00"
       and r["title"] == "julmiddag hemma hos hasse", repr(r))
    r = pn("julmiddag kl 18", date_as_start=True)
    ck("snabbinmatning: bara klockslag använder idag", r["start_date"] == today.isoformat()
       and r["due_date"] == today.isoformat() + "T18:00", repr(r))

    doc = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    ck("MANUAL beskriver naturliga datum", "Naturliga datum" in doc and "nästa mån" in doc)


main()
print(f"\nnatural_dates_test: {_ok} lyckades, {_fail} misslyckades")
sys.exit(1 if _fail else 0)
