"""
calendar_export.py — NY v8 (2026-10-12): exportera uppgifter till kalender.

Frågan var: *"kan man koppla ihop den med Google Calendar så man kan
exportera vissa uppgifter dit?"* — **Ja**, på två sätt. Båda är helt
lokala: appen skickar ingenting över nätet, inga konton eller nycklar
behövs (till skillnad från en full synk via Google Calendar API, som
kräver OAuth-uppsättning i Google Cloud).

  1. **.ics-fil** (`build_ics` / `write_ics`) — standardformatet iCalendar
     (RFC 5545) som importeras av Google Calendar, Outlook, Apple Kalender
     m.fl. I Google Calendar: *Inställningar → Importera och exportera*.
  2. **Google Calendar-länk** (`google_calendar_url`) — en adress som
     öppnar Google Calendar med uppgiften förifylld. Ett klick per uppgift,
     inget konto behövs i appen.

Varför VEVENT och inte VTODO: Google Calendar importerar VEVENT
(händelser) men struntar i VTODO (att-göra-poster). Varje uppgift blir
därför en heldagshändelse på sitt förfallodatum — eller, om uppgiften också har
ett startdatum, en flerdagarshändelse från start till förfallodatum. Har den bara
ett startdatum blir det en heldagshändelse på startdagen.

Bara stdlib — inga externa beroenden.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

# --------------------------------------------------------------------------
# Konstanter
# --------------------------------------------------------------------------
ICAL_LINE_LIMIT = 75  # RFC 5545: rader får vara max 75 oktetter
PRODID = "-//TaskBord//Kalenderexport//SV"
CALENDAR_NAME_DEFAULT = "TaskBord"
GOOGLE_TEMPLATE_URL = "https://calendar.google.com/calendar/render"

# RFC 5545 PRIORITY: 1 = högst, 9 = lägst, 0 = odefinierad
_PRIORITY_TO_ICAL: Dict[str, int] = {"high": 1, "medium": 5, "low": 9}
_PRIORITY_LABEL: Dict[str, str] = {
    "high": "Hög prioritet",
    "medium": "Normal prioritet",
    "low": "Låg prioritet",
}


# --------------------------------------------------------------------------
# Text-hjälpare (RFC 5545 kap. 3.3.11 + radbrytning kap. 3.1)
# --------------------------------------------------------------------------
def _escape_text(value: Any) -> str:
    """Escapera en TEXT-sträng enligt RFC 5545."""
    s = str(value if value is not None else "")
    # OBS: backslash först, annars escapar vi våra egna backslashes
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
    return s


def _fold_line(line: str, limit: int = ICAL_LINE_LIMIT) -> List[str]:
    """
    Radbryt en iCalendar-rad vid `limit` oktetter (UTF-8).

    Fortsättningsrader inleds med ett mellanslag och får då plats med
    `limit - 1` oktetter. Vikningen sker på TECKEN-nivå, så svenska
    tecken (å ä ö) kan aldrig klyvas mitt i — det är den klassiska
    buggen som ger trasiga kalenderfiler.
    """
    if len(line.encode("utf-8")) <= limit:
        return [line]
    delar: List[str] = []
    aktuell = ""
    anvant = 0
    utrymme = limit
    for ch in line:
        bredd = len(ch.encode("utf-8"))
        if anvant + bredd > utrymme:
            delar.append(aktuell)
            aktuell = ch
            anvant = bredd
            utrymme = limit - 1  # fortsättningsrad: ett mellanslag först
        else:
            aktuell += ch
            anvant += bredd
    if aktuell:
        delar.append(aktuell)
    return [delar[0]] + [" " + d for d in delar[1:]]


def _utc_stamp(moment: _datetime) -> str:
    """DTSTAMP-format: 20261012T081500Z (alltid UTC)."""
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _date_stamp(d: _date) -> str:
    """VALUE=DATE-format: 20261012."""
    return d.strftime("%Y%m%d")


# --------------------------------------------------------------------------
# Uppgiftshjälpare
# --------------------------------------------------------------------------
def parse_due_date(value: Any) -> Optional[_date]:
    """
    Tolka `due_date` från en uppgift.

    Tar ISO-datum ("2026-10-13") och ISO-datetime
    ("2026-10-13T00:00:00+00:00") — alltid samma tolkning i hela appen.
    """
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return _datetime.fromisoformat(s).date()
    except Exception:
        pass
    try:  # sista utväg: första 10 tecknen ("2026-10-13T..." → "2026-10-13")
        return _date.fromisoformat(s[:10])
    except Exception:
        return None


def has_due_date(task: Dict[str, Any]) -> bool:
    """Sant om uppgiften har ett FÖRFALLODATUM."""
    return parse_due_date(task.get("due_date")) is not None


def event_dates(task: Dict[str, Any]) -> Optional[Tuple[_date, _date]]:
    """
    Dagarna uppgiften upptar i kalendern: (första dagen, sista dagen) — båda inkluderade.

    * start + förfallodatum  → från start till förfallodatum (om start ligger EFTER
                               förfallodatum ignoreras starten, så ingen händelse blir "bakvänd")
    * bara förfallodatum     → den dagen
    * bara startdatum        → startdagen
    * inget av dem           → None (kan inte bli en kalenderhändelse)
    """
    due = parse_due_date(task.get("due_date"))
    start = parse_due_date(task.get("start_date"))
    if due is not None:
        if start is not None and start <= due:
            return start, due
        return due, due
    if start is not None:
        return start, start
    return None


def has_calendar_date(task: Dict[str, Any]) -> bool:
    """Sant om uppgiften har startdatum ELLER förfallodatum — räcker för kalendern."""
    return event_dates(task) is not None


def tasks_with_due(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Uppgifterna som kan bli kalenderhändelser: de med startdatum eller förfallodatum."""
    return [
        t for t in (tasks or [])
        if isinstance(t, dict) and str(t.get("title", "")).strip() and has_calendar_date(t)
    ]


