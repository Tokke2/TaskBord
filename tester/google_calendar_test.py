#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
google_calendar_test.py — tester för core/google_calendar.py (lokal OAuth).

Kör:  python tester/google_calendar_test.py

Vad testet gör (och inte gör):
  ✓ Använder de RIKTIGA Google-biblioteken (google-auth-oauthlib,
    google-api-python-client) för att bygga OAuth-flödet och för att
    läsa/skriva token-filen — inte bara påhittade objekt.
  ✓ Fejkar själva nätverket: "service"-objektet är en attrapp som svarar
    som Google Calendar-API:t gör (inkl. riktiga HttpError-objekt).
  ✗ Öppnar ingen webbläsare och kontaktar aldrig Google. Det går inte
    från en testmiljö — den riktiga inloggningen måste göras av
    användaren i appen (se GOOGLE_CALENDAR.md).

Körs utan Qt. Kräver google-paketen:
    pip install google-api-python-client google-auth-oauthlib
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import google_calendar as gc  # noqa: E402

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
# Attrapper som härmar Google Calendar-API:t
# --------------------------------------------------------------------------
def _http_error(status: int, meddelande: str = "fel") -> Exception:
    """Bygg ett RIKTIGT googleapiclient-fel (samma typ som i produktion)."""
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    return HttpError(
        Response({"status": int(status)}),
        json.dumps({"error": {"code": status, "message": meddelande}}).encode(),
    )


class _FakeRequest:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, **kwargs):
        return self._fn()


class FakeService:
    """Attrapp för googleapiclient-tjänsten (räknar anrop, kan fela)."""

    def __init__(self, fail_first: int = 0, list_items=None, permanent_error: int = 0):
        self.calls = []                 # ("insert"/"patch"/..., kwargs)
        self.events_db = {}             # event_id → body
        self.last_body = None
        self._next_id = 0
        self._fail_first = fail_first   # antal inledande tillfälliga fel (503)
        self._permanent = permanent_error  # t.ex. 400 → aldrig retry
        self._list_items = list_items or []
        self.deleted = set()
        self.patch_error = 0            # om satt: patch kastar detta fel

    def _bomb(self):
        if self._permanent:
            raise _http_error(self._permanent, "permanent fel")

    # -- events ------------------------------------------------------------
    def events(self):
        return self

    def calendars(self):
        return self

    def calendarList(self):
        return self

    def _maybe_fail(self, namn):
        if self._fail_first > 0:
            self._fail_first -= 1
            raise _http_error(503, "backend error")

    def insert(self, calendarId, body):
        self.calls.append(("insert", {"calendarId": calendarId, "body": body}))
        self.last_body = body

        def _run():
            self._bomb()
            self._maybe_fail("insert")
            self._next_id += 1
            eid = f"ev{self._next_id}"
            self.events_db[eid] = dict(body)
            return {"id": eid, "htmlLink": f"https://calendar.google.com/{eid}"}
        return _FakeRequest(_run)

    def patch(self, calendarId, eventId, body):
        self.calls.append(("patch", {"calendarId": calendarId, "eventId": eventId, "body": body}))

        def _run():
            self._bomb()
            if self.patch_error:
                raise _http_error(self.patch_error, "patch-fel")
            self._maybe_fail("patch")
            if eventId in self.deleted:
                raise _http_error(404, "Not Found")
            if eventId not in self.events_db:
                raise _http_error(404, "Not Found")
            self.events_db[eventId].update(body)
            return {"id": eventId, "htmlLink": f"https://calendar.google.com/{eventId}"}
        return _FakeRequest(_run)

    def update(self, calendarId, eventId, body):
        self.calls.append(("update", {"eventId": eventId}))
        return _FakeRequest(lambda: {"id": eventId})

    def delete(self, calendarId, eventId):
        self.calls.append(("delete", {"eventId": eventId}))

        def _run():
            if eventId in self.deleted:
                raise _http_error(410, "Gone")
            self.deleted.add(eventId)
            # Google returnerar inte borttagna händelser i en sökning —
            # därför tas den bort ur "databasen" här också (annars blir
            # återhämtningen via märket orealistiskt lätt att testa).
            self.events_db.pop(eventId, None)
            return ""
        return _FakeRequest(_run)

    def get(self, calendarId, eventId=None):
        self.calls.append(("get", {"calendarId": calendarId, "eventId": eventId}))

        def _run():
            if calendarId == "primary" and eventId is None:
                return {"id": "rickard@example.com", "summary": "Rickard",
                        "timeZone": "Europe/Stockholm"}
            if eventId in self.deleted:
                raise _http_error(404, "Not Found")
            return {"id": eventId, "summary": "händelse"}
        return _FakeRequest(_run)

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))

        def _run():
            if kwargs.get("privateExtendedProperty"):
                # sökning på uppgifts-id
                for eid, body in self.events_db.items():
                    if eid in self.deleted:
                        continue
                    märke = ((body.get("extendedProperties") or {}).get("private") or {}) \
                        .get(gc.EVENT_TAG_KEY)
                    if f"{gc.EVENT_TAG_KEY}={märke}" == kwargs["privateExtendedProperty"]:
                        return {"items": [{"id": eid, **body}]}
                return {"items": []}
            if kwargs.get("orderBy") == "startTime":  # list_upcoming_events
                return {"items": self._list_items}
            # calendarList().list()
            return {"items": [
                {"id": "rickard@example.com", "summary": "Rickard", "primary": True,
                 "timeZone": "Europe/Stockholm", "accessRole": "owner"},
                {"id": "arbete@group.calendar.google.com", "summary": "Arbete",
                 "timeZone": "Europe/Stockholm", "accessRole": "writer"},
            ]}
        return _FakeRequest(_run)


def fake_credentials(**kwargs):
    """
    Bygg ett RIKTIGT Credentials-objekt (som efter en lyckad inloggning).

    OBS: `expiry` sätts till en timme framåt — precis som Google gör.
    (Utan expiry räknar google-auth-token som utgången, vilket är
    anledningen till att appen alltid sparar Googles eget expiry-värde.)
    """
    from google.oauth2.credentials import Credentials
    data = dict(
        token="ya29.FAKE_ACCESS_TOKEN",
        refresh_token="1//FAKE_REFRESH_TOKEN",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="1234-fake.apps.googleusercontent.com",
        client_secret="FAKE_CLIENT_SECRET",
        scopes=list(gc.SCOPES),
        # google-auth jämför mot en "naiv" UTC-tid internt
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
    )
    data.update(kwargs)
    if data.get("expiry") is not None and getattr(data["expiry"], "tzinfo", None):
        data["expiry"] = data["expiry"].astimezone(timezone.utc).replace(tzinfo=None)
    return Credentials(**data)


