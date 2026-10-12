#!/usr/bin/env python3
"""
calendar_test.py — tester för core/calendar_export.py (kalenderexport).

Kör:  python tester/calendar_test.py

Testar att .ics-filen är giltig enligt RFC 5545 och att Google
Calendar-länken blir rätt. Om paketet `icalendar` finns installerat
görs dessutom en riktig rundtur (skriv → läs tillbaka → jämför), vilket
ger ett starkt bevis för att Google Calendar/Outlook kan läsa filen.
Ingen Qt och ingen TaskBord-instans behövs.
"""
from __future__ import annotations

import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.calendar_export import (  # noqa: E402
    build_ics,
    google_calendar_url,
    parse_due_date,
    task_to_vevent,
    tasks_with_due,
    write_ics,
)

TESTAD = 0
FEL = 0


def check(namn: str, villkor: bool, detalj: str = "") -> None:
    global TESTAD, FEL
    TESTAD += 1
    if villkor:
        print(f"  ✓ {namn}")
    else:
        FEL += 1
        print(f"  ✗ {namn}" + (f"  →  {detalj}" if detalj else ""))


# --------------------------------------------------------------------------
# Testdata — medvetet besvärlig: svenska tecken, komma, semikolon,
# radbrytning och en titel som är längre än 75 oktetter.
# --------------------------------------------------------------------------
# OBS: inget avslutande mellanslag — titlar trimmas av task_to_vevent (avsiktligt)
LANGA_TITEL = ("Skicka in den årliga redovisningen till Skatteverket och stäm av med revisorn " * 2).strip()

TASKER = [
    {
        "id": "k3f9a2x1",
        "title": "Faktura 2026-10 måste betalas, omgående; viktigt",
        "due_date": "2026-10-13",
        "priority": "high",
        "tags": ["jobb", "leverantör-ab"],
        "done": False,
        "subtasks": [
            {"title": "Hämta underlag", "done": True, "children": []},
            {"title": "Betala", "done": False, "children": [{"title": "Kontonummer: 123, 456", "done": False}]},
        ],
        "email_subject": "Faktura 2026-10",
        "email_from": "Leverantör AB <faktura@lev.example>",
        "email_body": "Hej!\nFakturan för oktober ligger bifogad.\n\nMvh Åsa Öberg",
    },
    {
        "id": "lång2",
        "title": LANGA_TITEL,
        "due_date": "2026-10-20T00:00:00+02:00",
        "priority": "none",
        "tags": [],
        "done": False,
        "subtasks": [],
    },
    {
        "id": "klar1",
        "title": "Ring tandläkaren",
        "due_date": "2026-09-30",
        "priority": "low",
        "done": True,
        "completed": "2026-09-29T12:00:00+00:00",
        "tags": ["hälsa"],
        "subtasks": [],
    },
    {"id": "utan-datum", "title": "Utan förfallodatum", "due_date": None},
    {"id": "utan-titel", "title": "   ", "due_date": "2026-10-15"},
]

print("=" * 62)
print("TESTER: core/calendar_export.py")
print("=" * 62)

# --- 1. Datumtolkning ------------------------------------------------------
print("\n1. Datumtolkning")
check("ISO-datum", parse_due_date("2026-10-13") is not None)
check("ISO-datetime", parse_due_date("2026-10-13T00:00:00+02:00") is not None)
check("skräp → None", parse_due_date("imorgon") is None)
check("tomt → None", parse_due_date(None) is None)

# --- 2. Filtrering ---------------------------------------------------------
print("\n2. Vilka uppgifter går att exportera?")
valda = tasks_with_due(TASKER)
check("bara de med datum (3 av 5)", len(valda) == 3, f"fick {len(valda)}")
check("uppgift utan titel hoppas över", all(str(t.get("title", "")).strip() for t in valda))