def _subtask_lines(subs: List[Dict[str, Any]], djup: int = 0) -> List[str]:
    """Delmoment som krysslista (rekursivt, för underdelmoment)."""
    rader: List[str] = []
    for s in subs or []:
        if not isinstance(s, dict):
            continue
        markering = "x" if s.get("done") else " "
        indent = "  " * djup
        rader.append(f"{indent}[{markering}] {s.get('title', '')}".rstrip())
        rader.extend(_subtask_lines(s.get("children") or [], djup + 1))
    return rader


def _description(task: Dict[str, Any], inkl_datum: bool = True) -> str:
    """Bygg DESCRIPTION: prioritet, taggar, delmoment och mailinfo."""
    rader: List[str] = []

    prio = _PRIORITY_LABEL.get(str(task.get("priority") or "none").lower())
    tags = [str(t).strip() for t in (task.get("tags") or []) if str(t).strip()]
    topp: List[str] = []
    if prio:
        topp.append(f"Prioritet: {prio}")
    if tags:
        topp.append("Taggar: " + ", ".join(tags))
    if topp:
        rader.extend(topp)
        rader.append("")

    if task.get("done"):
        rader.append("✅ Klar i TaskBord")
        rader.append("")

    subs = _subtask_lines(task.get("subtasks") or [])
    if subs:
        rader.append("Delmoment:")
        rader.extend(subs)
        rader.append("")

    # Mailinfo (finns när uppgiften kommit från Thunderbird/inkorgen)
    amne = str(task.get("email_subject") or "").strip()
    avsandare = str(task.get("email_from") or "").strip()
    if amne or avsandare:
        rader.append("📧 Från mail:")
        if amne:
            rader.append(f"  Ämne: {amne}")
        if avsandare:
            rader.append(f"  Från: {avsandare}")
        rader.append("")

    text = str(task.get("note") or task.get("email_body") or "").strip()
    if text:
        if len(text) > 1200:  # håll kalenderposten läsbar
            text = text[:1200].rstrip() + "…"
        rader.append(text)
        rader.append("")

    if inkl_datum:
        rader.append("Skapad i TaskBord")
    return "\n".join(rader).strip()


def build_description(task: Dict[str, Any], inkl_datum: bool = True) -> str:
    """
    Publik wrapper runt _description (delas med Google Calendar-exporten,
    så att .ics-filen och Google-händelsen får exakt samma text).
    """
    return _description(task, inkl_datum=inkl_datum)