def skriv_credentials_file(dir_: Path, client_id: str = "1234-fake.apps.googleusercontent.com") -> Path:
    """Skriv en credentials.json precis som Google laddar ner den."""
    p = gc.credentials_path(dir_)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "installed": {
            "client_id": client_id,
            "project_id": "taskbord-test",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "FAKE_CLIENT_SECRET",
            "redirect_uris": ["http://localhost"],
        }
    }, indent=2), encoding="utf-8")
    return p


UPPGIFT = {
    "id": "k3f9a2x1",
    "title": "Faktura 2026-10 måste betalas",
    "due_date": "2026-10-13",
    "priority": "high",
    "tags": ["jobb"],
    "done": False,
    "subtasks": [{"title": "Hämta underlag", "done": True}],
    "email_from": "Leverantör AB <faktura@lev.example>",
}

print("=" * 66)
print("TESTER: core/google_calendar.py (lokal OAuth → Google Calendar)")
print("=" * 66)

# --- 0. Paketen ------------------------------------------------------------
print("\n0. Beroenden")
check("google-paketen finns", gc.is_google_library_available(),
      f"saknas: {gc.missing_packages()}")
check("inga saknade paket", gc.missing_packages() == [], str(gc.missing_packages()))

try:
    import google_auth_oauthlib.flow  # noqa: F401
    import googleapiclient.discovery  # noqa: F401
except ImportError:
    print("\n✗ Installera först:  pip install google-api-python-client google-auth-oauthlib")
    sys.exit(2)