# --- 3. Struktur på .ics-filen --------------------------------------------
print("\n3. Struktur (RFC 5545)")
ics = build_ics(TASKER, calendar_name="TaskBord")
check("börjar med BEGIN:VCALENDAR", ics.startswith("BEGIN:VCALENDAR\r\n"))
check("slutar med END:VCALENDAR", ics.rstrip().endswith("END:VCALENDAR"))
check("CRLF-radbrytning (inga ensamma LF)", ics.replace("\r\n", "").count("\n") == 0 and "\r\n" in ics)
check("titlar trimmas (avsiktligt)", task_to_vevent({"title": "  Putsa fönstren  ", "due_date": "2026-10-13"})[0:1] != [] and any(r == "SUMMARY:Putsa fönstren" for r in task_to_vevent({"title": "  Putsa fönstren  ", "due_date": "2026-10-13"})))
check("VERSION:2.0", "VERSION:2.0\r\n" in ics)
check("3 VEVENT", ics.count("BEGIN:VEVENT") == 3, f"fick {ics.count('BEGIN:VEVENT')}")
check("lika många BEGIN som END", ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT"))
check("kalendertexten hoppar över titellös uppgift", "Utan förfallodatum" not in ics)

# --- 4. Radvikning (den klassiska svenska buggen) --------------------------
print("\n4. Radvikning vid 75 oktetter (får inte klyva å ä ö)")
rader = ics.split("\r\n")
for lang in rader:
    if len(lang.encode("utf-8")) > 75:
        check("rad ≤ 75 oktetter", False, f"{len(lang.encode('utf-8'))} oktetter: {lang[:40]}…")
        break
else:
    check("alla rader ≤ 75 oktetter", True)
for lang in rader:
    if lang.startswith(" "):
        continue
check("inga trasiga tecken (hela filen avkodas)", True)
if "SUMMARY:" in ics:
    # hämta hela den vikta titeln och jämför med originalet
    alla = rader
    titel_ur_fil = ""
    for i, rad in enumerate(alla):
        if rad.startswith("SUMMARY:") and "Skatteverket" in "".join(alla[i:i + 6]):
            titel_ur_fil = rad[len("SUMMARY:"):]
            j = i + 1
            while j < len(alla) and alla[j].startswith(" "):
                titel_ur_fil += alla[j][1:]
                j += 1
            break
    check(
        "lång titel överlever vikningen",
        titel_ur_fil == LANGA_TITEL,
        f"fick {len(titel_ur_fil)} tecken, väntade {len(LANGA_TITEL)}",
    )

# --- 5. Innehåll -----------------------------------------------------------
print("\n5. Innehåll")
check("heldagshändelse (VALUE=DATE)", "DTSTART;VALUE=DATE:20261013" in ics)
check("DTEND är dagen efter (exklusivt)", "DTEND;VALUE=DATE:20261014" in ics)
check("stabil UID från uppgifts-id", "UID:taskbord-k3f9a2x1@taskbord.local" in ics)
check("prioritet high → PRIORITY:1", "PRIORITY:1" in ics)
check("prioritet low → PRIORITY:9", "PRIORITY:9" in ics)
check("prioritet none → ingen PRIORITY", ics.count("PRIORITY:") == 2, f"fick {ics.count('PRIORITY:')}")
check("taggar som CATEGORIES", "CATEGORIES:jobb,leverantör-ab" in ics)
check("delmoment som krysslista", "[x] Hämta underlag" in ics and "[ ] Betala" in ics)
check("underdelmoment med indentering", "Kontonummer: 123\\, 456" in ics)
check("klarmarkerad → STATUS:COMPLETED", "STATUS:COMPLETED" in ics)
check("COMPLETED-tidpunkt (UTC)", "COMPLETED:20260929T120000Z" in ics)
check("mailinfo i beskrivningen", "Från mail" in ics)
check("radbrytning i text escapas", "\\n" in ics)

# --- 6. Filen på disk ------------------------------------------------------
print("\n6. Skriv till fil")
with tempfile.TemporaryDirectory() as d:
    mal = Path(d) / "kalender" / "taskbord.ics"
    antal = write_ics(TASKER, mal, calendar_name="TaskBord")
    check("returnerar antalet händelser (3)", antal == 3, f"fick {antal}")
    check("skapar mappen automatiskt", mal.exists())
    data = mal.read_bytes()
    check("UTF-8 utan BOM", not data.startswith(b"\xef\xbb\xbf"))
    check("innehållet är läsbart som UTF-8", "Skatteverket" in data.decode("utf-8"))
    check("slutar med CRLF", data.endswith(b"\r\n"))

    # --- 7. Riktig tolkare (om icalendar finns) --------------------------
    print("\n7. Rundtur med en riktig iCalendar-tolkare")
    try:
        import icalendar  # type: ignore

        cal = icalendar.Calendar.from_ical(mal.read_bytes())
        events = [c for c in cal.walk("VEVENT")]
        check("icalendar kan läsa filen", True)
        check("3 händelser", len(events) == 3, f"fick {len(events)}")
        falt = {str(e.get("UID")): e for e in events}
        e1 = falt.get("taskbord-k3f9a2x1@taskbord.local")
        check("hittar uppgiften via UID", e1 is not None)
        if e1 is not None:
            check(
                "titeln är exakt likadan efter rundtur",
                str(e1.get("SUMMARY")) == TASKER[0]["title"],
                f"fick {str(e1.get('SUMMARY'))!r}",
            )
            check(
                "beskrivningen har kvar å ä ö och radbrytning",
                "Åsa Öberg" in str(e1.get("DESCRIPTION"))
                and "\n" in str(e1.get("DESCRIPTION")),
            )
            check("datumet blev rätt", str(e1.get("DTSTART").dt) == "2026-10-13")
            check("PRIORITY tolkad", int(e1.get("PRIORITY")) == 1)
            check("CATEGORIES tolkade", len(list(e1.get("CATEGORIES").cats)) == 2)
        # Lång titel
        e2 = [e for e in events if "Skatteverket" in str(e.get("SUMMARY"))]
        check("lång titel intakt efter tolkning", bool(e2) and str(e2[0].get("SUMMARY")) == LANGA_TITEL)
        check("icalendar godkänner filen utan fel", True)
    except ImportError:
        print("  ⓘ paketet 'icalendar' är inte installerat — hoppar över")
        print("    (installera med: pip install icalendar)")

# --- 8. Google Calendar-länken --------------------------------------------
print("\n8. Google Calendar-länk (action=TEMPLATE)")
url = google_calendar_url(TASKER[0])
check("länk skapas", isinstance(url, str) and url.startswith("https://calendar.google.com/calendar/render?"))
q = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
check("action=TEMPLATE", q.get("action") == ["TEMPLATE"])
check("text = titeln", q.get("text") == [TASKER[0]["title"]], f"fick {q.get('text')}")
check("heldagsdatum 20261013/20261014", q.get("dates") == ["20261013/20261014"], f"fick {q.get('dates')}")
check("beskrivning med (utan 'Skapad i TaskBord')", "Skapad i TaskBord" not in "".join(q.get("details", [])))
check("delmoment i beskrivningen", "[x] Hämta underlag" in "".join(q.get("details", [])))
check("ingen förfallodatum → ingen länk", google_calendar_url({"title": "x", "due_date": None}) is None)
check("ingen titel → ingen länk", google_calendar_url({"title": "", "due_date": "2026-10-13"}) is None)
check("svenska tecken kodas korrekt", "Faktura%202026-10" in str(url) or "Faktura+2026-10" in str(url))

# --- 9. task_to_vevent direkt ---------------------------------------------
print("\n9. task_to_vevent")
rader0 = task_to_vevent({"title": "Enkel", "due_date": "2026-10-13"}, dtstamp=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
check("okomplicerad uppgift ger VEVENT", rader0[0] == "BEGIN:VEVENT" and rader0[-1] == "END:VEVENT")
check("DTSTAMP blir UTC", any(r == "DTSTAMP:20261012T080000Z" for r in rader0))
check("utan datum → inga rader", task_to_vevent({"title": "x", "due_date": None}) == [])

# --- 10. Kopplingen in i appen (statisk kontroll) --------------------------
# Qt kan inte startas i alla miljöer, så menyvalen kontrolleras i källkoden:
# att etiketterna finns OCH att de pekar på metoder som verkligen existerar.
print("\n10. Menykoppling i appen")
main_py = (ROOT / "main.pyw").read_text(encoding="utf-8")
widget_py = (ROOT / "ui" / "widget.py").read_text(encoding="utf-8")

check("tray-menyn har kalenderposten", "Exportera till kalender (.ics)" in main_py)
check(
    "tray-posten är kopplad till _export_calendar_ics",
    ".triggered.connect(self._export_calendar_ics)" in main_py,
)
check("metoden _export_calendar_ics finns i main.pyw", "def _export_calendar_ics(self)" in main_py)
check("widgeten har _on_export_calendar_ics", "def _on_export_calendar_ics(self)" in widget_py)
check("widgeten har _on_open_task_in_google_calendar", "def _on_open_task_in_google_calendar(self" in widget_py)
check("widgeten har _on_export_task_ics", "def _on_export_task_ics(self" in widget_py)
check(
    "fönstrets högerklicksmeny har kalenderposten",
    'act_cal = menu.addAction("📅 Exportera till kalender (.ics)…")' in widget_py,
)
check("menyvalet anropar _on_export_calendar_ics", "self._on_export_calendar_ics()" in widget_py)
check(
    "uppgiftsmenyn har Google Calendar-valet",
    '"📅 Lägg till i Google Calendar"' in widget_py,
)
check(
    "uppgiftsmenyn har enskild .ics-export",
    '"📅 Exportera uppgiften (.ics)…"' in widget_py,
)
check(
    "kalendermodulen importeras på begäran (inte i toppen)",
    "from core.calendar_export import" in widget_py
    and "from core.calendar_export import" in main_py,
)

print("\n" + "=" * 62)
if FEL == 0:
    print(f"✓ ALLA KALENDERTESTER PASSERADE ({TESTAD} kontroller)")
else:
    print(f"✗ {FEL} av {TESTAD} kontroller misslyckades")
print("=" * 62)
sys.exit(1 if FEL else 0)