# --------------------------------------------------------------------------
# iCalendar
# --------------------------------------------------------------------------
def task_to_vevent(
    task: Dict[str, Any],
    dtstamp: Optional[_datetime] = None,
) -> List[str]:
    """
    En uppgift → raderna i en VEVENT (heldagshändelse; flera dagar om både start-
    och förfallodatum finns).

    Returnerar [] om uppgiften saknar titel eller både startdatum och förfallodatum.
    """
    titel = str(task.get("title") or "").strip()
    dagar = event_dates(task)
    if not titel or dagar is None:
        return []
    d, sista = dagar

    stamp = dtstamp or _datetime.utcnow()
    task_id = str(task.get("id") or "").strip() or titel
    slut = sista + _timedelta(days=1)  # DTEND är exklusivt i RFC 5545

    rader: List[str] = [
        "BEGIN:VEVENT",
        f"UID:taskbord-{_escape_text(task_id)}@taskbord.local",
        f"DTSTAMP:{_utc_stamp(stamp)}",
        f"DTSTART;VALUE=DATE:{_date_stamp(d)}",
        f"DTEND;VALUE=DATE:{_date_stamp(slut)}",
        f"SUMMARY:{_escape_text(titel)}",
    ]

    beskrivning = _description(task)
    if beskrivning:
        rader.append(f"DESCRIPTION:{_escape_text(beskrivning)}")

    tags = [str(t).strip() for t in (task.get("tags") or []) if str(t).strip()]
    if tags:
        rader.append("CATEGORIES:" + ",".join(_escape_text(t) for t in tags))

    prio = _PRIORITY_TO_ICAL.get(str(task.get("priority") or "").lower())
    if prio is not None:
        rader.append(f"PRIORITY:{prio}")

    if task.get("done"):
        rader.append("STATUS:COMPLETED")
        klart = str(task.get("completed") or "").strip()
        if klart:
            try:
                rader.append("COMPLETED:" + _utc_stamp(_datetime.fromisoformat(klart)))
            except Exception:
                pass
    else:
        rader.append("STATUS:CONFIRMED")

    rader.append("TRANSP:TRANSPARENT")  # bokar inte upp tiden i kalendern
    rader.append("END:VEVENT")
    return rader


def build_ics(
    tasks: List[Dict[str, Any]],
    calendar_name: str = CALENDAR_NAME_DEFAULT,
    now: Optional[_datetime] = None,
) -> str:
    """
    Bygg en komplett .ics-fil (CRLF-radbrytning enligt RFC 5545).

    Uppgifter utan titel/förfallodatum hoppas över automatiskt.
    """
    stamp = now or _datetime.utcnow()
    rader: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(calendar_name)}",
    ]
    for t in tasks or []:
        if isinstance(t, dict):
            rader.extend(task_to_vevent(t, dtstamp=stamp))
    rader.append("END:VCALENDAR")

    vikta: List[str] = []
    for rad in rader:
        vikta.extend(_fold_line(rad))
    return "\r\n".join(vikta) + "\r\n"


def write_ics(
    tasks: List[Dict[str, Any]],
    path: Any,
    calendar_name: str = CALENDAR_NAME_DEFAULT,
    now: Optional[_datetime] = None,
) -> int:
    """
    Skriv .ics-filen och returnera antalet händelser som blev med.

    Skapar mappen om den inte finns. Filen skrivs i UTF-8 **utan** BOM
    (BOM förvirrar Google Calendar och Outlook).
    """
    valda = [t for t in (tasks or []) if isinstance(t, dict) and task_to_vevent(t)]
    mål = Path(str(path))
    if mål.parent and not mål.parent.exists():
        mål.parent.mkdir(parents=True, exist_ok=True)
    mål.write_text(build_ics(tasks, calendar_name=calendar_name, now=now), encoding="utf-8")
    return len(valda)


# --------------------------------------------------------------------------
# Google Calendar — direktlänk (ett klick, inget konto i appen)
# --------------------------------------------------------------------------
def google_calendar_url(task: Dict[str, Any]) -> Optional[str]:
    """
    Länk som öppnar Google Calendar med uppgiften förifylld.

    Google Calendar API behövs inte: det här är Googles egen
    "skapa händelse"-mall (action=TEMPLATE). Allt skickas som
    query-parametrar och ingenting sparas förrän användaren klickar
    *Spara* i Google Calendar.

    Returnerar None om uppgiften saknar titel eller både startdatum och förfallodatum.
    """
    titel = str(task.get("title") or "").strip()
    dagar = event_dates(task)
    if not titel or dagar is None:
        return None
    d, sista = dagar

    params: Dict[str, str] = {
        "action": "TEMPLATE",
        "text": titel,
        # Heldagshändelse: Google tolkar samma datum/intervall som .ics
        "dates": f"{_date_stamp(d)}/{_date_stamp(sista + _timedelta(days=1))}",
    }
    beskrivning = _description(task, inkl_datum=False)
    if beskrivning:
        params["details"] = beskrivning
    return GOOGLE_TEMPLATE_URL + "?" + urlencode(params, safe="/", quote_via=quote)