with tempfile.TemporaryDirectory() as tmpdir:
    D = Path(tmpdir)

    # --- 1. Sökvägar & status ---------------------------------------------
    print("\n1. Sökvägar och status")
    check("google-mappen ligger under datamappen",
          gc.google_dir(D) == D / "google", str(gc.google_dir(D)))
    check("token hamnar i google/token.json",
          gc.token_path(D).name == "token.json")
    check("credentials-filen hittas inte innan den finns",
          gc.discover_credentials_file(D) is None)
    st = gc.get_status(D)
    check("status = not_configured utan credentials.json",
          st["state"] == gc.ConnectionStatus.NOT_CONFIGURED, st["state"])
    check("status-texten nämner credentials.json", "credentials.json" in st["message"])

    # --- 2. credentials.json hittas (alla platser) -------------------------
    print("\n2. Hitta credentials.json")
    cfile = skriv_credentials_file(D)
    check("hittas på standardplatsen", gc.discover_credentials_file(D) == cfile)
    check("status går vidare till 'inte ansluten'",
          gc.get_status(D)["state"] == gc.ConnectionStatus.DISCONNECTED)
    alt = D / "client_secret_999.apps.googleusercontent.com.json"
    alt.write_text(cfile.read_text(encoding="utf-8"), encoding="utf-8")
    (D / "google" / "credentials.json").unlink()
    check("hittas även som client_secret*.json",
          gc.discover_credentials_file(D) == alt)
    alt.unlink()
    skriv_credentials_file(D)
    with mock.patch.dict("os.environ", {gc.ENV_CREDENTIALS: str(cfile)}):
        check("miljövariabeln TASKBORD_GOOGLE_CREDENTIALS respekteras",
              gc.discover_credentials_file(Path("/nonexistent")) == cfile)

    # --- 3. OAuth-flödet (riktiga biblioteket, inget nätverk) --------------
    print("\n3. OAuth-flödet (byggt med de riktiga Google-biblioteken)")
    fl = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        str(cfile), list(gc.SCOPES)
    )
    url, _state = fl.authorization_url(access_type="offline", prompt="consent")
    check("inloggnings-URL byggs från filen", url.startswith("https://accounts.google.com/o/oauth2/auth?"))
    check("URL:en innehåller vår klient", "1234-fake.apps.googleusercontent.com" in url)
    check("URL:en begär calendar.events", "calendar.events" in url)
    check("URL:en begär calendar.readonly", "calendar.readonly" in url)
    check("access_type=offline (ger refresh-token)", "access_type=offline" in url)
    # redirect_uri sätts av run_local_server precis innan URL:en byggs.
    # Här härmar vi det steget och kontrollerar att loopback hamnar i URL:en.
    fl.redirect_uri = "http://127.0.0.1:41234/"
    url_loopback, _ = fl.authorization_url(access_type="offline", prompt="consent")
    check(
        "redirect_uri blir loopback på 127.0.0.1 (krävs av Google för datorappar)",
        "redirect_uri=http%3A%2F%2F127.0.0.1%3A41234%2F" in url_loopback,
        url_loopback[:120],
    )
    check("ingen hemlighet läcker till URL:en", "FAKE_CLIENT_SECRET" not in url_loopback)

    # --- 4. Hela connect-flödet (mockat: ingen webbläsare, inget nätverk) --
    print("\n4. connect-flödet (run_local_server ersatt av attrapp)")
    fake_svc = FakeService()
    with mock.patch.object(gc, "build_calendar_service", return_value=fake_svc):
        with mock.patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
            return_value=fake_credentials(),
        ) as m:
            svar = gc.authenticate_google_calendar(D, open_browser=False)
    check("connect returnerar ok", svar.get("ok") is True)
    check("e-post hämtades från kalendern", svar.get("email") == "rickard@example.com",
          str(svar.get("email")))
    check("tidszon sparades", svar.get("timezone") == "Europe/Stockholm")
    kwargs = m.call_args.kwargs if m.call_args else {}
    check("access_type=offline skickas med", kwargs.get("access_type") == "offline")
    check("prompt=consent skickas med (alltid refresh-token)", kwargs.get("prompt") == "consent")
    check("loopback-servern binds till 127.0.0.1", kwargs.get("host") == "127.0.0.1",
          str(kwargs.get("host")))
    check("port 0 → operativsystemet väljer en ledig port", kwargs.get("port") == 0,
          str(kwargs.get("port")))
    check("användaren får ett begripligt meddelande i webbläsaren",
          "TaskBord" in str(kwargs.get("success_message", "")))

    # --- 5. Token-filen ----------------------------------------------------
    print("\n5. Token på disk (lokalt, låsta rättigheter)")
    tf = gc.token_path(D)
    check("token.json skapades", tf.is_file())
    data = json.loads(tf.read_text(encoding="utf-8"))
    check("refresh-token finns med", bool(data.get("refresh_token")))
    check("klienthemligheten finns med (behövs för förnyelse)", bool(data.get("client_secret")))
    check("behörigheterna är sparade", data.get("_taskbord_scopes") == list(gc.SCOPES))
    check("sparningstidpunkt finns", bool(data.get("_taskbord_saved_at")))
    if sys.platform != "win32":
        mode = tf.stat().st_mode & 0o777
        check("filrättigheter 0600 (bara du kan läsa)", mode == 0o600, oct(mode))
    check("status = ansluten", gc.get_status(D)["state"] == gc.ConnectionStatus.CONNECTED)
    check("e-post syns i statusen", gc.get_status(D)["email"] == "rickard@example.com")
    check("kontoinfo sparades", gc.load_account_info(D) is not None)
    check("händelsemappningen ligger bredvid", gc.event_map_path(D).name == "event_map.json")

    # --- 6. Inläsning av token (riktiga Credentials) -----------------------
    print("\n6. Läsa token (riktiga Credentials-objektet)")
    creds = gc.load_credentials(D)
    check("token kunde läsas", creds is not None)
    check("har refresh-token", bool(getattr(creds, "refresh_token", "")))
    check("klient-id bevarat", getattr(creds, "client_id", "") == "1234-fake.apps.googleusercontent.com")
    check("giltig utan förnyelse", bool(getattr(creds, "valid", False)))
    # utgången token utan refresh-token → None (ingen krasch, ingen retry)
    gc.save_token(fake_credentials(
        refresh_token=None, expiry=datetime.now(timezone.utc) - timedelta(hours=2)
    ), D)
    check("utgången token utan refresh-token → None", gc.load_credentials(D) is None)
    gc.save_token(fake_credentials(), D)
    check("giltig token läses igen", gc.load_credentials(D) is not None)
    # Dokumenterat beteende: google-auth räknar token UTAN expiry som giltig
    # tills Google säger annat; appen sparar alltid Googles eget expiry-värde.
    from google.oauth2.credentials import Credentials as _C
    utan_expiry = _C(
        token="ya29.X", refresh_token="1//Y", client_id="c", client_secret="s",
        token_uri="https://oauth2.googleapis.com/token", scopes=list(gc.SCOPES),
    )
    gc.save_token(utan_expiry, D)
    sparad = json.loads(gc.token_path(D).read_text(encoding="utf-8"))
    check("expiry saknas i filen när Google inte gett något",
          not sparad.get("expiry"), str(sparad.get("expiry")))
    try:
        gc.load_credentials(D)
        check("load_credentials hanterar token utan expiry utan krasch", True)
    except Exception as _e:  # noqa: BLE001
        check("load_credentials hanterar token utan expiry utan krasch", False, repr(_e))

    # --- 7. Hemligheter i loggen ------------------------------------------
    print("\n7. Läckagekontroll (token får aldrig hamna i loggen)")
    gc.save_token(fake_credentials(), D)
    loggsamlare = []

    class _Samlare(logging.Handler):
        def emit(self, record):
            loggsamlare.append(record.getMessage())

    log = logging.getLogger("GoogleCalendar")
    h = _Samlare()
    log.addHandler(h)
    log.setLevel(logging.DEBUG)
    try:
        gc.save_token(fake_credentials(), D)
        gc.load_credentials(D)
        gc.get_status(D)
        gc.push_task(FakeService(), "primary", UPPGIFT, gc.load_event_map(D))
    finally:
        log.removeHandler(h)
    text = "\n".join(loggsamlare)
    check("access-token syns inte i loggen", "ya29.FAKE_ACCESS_TOKEN" not in text)
    check("refresh-token syns inte i loggen", "1//FAKE_REFRESH_TOKEN" not in text)
    check("klienthemligheten syns inte i loggen", "FAKE_CLIENT_SECRET" not in text)
    check("något loggades alls (kontrollen är verklig)", len(loggsamlare) > 0)

    # --- 8. Händelsens innehåll -------------------------------------------
    print("\n8. Händelsen som skickas till Google")
    body = gc.build_event_body(UPPGIFT, color_by_priority=True)
    check("sammanfattning = titeln", body["summary"] == UPPGIFT["title"])
    check("heldagshändelse (date, inte dateTime)", "date" in body["start"] and "dateTime" not in body["start"])
    check("start = förfallodatumet", body["start"]["date"] == "2026-10-13")
    check("slut = dagen efter (exklusivt)", body["end"]["date"] == "2026-10-14")
    check("märkt med uppgiftens id", body["extendedProperties"]["private"][gc.EVENT_TAG_KEY] == "k3f9a2x1")
    check("källa = taskbord", body["extendedProperties"]["private"]["taskbord_source"] == "taskbord")
    check("hög prioritet → röd färg (11)", body.get("colorId") == "11")
    check("beskrivningen har delmomenten", "[x] Hämta underlag" in body["description"])
    check("beskrivningen har mailinfo", "Leverantör AB" in body["description"])
    check("påminnelse använder Googles standard", body["reminders"] == {"useDefault": True})
    check("bokar inte upp tiden (transparent)", body.get("transparency") == "transparent")
    ok, feltext = gc.validate_event_data(body)
    check("händelsen validerar", ok, feltext)
    check("utan prioritet → ingen färg", "colorId" not in gc.build_event_body({**UPPGIFT, "priority": "none"}))
    check("färgkodning avstängd → ingen färg",
          "colorId" not in gc.build_event_body(UPPGIFT, color_by_priority=False))
    try:
        gc.build_event_body({"title": "Utan datum", "due_date": None})
        check("kastar fel utan förfallodatum", False)
    except gc.GoogleCalendarError as e:
        check("kastar begripligt fel utan förfallodatum", "förfallodatum" in e.user_message)

    # --- 9. Skicka (skapa → uppdatera → dubblettskydd) --------------------
    print("\n9. Skicka uppgifter (dubblettskydd och uppdatering)")
    svc = FakeService()
    em = gc.load_event_map(D)
    r1 = gc.push_task(svc, "primary", UPPGIFT, em)
    check("första sändningen skapar händelse", r1["ok"] and r1["action"] == "skapad", str(r1))
    check("händelse-id sparades lokalt", em.get("k3f9a2x1") == r1["event_id"])
    antal_insert1 = sum(1 for c in svc.calls if c[0] == "insert")
    r2 = gc.push_task(svc, "primary", UPPGIFT, em)
    check("andra sändningen uppdaterar (ingen dubblett)", r2["action"] == "uppdaterad", str(r2))
    check("fortfarande bara en insert", sum(1 for c in svc.calls if c[0] == "insert") == antal_insert1)
    check("samma händelse-id", r2["event_id"] == r1["event_id"])

    # händelsen borttagen i Google → skapas på nytt
    svc.deleted.add(r1["event_id"])
    r3 = gc.push_task(svc, "primary", UPPGIFT, em)
    check("borttagen händelse skapas på nytt", r3["ok"] and r3["action"] == "skapad", str(r3))
    check("nytt id efter återskapande", r3["event_id"] != r1["event_id"])

    # annat fel än "borttagen" (t.ex. 403) → ska INTE skapa en dubblett
    antal_insert_fore = sum(1 for c in svc.calls if c[0] == "insert")
    svc.patch_error = 403
    r3b = gc.push_task(svc, "primary", UPPGIFT, em)
    svc.patch_error = 0
    check("403 vid uppdatering ger fel (ingen dubblett)",
          not r3b["ok"] and sum(1 for c in svc.calls if c[0] == "insert") == antal_insert_fore,
          str(r3b))
    check("mappningen finns kvar efter ett övergående fel",
          em.get("k3f9a2x1") == r3["event_id"])

    # återställning via märket (t.ex. efter ominstallation)
    em2 = gc.EventMap(D / "google" / "tom_mappning.json")
    r4 = gc.push_task(svc, "primary", UPPGIFT, em2)
    check("hittar händelsen via märket när mappningen saknas",
          r4["action"] == "uppdaterad", str(r4))
    check("mappningen lagades automatiskt", em2.get("k3f9a2x1") == r3["event_id"])

    # uppgift utan datum hoppas över
    r5 = gc.push_task(svc, "primary", {"id": "x", "title": "Ingen datum"}, em)
    check("uppgift utan datum hoppas över", r5["action"] == "hoppad" and not r5["ok"], str(r5))
    check("hoppad uppgift får förklaring", "förfallodatum" in r5["message"])

    # --- 10. Flera uppgifter + felhantering -------------------------------
    print("\n10. Flera uppgifter och felhantering")
    uppgifter = [
        {"id": "a", "title": "A", "due_date": "2026-10-14"},
        {"id": "b", "title": "B", "due_date": "2026-10-15"},
        {"id": "c", "title": "C", "due_date": None},          # hoppas över
        {"id": "d", "title": "  ", "due_date": "2026-10-16"},  # tom titel → hoppas över
    ]
    res = gc.push_tasks(FakeService(), "primary", uppgifter, gc.EventMap(D / "google" / "m2.json"))
    check("2 skapade", res["skapade"] == 2, str(res["skapade"]))
    check("2 hoppade (utan datum / utan titel)", res["hoppade"] == 2, str(res["hoppade"]))
    check("inga misslyckade när inget API-fel inträffar", res["misslyckade"] == 0, str(res["misslyckade"]))
    check("resultat per uppgift", len(res["results"]) == 4)
    check("uppgiften utan titel fick förklaring",
          "titel" in res["results"][3]["message"].lower(), str(res["results"][3]))
    # RIKTIGT API-fel: 400 → räknas som misslyckad och stoppar inte resten
    res_fel = gc.push_tasks(FakeService(permanent_error=400), "primary",
                            [{"id": "z", "title": "Z", "due_date": "2026-10-17"}],
                            gc.EventMap(D / "google" / "m_fel.json"))
    check("API-fel räknas som misslyckat", res_fel["misslyckade"] == 1, str(res_fel["misslyckade"]))
    check("felräkningen syns i sammanfattningen", "misslyckades" in gc.summarize(res_fel))
    check("felmeddelandet är begripligt",
          "Google" in res_fel["results"][0]["message"], str(res_fel["results"][0]))
    check("sammanfattningen är läsbar", "nya händelser" in gc.summarize(res))
    check("en trasig uppgift stoppar inte de andra",
          res["results"][0]["ok"] and res["results"][1]["ok"])

    # --- 10b. Användaren väljer själv vad som skickas ---------------------
    print("\n10b. Uppgiftsväljaren (användaren väljer)")
    em_v = gc.EventMap(D / "google" / "m_val.json")
    em_v.set("a", "ev_gammal")
    rader_v = gc.describe_tasks_for_picker(uppgifter, em_v)
    check("tomma titlar syns inte i väljaren", [r["id"] for r in rader_v] == ["a", "b", "c"],
          str([r["id"] for r in rader_v]))
    check("uppgift utan datum kan inte väljas",
          [r["sendable"] for r in rader_v] == [True, True, False])
    check("förklaring när datum saknas", "förfallodatum" in rader_v[2]["reason"])
    check("redan skickad uppgift märks", rader_v[0]["sent"] and not rader_v[1]["sent"])
    valda_v = gc.select_tasks_by_ids(uppgifter, ["b"])
    svc_v = FakeService()
    res_v = gc.push_tasks(svc_v, "primary", valda_v, em_v)
    check("bara den valda uppgiften väljs ut", [t["id"] for t in valda_v] == ["b"])
    check("bara den valda skickas till Google",
          sum(1 for c in svc_v.calls if c[0] == "insert") == 1 and res_v["skapade"] == 1)
    check("inget valt → inget skickas",
          gc.select_tasks_by_ids(uppgifter, []) == [])

    # --- 10c. Klara uppgifter blir grå/överstrukna händelser ---------------
    print("\n10c. Klar uppgift → grå händelse")
    klar = {**UPPGIFT, "done": True, "priority": "high"}
    b_grey = gc.build_event_body(klar)
    check("klar → grå färg (Grafit) slår prioritetsfärgen", b_grey.get("colorId") == "8")
    check("klar → bock framför titeln", b_grey["summary"] == "✅ " + UPPGIFT["title"])
    check("klar → fortfarande transparent", b_grey.get("transparency") == "transparent")
    b_strike = gc.build_event_body(klar, done_style="strike")
    check("strike → överstruken titel", "\u0336" in b_strike["summary"]
          and b_strike["summary"].replace("\u0336", "") == "✅ " + UPPGIFT["title"])
    check("strike → mellanslag lämnas orörda", " \u0336" not in b_strike["summary"])
    b_off = gc.build_event_body(klar, done_style="off")
    check("off → titel och prioritetsfärg som vanligt",
          b_off["summary"] == UPPGIFT["title"] and b_off.get("colorId") == "11")
    check("okänd stil faller tillbaka på standard",
          gc.build_event_body(klar, done_style="strunt")["colorId"] == "8")
    check("aktiv uppgift påverkas inte", gc.build_event_body(UPPGIFT)["summary"] == UPPGIFT["title"])
    svc_k = FakeService()
    em_k = gc.EventMap(D / "google" / "m_klar.json")
    gc.push_task(svc_k, "primary", UPPGIFT, em_k)
    gc.push_task(svc_k, "primary", klar, em_k)
    ev = svc_k.events_db[em_k.get("k3f9a2x1")]
    check("klar uppgift uppdaterar samma händelse", sum(1 for c in svc_k.calls if c[0] == "insert") == 1)
    check("händelsen blev grå och fick bock", ev.get("colorId") == "8" and ev["summary"].startswith("✅ "))
    gc.push_task(svc_k, "primary", {**UPPGIFT, "priority": "none"}, em_k)
    ev = svc_k.events_db[em_k.get("k3f9a2x1")]
    check("ångrad klar-markering återställer titeln", ev["summary"] == UPPGIFT["title"])
    check("…och tar bort den grå färgen (null i PATCH)", ev.get("colorId") is None)

    # --- 10d. Sändningshistorik ---------------------------------------------
    print("\n10d. Sändningshistorik")
    hist = gc.load_history(D)
    check("historiken börjar tom", hist.all() == [])
    svc_h = FakeService()
    em_h = gc.EventMap(D / "google" / "m_hist.json")
    gc.push_task(svc_h, "primary", UPPGIFT, em_h, history=hist)
    gc.push_task(svc_h, "primary", UPPGIFT, em_h, history=hist)
    gc.push_task(svc_h, "primary", {"id": "zz", "title": "Utan datum"}, em_h, history=hist)
    gc.push_tasks(FakeService(permanent_error=400), "primary",
                  [{"id": "e1", "title": "Fel", "due_date": "2026-10-20"}], em_h, history=hist)
    alla_h = gc.load_history(D).all()
    check("alla försök loggas (även hoppade och misslyckade)", len(alla_h) == 4, str(len(alla_h)))
    check("nyaste först", alla_h[0]["task_id"] == "e1")
    check("skapad + uppdaterad syns för uppgiften",
          [e["action"] for e in gc.load_history(D).for_task("k3f9a2x1")] == ["uppdaterad", "skapad"])
    check("historiken sparas på disk (överlever omstart)", gc.history_path(D).is_file())
    check("posten har titel, förfallodatum, kalender och tid",
          all(alla_h[-1].get(k) for k in ("title", "due", "calendar_id", "ts")))
    check("länk till händelsen sparas", alla_h[-1]["html_link"].startswith("https://calendar.google.com/"))
    check("öppna-länken är Googles egen när den finns",
          gc.calendar_open_url(alla_h[-1]) == alla_h[-1]["html_link"])
    check("saknas länk → dagsvyn för förfallodatumet",
          gc.calendar_open_url({"due": "2026-10-13"}) == "https://calendar.google.com/calendar/r/day/2026/10/13")
    check("saknas allt → Google Calendar", gc.calendar_open_url({}) == gc.GOOGLE_CALENDAR_URL)
    check("resultattext för skapad", gc.history_result_text(alla_h[-1]) == "✅ Skapad")
    check("resultattext för hoppad", "Hoppades över" in gc.history_result_text(alla_h[1]))
    check("resultattext för fel", gc.history_result_text(alla_h[0]).startswith("✗"))
    check("tidstext går att läsa", len(gc.history_time_text(alla_h[0])) == 16)
    check("historiken innehåller inga hemligheter",
          "FAKE" not in gc.history_path(D).read_text(encoding="utf-8"))
    liten = gc.SendHistory(D / "google" / "h_liten.json", max_entries=10)
    for i in range(15):
        liten.add({"task_id": str(i), "title": f"t{i}", "ok": True, "action": "skapad"})
    check("äldsta posterna rensas vid maxgränsen",
          len(liten.all()) == 10 and liten.all()[0]["task_id"] == "14")
    check("rensa tömmer historiken", gc.load_history(D).clear() == 4 and gc.load_history(D).all() == [])

    # --- 10e. Guidad installation + kontroll av credentials.json ------------
    print("\n10e. Guidad första koppling (kontroll av credentials.json)")
    V = Path(tmpdir) / "guide"
    V.mkdir()
    check("saknad fil avvisas", not gc.validate_credentials_file(V / "finns_inte.json")["ok"])
    tom = V / "tom.json"; tom.write_text("", encoding="utf-8")
    check("tom fil avvisas", "tom" in " ".join(gc.validate_credentials_file(tom)["problems"]))
    trasig = V / "trasig.json"; trasig.write_text("{inte json", encoding="utf-8")
    check("trasig JSON avvisas", "JSON" in " ".join(gc.validate_credentials_file(trasig)["problems"]))
    web = V / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "x.apps.googleusercontent.com",
                                       "client_secret": "S", "auth_uri": "a", "token_uri": "t"}}),
                   encoding="utf-8")
    kw = gc.validate_credentials_file(web)
    check("Webbapp-klient avvisas med tydlig text",
          not kw["ok"] and kw["client_type"] == "web" and "Datorapp" in " ".join(kw["problems"]))
    sa = V / "sa.json"; sa.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    check("tjänstekonto-nyckel avvisas", "tjänstekonto" in " ".join(gc.validate_credentials_file(sa)["problems"]))
    ofull = V / "ofull.json"
    ofull.write_text(json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com"}}), encoding="utf-8")
    check("saknade fält pekas ut",
          "client_secret" in " ".join(gc.validate_credentials_file(ofull)["problems"]))
    ok_fil = skriv_credentials_file(V / "ok_data")
    kok = gc.validate_credentials_file(ok_fil)
    check("giltig Datorapp-fil godkänns", kok["ok"] and kok["client_type"] == "installed", str(kok))
    check("klienthemligheten returneras aldrig av kontrollen", "FAKE_CLIENT_SECRET" not in json.dumps(kok))
    # inloggningen stoppas innan webbläsaren om filen är trasig
    (V / "google").mkdir(exist_ok=True)
    (V / "google" / "credentials.json").write_text(web.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        with mock.patch("google_auth_oauthlib.flow.InstalledAppFlow.run_local_server") as rls:
            gc.authenticate_google_calendar(V, open_browser=False)
        check("fel klienttyp stoppar inloggningen", False)
    except gc.GoogleCalendarError as e:
        check("fel klienttyp stoppar inloggningen före webbläsaren",
              "Datorapp" in e.user_message and not rls.called)
        check("felet hänvisar till guiden i appen", "Guidad installation" in e.user_message)
    # guiden
    st_v = gc.setup_steps(V)
    check("guiden har 7 steg i rätt ordning",
          [s_["key"] for s_ in st_v] == ["library", "project", "api", "consent", "client", "file", "login"])
    check("filsteget är rött för trasig fil", st_v[5]["done"] is False and "Datorapp" in st_v[5]["text"])
    check("engångssteg hos Google har done=None (användaren bekräftar)",
          all(st_v[i]["done"] is None for i in (1, 2, 3, 4)))
    check("stegen med länkar pekar på Google Cloud",
          all(st_v[i]["url"].startswith("https://console.cloud.google.com/") for i in (1, 2, 3, 4)))
    check("inloggningssteget är inte klart utan token", st_v[6]["done"] is False)
    # installera från en nedladdad fil
    nerladdad = V / "client_secret_123.apps.googleusercontent.com.json"
    nerladdad.write_text(ok_fil.read_text(encoding="utf-8"), encoding="utf-8")
    bad = gc.install_credentials_file(web, V / "ny_data")
    check("trasig fil kopieras inte", not bad["installed"] and not gc.credentials_path(V / "ny_data").exists())
    good = gc.install_credentials_file(nerladdad, V / "ny_data")
    check("giltig fil kopieras till rätt plats", good["installed"] and gc.credentials_path(V / "ny_data").is_file())
    if sys.platform != "win32":
        check("kopian får rättigheter 0600",
              (gc.credentials_path(V / "ny_data").stat().st_mode & 0o777) == 0o600)
    check("filsteget blir grönt efter installation",
          gc.setup_steps(V / "ny_data")[5]["done"] is True)
    check("hittar nedladdad fil i Hämtade filer",
          gc.find_downloaded_credentials([V]) == nerladdad)
    check("hittar inget i tom mapp", gc.find_downloaded_credentials([V / "ny_data"]) is None)

    # --- 11. Retry vid tillfälliga fel ------------------------------------
    print("\n11. Retry (exponentiell backoff med jitter)")
    svc_flaky = FakeService(fail_first=2)
    väntetider = []
    with mock.patch.object(gc.time, "sleep", lambda _s: None):
        r = gc.push_task(svc_flaky, "primary", UPPGIFT, gc.EventMap(D / "google" / "m3.json"))
    check("försöker om och lyckas till slut", r["ok"], str(r))
    check("gjorde 3 insert-försök", sum(1 for c in svc_flaky.calls if c[0] == "insert") == 3)

    försök = {"n": 0}

    def _flaky():
        försök["n"] += 1
        if försök["n"] < 3:
            raise _http_error(429, "rate limit")
        return "klar"

    svar = gc.with_retry(_flaky, sleep=väntetider.append)
    check("with_retry returnerar värdet", svar == "klar")
    check("väntade två gånger", len(väntetider) == 2, str(väntetider))
    check("väntetiden ökar (exponentiell)", väntetider[1] > väntetider[0], str(väntetider))
    check("jitter gör väntetiden ojämn",
          väntetider[0] >= gc.RETRY_BASE_DELAY and väntetider[0] <= gc.RETRY_BASE_DELAY * 1.3)

    def _permanent():
        raise _http_error(400, "bad request")

    try:
        gc.with_retry(_permanent, sleep=lambda _s: None)
        check("permanent fel försöker inte om", False)
    except Exception as e:
        check("permanent fel kastas direkt (ingen retry)", gc._error_status(e) == 400)

    # --- 12. Felöversättning ---------------------------------------------
    print("\n12. Begripliga svenska fel")
    check("401 → koppla om", "Koppla kontot på nytt" in gc.handle_http_error(_http_error(401)))
    check("403 → API/kvot/testanvändare", "API är inte aktiverat" in gc.handle_http_error(_http_error(403)))
    check("404 → finns inte kvar", "finns inte kvar" in gc.handle_http_error(_http_error(404)))
    check("429/5xx → tillfälligt", "tillfälligt" in gc.handle_http_error(_http_error(503)))
    check("429 klassas som tillfälligt", gc.is_transient_error(_http_error(429)))
    check("403 klassas inte som tillfälligt", not gc.is_transient_error(_http_error(403)))
    check("nätverksfel klassas som tillfälligt", gc.is_transient_error(ConnectionError("nät")))
    e = gc.to_user_error(_http_error(404))
    check("to_user_error ger GoogleCalendarError", isinstance(e, gc.GoogleCalendarError))
    check("tekniska detaljer bevaras", "HttpError" in e.technical)

    # --- 13. Kalenderinfo och listor --------------------------------------
    print("\n13. Kalenderinfo, lista och kommande händelser")
    svc2 = FakeService(list_items=[{"id": "e1", "summary": "Möte",
                                    "start": {"date": "2026-10-14"},
                                    "extendedProperties": {"private": {gc.EVENT_TAG_KEY: "a"}}}])
    info = gc.get_calendar_info(svc2, "primary")
    check("kalenderinfo hämtas", info["id"] == "rickard@example.com", str(info))
    check("tidszon med", info["timezone"] == "Europe/Stockholm")
    kal = gc.list_calendars(svc2)
    check("två kalendrar i listan", len(kal) == 2, str(kal))
    check("primärkalendern först", kal[0]["primary"] is True)
    check("kalendrar sorterade (primär, sedan namn)", kal[0]["summary"] == "Rickard")
    ping = gc.test_connection(svc2)
    check("test_connection svarar ok", ping["ok"] is True)
    händelser = gc.list_upcoming_events(svc2, days=14)
    check("kommande händelser listas", len(händelser) == 1 and händelser[0]["summary"] == "Möte")
    check("händelsen kopplas till uppgiften", händelser[0]["taskbord_id"] == "a")

    # --- 14. Ta bort händelse --------------------------------------------
    print("\n14. Ta bort händelse")
    svc3 = FakeService()
    rid = gc.push_task(svc3, "primary", UPPGIFT, gc.EventMap(D / "google" / "m4.json"))["event_id"]
    check("borttagning lyckas", gc.delete_event(svc3, "primary", rid) is True)
    check("borttagen två gånger = fortfarande ok",
          gc.delete_event(svc3, "primary", rid) is True)
    check("get_event på borttagen → None", gc.get_event(svc3, "primary", rid) is None)

    # --- 15. Frånkoppling ------------------------------------------------
    print("\n15. Koppla från")
    check("token finns före frånkoppling", gc.token_path(D).is_file())
    check("frånkoppling lyckas", gc.disconnect(D) is True)
    check("token borta", not gc.token_path(D).is_file())
    check("kontoinfo borta", not gc.account_path(D).is_file())
    check("credentials.json behålls (nästa inloggning blir snabb)",
          gc.credentials_path(D).is_file())
    check("status = inte ansluten igen",
          gc.get_status(D)["state"] == gc.ConnectionStatus.DISCONNECTED)
    try:
        gc.build_calendar_service(D)
        check("build_calendar_service kräver inloggning", False)
    except gc.GoogleCalendarError as e:
        check("build_calendar_service ger begripligt fel", "Inte ansluten" in e.user_message)

    # --- 16. Utan credentials.json ---------------------------------------
    print("\n16. Innan credentials.json finns")
    D2 = Path(tmpdir) / "utan_filer"
    D2.mkdir()
    try:
        gc.authenticate_google_calendar(D2, open_browser=False)
        check("connect utan credentials.json ger fel", False)
    except gc.GoogleCalendarError as e:
        check("connect förklarar vad som saknas", "credentials.json" in e.user_message)
        check("felet hänvisar till guiden", "GOOGLE_CALENDAR.md" in e.user_message)

# --- 17. Kopplingen in i appen (statisk kontroll) -------------------------
print("\n17. Menykoppling i appen")
main_py = (ROOT / "main.pyw").read_text(encoding="utf-8")
widget_py = (ROOT / "ui" / "widget.py").read_text(encoding="utf-8")
dlg_py = (ROOT / "ui" / "google_calendar_dialog.py").read_text(encoding="utf-8") \
    if (ROOT / "ui" / "google_calendar_dialog.py").is_file() else ""
settings_py = (ROOT / "core" / "settings.py").read_text(encoding="utf-8")

check("main.pyw öppnar Google-dialogen",
      "ui.google_calendar_dialog" in main_py and "open_google_calendar_dialog" in main_py)
check("main.pyw kopplar tray-posten till metoden",
      "self._google_calendar_action.triggered.connect" in main_py)
check("tray-menyn har Google Calendar-posten", "Google Calendar" in main_py)
check("widgeten har Google Calendar-dialogen", "open_google_calendar_dialog" in widget_py)
check("uppgiftsmenyn kan skicka en uppgift", "push_task" in (widget_py + dlg_py))
check("dialogen finns", bool(dlg_py))
check("dialogen har guide och historik", "GoogleSetupWizard" in dlg_py and "HistoryDialog" in dlg_py)
check("dialogen kontrollerar credentials.json före inloggning", "validate_credentials_file" in dlg_py)
check("uppgiftsmenyn har kalenderhistorik", "_on_show_task_calendar_history" in widget_py)
check("inställningarna har google_calendar_done_style", "google_calendar_done_style" in settings_py)
check("dialogen har uppgiftsväljare", "TaskPickerDialog" in dlg_py and "valda_ids" in dlg_py)
check("\"skicka alla\" skickar inte längre utan val", "select_tasks_by_ids" in dlg_py)
check("dialogen kör nätverket i en tråd (UI får inte frysa)",
      "QThread" in dlg_py or "Thread" in dlg_py)
check("inställningarna har google_calendar_id", "google_calendar_id" in settings_py)
check("inställningarna har google_calendar_enabled", "google_calendar_enabled" in settings_py)
check("schema-versionen är höjd", "SETTINGS_VERSION: Final[int] = 11" in settings_py)
check("valfria paket listade i requirements-optional.txt",
      "google-api-python-client" in (ROOT / "requirements-optional.txt").read_text(encoding="utf-8"))
check("plugin-registret känner igen google-paketen",
      "google-api-python-client" in main_py and "PLUGIN_REGISTRY" in main_py)
check("guiden GOOGLE_CALENDAR.md finns", (ROOT / "GOOGLE_CALENDAR.md").is_file())
check(".gitignore skyddar token-filen", "token.json" in (ROOT / ".gitignore").read_text(encoding="utf-8"))
check(".gitignore skyddar credentials.json",
      "credentials.json" in (ROOT / ".gitignore").read_text(encoding="utf-8"))

# --- Dubblerade namn: den sista definitionen vinner TYST --------------------
# Den här kontrollen finns för att en riktig bugg upptäcktes här: metoden som
# öppnar Google-dialogen och metoden som öppnar Google med en uppgift hade
# samma namn i samma klass. Python behåller den sista — menyvalet kraschade
# tyst och syntes bara som en rad i loggen.
import ast as _ast  # noqa: E402

_GENOM = (_ast.If, _ast.For, _ast.While, _ast.With, _ast.Try,
          _ast.AsyncWith, _ast.AsyncFor)


def _definitioner(kropp):
    """Alla def/class i ETT scope (även inuti if/for/try)."""
    ut = []
    for nod in kropp:
        if isinstance(nod, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            ut.append(nod)
        elif isinstance(nod, _GENOM):
            for barn in _ast.iter_child_nodes(nod):
                ut.extend(_definitioner([barn]))
    return ut


def _dubbletter(fil):
    """[(scope, namn, rad1, rad2)] för namn som definieras två gånger."""
    trad = _ast.parse(Path(fil).read_text(encoding="utf-8"))
    fynd = []

    def scope(nod, kropp, väg):
        sedda = {}
        for d in _definitioner(kropp):
            if d.name in sedda:
                fynd.append((" > ".join(väg) or str(fil), d.name, sedda[d.name], d.lineno))
            sedda[d.name] = d.lineno
            scope(d, d.body, väg + [d.name])

    scope(trad, trad.body, [str(Path(fil).name)])
    return fynd


def _antal_definitioner(fil: str, namn: str) -> int:
    """Hur många gånger ett namn definieras i en fil (alla scopes)?"""
    trad = _ast.parse((ROOT / fil).read_text(encoding="utf-8"))
    return sum(1 for n in _ast.walk(trad)
               if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))
               and n.name == namn)


# Namnen som den här funktionen kopplar in i menyerna får bara finnas EN gång
for _fil, _namn in [
    ("ui/widget.py", "_on_open_google_calendar"),
    ("ui/widget.py", "_on_push_task_to_google"),
    ("ui/widget.py", "_on_export_calendar_ics"),
    ("ui/widget.py", "_on_open_task_in_google_calendar"),
    ("ui/widget.py", "_on_export_task_ics"),
    ("main.pyw", "_open_google_calendar"),
    ("main.pyw", "_export_calendar_ics"),
    ("ui/google_calendar_dialog.py", "open_google_calendar_dialog"),
    ("ui/google_calendar_dialog.py", "push_task_with_dialog"),
    ("ui/google_calendar_dialog.py", "run_google_job"),
    ("ui/google_calendar_dialog.py", "TaskPickerDialog"),
    ("ui/google_calendar_dialog.py", "GoogleSetupWizard"),
    ("ui/google_calendar_dialog.py", "HistoryDialog"),
    ("ui/google_calendar_dialog.py", "open_history_dialog"),
    ("ui/widget.py", "_on_show_task_calendar_history"),
]:
    _n = _antal_definitioner(_fil, _namn)
    check(f"{_namn} definieras exakt en gång i {_fil}", _n == 1, f"hittade {_n}")

# Alla dubbletter i appens filer visas (den sista vinner tyst = död kod)
_alla = []
for _f in ("main.pyw", "ui/widget.py", "ui/google_calendar_dialog.py", "ui/donate.py",
           "core/google_calendar.py", "core/settings.py", "core/store.py",
           "core/mail_bridge.py", "core/calendar_export.py"):
    _alla.extend(_dubbletter(str(ROOT / _f)))
if _alla:
    print("\n  ⓘ dubblerade namn i appens filer (sista definitionen vinner):")
    for _scope, _namn, _r1, _r2 in _alla:
        print(f"      {_scope}: {_namn} (rad {_r1} och {_r2})")
else:
    print("\n  ✓ inga dubblerade namn i appens filer")

# De nya filerna ska vara helt fria från dubbletter
for _f in ("core/google_calendar.py", "ui/google_calendar_dialog.py"):
    _d = _dubbletter(str(ROOT / _f))
    check(f"inga dubblerade namn i {_f}", _d == [], str(_d))

# --- 18. Hela kedjan: appens butik + inställningar + Google (utan nätverk) --
# Det här är så nära "på riktigt" testet kommer utan webbläsare och nät:
# en uppgift skapas i TaskBords RIKTIGA butik, inställningarna läses från en
# RIKTIG settings.json, och händelsen som skulle skickats till Google
# granskas fält för fält.
print("\n18. Hela kedjan (TaskStore + Settings + Google)")

from core.settings import Settings  # noqa: E402
from core.store import TaskStore    # noqa: E402

with tempfile.TemporaryDirectory() as kedja_tmp:
    K = Path(kedja_tmp) / "data"
    K.mkdir()
    skriv_credentials_file(K)

    sett = Settings(str(K / "settings.json"))
    store = TaskStore(data_dir_override=str(K))
    uppgift_id = store.add_task(
        title="Lämna in rapporten", priority="high",
        due_date="2026-10-22", tags=["jobb"],
    )
    store.add_subtask(uppgift_id, "Skriv sammanfattning")
    store.save()
    alla = [t for t in store.all_tasks() if t.get("id") == uppgift_id]
    check("uppgiften finns i appens butik", len(alla) == 1, f"fick {len(alla)}")
    uppgift = dict(alla[0]) if alla else {}

    # Koppla kontot (webbläsaren ersatt av attrapp)
    svc = FakeService()
    with mock.patch.object(gc, "build_calendar_service", return_value=svc):
        with mock.patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
            return_value=fake_credentials(),
        ):
            gc.authenticate_google_calendar(K, open_browser=False)
    sett.set_google_calendar_enabled(True)

    check("status är ansluten för appens datamapp",
          gc.get_status(K)["state"] == gc.ConnectionStatus.CONNECTED)
    check("inställningen minns anslutningen", sett.google_calendar_enabled() is True)
    check("kalender-id läses från inställningarna",
          sett.google_calendar_id() in ("primary", "rickard@example.com"))

    # Skicka uppgiften precis som menyn gör
    em = gc.load_event_map(K)
    r = gc.push_task(
        svc, sett.google_calendar_id(), uppgift, em,
        color_by_priority=sett.google_calendar_color_by_priority(),
    )
    check("uppgiften skickades", r["ok"] and r["action"] == "skapad", str(r))
    kropp = svc.last_body or {}
    check("titel från uppgiften", kropp.get("summary") == "Lämna in rapporten",
          str(kropp.get("summary")))
    check("förfallodatumet blev händelsens datum",
          (kropp.get("start") or {}).get("date") == "2026-10-22")
    check("delmomentet finns i beskrivningen",
          "Skriv sammanfattning" in str(kropp.get("description", "")))
    check("taggen finns i beskrivningen", "jobb" in str(kropp.get("description", "")))
    check("hög prioritet → röd färg", kropp.get("colorId") == "11")
    check("märket pekar på rätt uppgift",
          ((kropp.get("extendedProperties") or {}).get("private") or {})
          .get(gc.EVENT_TAG_KEY) == uppgift_id)
    check("mappningen sparades i appens datamapp",
          gc.load_event_map(K).get(uppgift_id) == r["event_id"])

    # Andra sändningen = uppdatering (inte dubblett)
    r2 = gc.push_task(svc, sett.google_calendar_id(), uppgift, em)
    check("andra sändningen uppdaterar i stället för att dubblera",
          r2["action"] == "uppdaterad", str(r2))

    # Frånkoppling
    check("frånkoppling raderar token", gc.disconnect(K) is True)
    sett.set_google_calendar_enabled(False)
    check("status är inte längre ansluten",
          gc.get_status(K)["state"] == gc.ConnectionStatus.DISCONNECTED)
    check("inställningen minns frånkopplingen",
          sett.google_calendar_enabled() is False)
    check("uppgifterna ligger kvar i butiken efter frånkoppling",
          len([t for t in TaskStore(data_dir_override=str(K)).all_tasks()
               if t.get("id") == uppgift_id]) == 1)

print("\n" + "=" * 66)
if FEL == 0:
    print(f"✓ ALLA GOOGLE-TESTER PASSERADE ({TESTAD} kontroller)")
else:
    print(f"✗ {FEL} av {TESTAD} kontroller misslyckades")
print("=" * 66)
sys.exit(1 if FEL else 0)
