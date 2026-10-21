# -*- coding: utf-8 -*-
"""
google_calendar.py — NY v8 (2026-10-12): lokal Google Calendar-anslutning.

Rickard 2026-10-12: "gör i appen att man lokalt kopplar OAuth".

Vad "lokalt" betyder här — och varför det är säkert:
  • Hela OAuth-flödet körs på din egen dator. Appen öppnar webbläsaren,
    du loggar in hos Google och godkänner. Google skickar tillbaka svaret
    till en tillfällig server på **127.0.0.1** (loopback) som bara finns
    under inloggningen.
  • **Ingen server utanför din dator är inblandad.** Appen har ingen
    backend, inget konto hos oss och skickar ingenting någon annanstans.
  • Åtkomstbeviset (token) sparas **bara lokalt** i `js/google/token.json`
    med filrättigheter 0600 (bara din användare kan läsa den).
  • Behörigheterna är så snäva som möjligt: skapa/ändra händelser i din
    kalender + läsa kalenderlistan. Inget annat.
  • Koppla från när du vill: filen raderas och appen glömmer allt.

Engångssteg (bara en gång, hos Google):
  1. Skapa ett projekt i Google Cloud Console (gratis).
  2. Aktivera **Google Calendar API**.
  3. Skapa OAuth-klient av typen **Datorapp** och ladda ner JSON-filen.
  4. Lägg filen här: `js/google/credentials.json`
     (appen hittar den även som `credentials.json` eller
     `client_secret*.json` i appmappen).

Se `GOOGLE_CALENDAR.md` för steg-för-steg med bildtexter.

API:t nedan är medvetet namnlikt det gamla `Script/API.py` (som Rickards
tidigare projekt använde) så att vanan sitter kvar:
`authenticate_google_calendar`, `build_calendar_service`, `create_event`,
`patch_event`, `update_event`, `delete_event`, `get_event`,
`list_upcoming_events`, `list_calendars`, `get_calendar_info`,
`test_connection`, `discover_token_file`, `discover_credentials_file`,
`with_retry`, `handle_http_error`, `ConnectionStatus`.

Skillnad mot det gamla API:t: **ett konto** i taget (inte fem slots).
Fler konton kan läggas till senare utan att token-lagret ändras
(`discover_token_file` letar redan efter `token*.json`).

Beroenden (valfria — appen fungerar utan dem):
    pip install google-api-python-client google-auth-oauthlib
"""
from __future__ import annotations

import json
from contextlib import suppress
import logging
import os
import random
import threading
import time
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("GoogleCalendar")
LOG_PREFIX = "[GCAL]"

# --------------------------------------------------------------------------
# Konstanter
# --------------------------------------------------------------------------
# Så snäva behörigheter som möjligt:
#   calendar.events    → skapa/ändra/ta bort händelser
#   calendar.readonly  → läsa kalenderlistan (behövs för att välja kalender)
SCOPES: Tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
)

# Hur länge inloggningen får vänta på att du godkänner i webbläsaren.
# Gör att tråden aldrig kan hänga för evigt om fönstret glöms bort.
CONNECT_TIMEOUT_SEC: int = 300

DEFAULT_CALENDAR_ID: str = "primary"
GOOGLE_DIRNAME: str = "google"
CREDENTIALS_FILENAME: str = "credentials.json"
# Medföljande OAuth-klient ("Datorapp") som utvecklaren lägger i appen en enda gång. Finns den
# behöver användaren inte skapa något hos Google — bara logga in och godkänna. Enligt Googles
# regler för datorappar är klient-id:t inte en hemlighet. Mappen core/ skickas med i releasen.
BUNDLED_CLIENT_FILENAME: str = "google_client.json"
TOKEN_FILENAME: str = "token.json"
ACCOUNT_FILENAME: str = "account.json"
EVENT_MAP_FILENAME: str = "event_map.json"

# Private-märke på varje händelse → vi hittar tillbaka till uppgiften
# även om mappningen skulle tappas (t.ex. ominstallation).
EVENT_TAG_KEY: str = "taskbord_id"
EVENT_SOURCE_VALUE: str = "taskbord"

# Google-färger per prioritet (11 = Tomat/röd, 5 = Banan/gul, 10 = Basilika/grön)
COLOR_BY_PRIORITY: Dict[str, str] = {"high": "11", "medium": "5", "low": "10"}

# Klara uppgifter: Google Calendar saknar "överstruken" för heldagshändelser,
# så en klar uppgift markeras med grå färg (Grafit = 8) och en av stilarna:
#   "grey"   → ✅ framför titeln + grå färg  (standard)
#   "strike" → överstruken titel (Unicode) + ✅ + grå färg
#   "off"    → ingen särskild markering (bara beskrivningen säger "Klar")
DONE_STYLES: Tuple[str, ...] = ("grey", "strike", "off")
DEFAULT_DONE_STYLE: str = "grey"
DONE_COLOR_ID: str = "8"
DONE_PREFIX: str = "✅ "
_COMBINING_STROKE: str = "\u0336"

HISTORY_FILENAME: str = "history.json"
HISTORY_MAX_ENTRIES: int = 500

# Retry (exponentiell backoff med jitter — som i gamla Script/API.py)
RETRY_ATTEMPTS: int = 3
RETRY_BASE_DELAY: float = 0.8
RETRY_MAX_DELAY: float = 8.0
RETRY_JITTER: float = 0.25
TRANSIENT_STATUS: Tuple[int, ...] = (429, 500, 502, 503, 504)

# Guider
GOOGLE_CONSOLE_CREDENTIALS_URL: str = "https://console.cloud.google.com/apis/credentials"
GOOGLE_CONSOLE_LIBRARY_URL: str = (
    "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"
)
GOOGLE_CALENDAR_URL: str = "https://calendar.google.com/"
GOOGLE_CLOUD_PROJECT_URL: str = "https://console.cloud.google.com/projectcreate"
GOOGLE_CONSOLE_CONSENT_URL: str = "https://console.cloud.google.com/apis/credentials/consent"

MAX_CALENDAR_ID_LEN: int = 200
MAX_EVENTS_PREVIEW: int = 25

# Env-variabel för den som vill ha credentials på annan plats
ENV_CREDENTIALS: str = "TASKBORD_GOOGLE_CREDENTIALS"


# --------------------------------------------------------------------------
# Fel
# --------------------------------------------------------------------------
class GoogleCalendarError(Exception):
    """Fel som går att visa för användaren (svensk text i `user_message`)."""

    def __init__(self, user_message: str, technical: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical or ""


class ConnectionStatus(str, Enum):
    """Anslutningens läge — används av dialogen och av menyn."""
    NO_LIBRARY = "no_library"          # Google-paketen är inte installerade
    NOT_CONFIGURED = "not_configured"  # credentials.json saknas
    DISCONNECTED = "disconnected"      # credentials finns, men inte inloggad
    CONNECTED = "connected"            # inloggad, token finns
    ERROR = "error"                    # token finns men går inte att läsa

    @property
    def etikett(self) -> str:
        return {
            ConnectionStatus.NO_LIBRARY: "Google-paketen saknas",
            ConnectionStatus.NOT_CONFIGURED: "Inte konfigurerad",
            ConnectionStatus.DISCONNECTED: "Inte ansluten",
            ConnectionStatus.CONNECTED: "Ansluten",
            ConnectionStatus.ERROR: "Fel på anslutningen",
        }.get(self, str(self.value))


# --------------------------------------------------------------------------
# Paketkontroll (importeras på begäran — appen får aldrig krascha utan dem)
# --------------------------------------------------------------------------
def is_google_library_available() -> bool:
    """Är google-api-python-client + google-auth-oauthlib installerade?"""
    try:
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
        return True
    except Exception:
        return False


def missing_packages() -> List[str]:
    """Lista med pip-paket som saknas (tom = allt finns)."""
    saknas: List[str] = []
    try:
        import google_auth_oauthlib  # noqa: F401
    except Exception:
        saknas.append("google-auth-oauthlib")
    try:
        import googleapiclient  # noqa: F401
    except Exception:
        saknas.append("google-api-python-client")
    return saknas


def install_hint() -> str:
    """Kommandoraden användaren kan köra om paketen saknas."""
    pk = missing_packages() or ["google-api-python-client", "google-auth-oauthlib"]
    return "pip install " + " ".join(pk)


def _require_library() -> None:
    """Kasta ett tydligt fel (med svensk text) om paketen saknas."""
    saknas = missing_packages()
    if saknas:
        raise GoogleCalendarError(
            "Google-paketen är inte installerade.\n\n"
            f"Kör i en kommandotolk:\n    pip install {' '.join(saknas)}\n\n"
            "…eller starta appen med FORSTA_START.bat som installerar dem "
            "automatiskt.",
            technical=f"missing: {', '.join(saknas)}",
        )


# --------------------------------------------------------------------------
# Sökvägar
# --------------------------------------------------------------------------
def google_dir(data_dir: Any) -> Path:
    """Katalogen där Google-filerna ligger (`<data>/google`)."""
    return Path(str(data_dir)) / GOOGLE_DIRNAME


def credentials_path(data_dir: Any) -> Path:
    """Standardplats för den nedladdade OAuth-klientfilen."""
    return google_dir(data_dir) / CREDENTIALS_FILENAME


def token_path(data_dir: Any) -> Path:
    """Platsen för åtkomstbeviset (skapas av appen vid inloggning)."""
    return google_dir(data_dir) / TOKEN_FILENAME


def account_path(data_dir: Any) -> Path:
    """Kontoinfo (e-post, tidszon) — sparas vid lyckad inloggning."""
    return google_dir(data_dir) / ACCOUNT_FILENAME


def history_path(data_dir: Any) -> Path:
    """Sändningshistorik (vad som skickats, när och med vilket resultat)."""
    return google_dir(data_dir) / HISTORY_FILENAME


def event_map_path(data_dir: Any) -> Path:
    """Mappning uppgifts-id → Google-händelse (för uppdatering i stället för dubblett)."""
    return google_dir(data_dir) / EVENT_MAP_FILENAME


def discover_credentials_file(
    data_dir: Any,
    extra_dirs: Optional[List[Any]] = None,
) -> Optional[Path]:
    """
    Hitta OAuth-klientfilen (credentials.json / client_secret*.json).

    Letar i den ordning som är mest praktisk för användaren:
      1. miljövariabeln TASKBORD_GOOGLE_CREDENTIALS
      2. `<data>/google/credentials.json`
      3. `<data>/google/client_secret*.json`
      4. `<data>/credentials.json`
      5. appmappen (extra_dirs, t.ex. där main.pyw ligger)
    """
    kandidater: List[Path] = []

    env = os.environ.get(ENV_CREDENTIALS, "").strip()
    if env:
        kandidater.append(Path(env))

    gdir = google_dir(data_dir)
    kandidater.append(gdir / CREDENTIALS_FILENAME)
    kandidater.append(Path(str(data_dir)) / CREDENTIALS_FILENAME)
    # Googles nedladdade fil heter ofta client_secret_<långt id>.json —
    # leta efter den både i google/-mappen och i datamappen (där folk
    # brukar lägga filen när de laddat ner den).
    for mapp in (gdir, Path(str(data_dir))):
        try:
            if mapp.is_dir():
                kandidater.extend(sorted(mapp.glob("client_secret*.json")))
        except Exception:
            continue

    for extra in extra_dirs or []:
        try:
            p = Path(str(extra))
            kandidater.append(p / CREDENTIALS_FILENAME)
            if p.is_dir():
                kandidater.extend(sorted(p.glob("client_secret*.json")))
        except Exception:
            continue

    for k in kandidater:
        try:
            if k.is_file() and k.stat().st_size > 0:
                return k
        except Exception:
            continue
    # Sist: den medföljande klienten (ger "enkel koppling" utan egen Google-installation).
    bundled = bundled_client_file()
    if bundled is not None:
        return bundled
    return None


def bundled_client_file() -> Optional[Path]:
    """Sökvägen till appens medföljande OAuth-klient, om den finns och är giltig."""
    try:
        k = Path(__file__).resolve().parent / BUNDLED_CLIENT_FILENAME
        if k.is_file() and k.stat().st_size > 0 and validate_credentials_file(k)["ok"]:
            return k
    except Exception:
        pass
    return None


def discover_token_file(data_dir: Any) -> Optional[Path]:
    """
    Hitta token-filen. Stödjer flera filer (`token.json`, `token_2.json` …)
    och returnerar den som ändrades senast — gör flerkonto möjligt senare
    utan att ändra något här.
    """
    gdir = google_dir(data_dir)
    kandidater: List[Path] = []
    try:
        if gdir.is_dir():
            kandidater.extend(gdir.glob("token*.json"))
    except Exception:
        pass
    giltiga = [p for p in kandidater if _is_file_nonempty(p)]
    if not giltiga:
        return None
    try:
        return max(giltiga, key=lambda p: p.stat().st_mtime)
    except Exception:
        return giltiga[0]


def _is_file_nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


# --------------------------------------------------------------------------
# Fillagring (atomiskt + snäva rättigheter — inga halvskrivna tokens)
# --------------------------------------------------------------------------
def _atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Skriv atomiskt (temp-fil i samma mapp + os.replace) med rättigheter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        try:
            os.chmod(tmp, mode)
        except Exception:
            pass  # Windows utan POSIX-rättigheter
        os.replace(str(tmp), str(path))
        try:
            os.chmod(path, mode)
        except Exception:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _atomic_write_json(path: Path, data: Dict[str, Any], mode: int = 0o600) -> None:
    """Skriv JSON atomiskt med rättigheter."""
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False), mode)


# --------------------------------------------------------------------------
# Lokal nyckelfil: åtkomstbeviset krypteras så att bara DEN HÄR datorn + DET HÄR Windows-kontot
# kan använda det (Windows DPAPI). Filen ligger kvar i appmappen (js/google/token.json) — men den
# är värdelös om den kopieras till en annan dator eller läses av ett annat konto.
# På andra system (Linux/macOS) gäller filrättigheterna 0600.
# --------------------------------------------------------------------------
TOKEN_PROTECT_KEY: str = "_taskbord_protected"
TOKEN_PROTECT_SCHEME: str = "dpapi-user"
_DPAPI_ENTROPY: bytes = b"TaskBord-Google-token-v1"


def _dpapi_supported() -> bool:
    return os.name == "nt"


def _dpapi_crypt(data: bytes, encrypt: bool) -> bytes:
    """Windows DPAPI (CryptProtectData/CryptUnprotectData), knuten till användaren + datorn."""
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    fn.restype = wintypes.BOOL
    fn.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def mk(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return _BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    blob_in, _keep1 = mk(data)
    blob_ent, _keep2 = mk(_DPAPI_ENTROPY)
    blob_out = _BLOB()
    if not fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None,
              0x1, ctypes.byref(blob_out)):  # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError(f"DPAPI {'kryptering' if encrypt else 'dekryptering'} misslyckades "
                      f"(fel {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def protect_token_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Det som ska skrivas till token.json: krypterat på Windows, annars oförändrat.
    Misslyckas krypteringen sparas filen i klartext (0600) hellre än att inloggningen går förlorad.
    """
    if not _dpapi_supported():
        return info
    try:
        import base64
        blob = _dpapi_crypt(json.dumps(info, ensure_ascii=False).encode("utf-8"), True)
        return {
            TOKEN_PROTECT_KEY: TOKEN_PROTECT_SCHEME,
            "info": "Krypterad Google-nyckel. Kan bara läsas av samma Windows-konto på samma dator.",
            "data": base64.b64encode(blob).decode("ascii"),
            "_taskbord_saved_at": info.get("_taskbord_saved_at", ""),
        }
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} token kunde inte krypteras ({type(e).__name__}) — sparas med "
                       f"filrättigheter i stället")
        return info


def unprotect_token_info(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Motsatsen till protect_token_info. None om filen är krypterad för någon annan / trasig."""
    if not isinstance(raw, dict):
        return None
    if raw.get(TOKEN_PROTECT_KEY) != TOKEN_PROTECT_SCHEME:
        return raw  # äldre/oskyddad fil
    try:
        import base64
        text = _dpapi_crypt(base64.b64decode(str(raw.get("data", ""))), False).decode("utf-8")
        info = json.loads(text)
        return info if isinstance(info, dict) else None
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} token kunde inte dekrypteras ({type(e).__name__}) — "
                       f"den är knuten till ett annat konto/dator. Koppla om kontot.")
        return None


def is_token_protected(path: Any) -> bool:
    """True om token-filen är krypterad (lokal nyckel)."""
    try:
        raw = _read_json(Path(str(path)))
        return bool(raw and raw.get(TOKEN_PROTECT_KEY) == TOKEN_PROTECT_SCHEME)
    except Exception:
        return False


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Läs JSON, returnera None vid fel (loggar aldrig innehållet)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte läsa {path.name}: {type(e).__name__}")
        return None


# --------------------------------------------------------------------------
# Kontroll av credentials.json + guidad första koppling
# --------------------------------------------------------------------------
_REQUIRED_CLIENT_KEYS: Tuple[str, ...] = ("client_id", "client_secret", "auth_uri", "token_uri")


def validate_credentials_file(path: Any) -> Dict[str, Any]:
    """
    Kontrollera en nedladdad OAuth-klientfil INNAN inloggningen startar.

    Fångar de vanliga misstagen på svenska: fel klienttyp (Webbapp i stället
    för Datorapp), tjänstekonto-nyckel, trasig JSON, saknade fält. Läser
    filen men returnerar eller loggar aldrig klienthemligheten.

    Returnerar {"ok", "problems", "warnings", "client_type", "client_id",
    "project_id", "path"}.
    """
    res: Dict[str, Any] = {
        "ok": False, "problems": [], "warnings": [], "client_type": "",
        "client_id": "", "project_id": "", "path": str(path or ""),
    }
    problems: List[str] = res["problems"]
    p = Path(str(path)) if path else None
    if p is None or not p.is_file():
        problems.append("Filen finns inte.")
        return res
    try:
        if p.stat().st_size == 0:
            problems.append("Filen är tom — ladda ner den på nytt från Google Cloud.")
            return res
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        problems.append(
            "Filen är inte giltig JSON. Ladda ner den på nytt från Google Cloud "
            "(Skapa inloggningsuppgifter → OAuth-klient-ID → Ladda ner JSON)."
        )
        return res
    if not isinstance(raw, dict):
        problems.append("Filen har fel format (förväntade ett JSON-objekt).")
        return res

    if raw.get("type") == "service_account":
        problems.append(
            "Det här är en nyckel för ett tjänstekonto. TaskBord behöver en "
            "OAuth-klient av typen “Datorapp” (Desktop app)."
        )
        return res
    if "installed" in raw and isinstance(raw["installed"], dict):
        res["client_type"] = "installed"
        cfg = raw["installed"]
    elif "web" in raw and isinstance(raw["web"], dict):
        res["client_type"] = "web"
        cfg = raw["web"]
        problems.append(
            "Klienttypen är “Webbapplikation”. Skapa en ny OAuth-klient och "
            "välj programtypen “Datorapp” (Desktop app) — annars fungerar "
            "inte den lokala inloggningen."
        )
    else:
        problems.append(
            "Filen ser inte ut som en OAuth-klientfil (saknar avsnittet "
            "“installed”). Ladda ner JSON-filen för en “Datorapp”."
        )
        return res

    saknas = [k for k in _REQUIRED_CLIENT_KEYS if not str(cfg.get(k) or "").strip()]
    if saknas:
        problems.append("Filen saknar fält: " + ", ".join(saknas) + ".")
    cid = str(cfg.get("client_id") or "")
    res["client_id"] = cid
    res["project_id"] = str(cfg.get("project_id") or "")
    if cid and not cid.endswith(".apps.googleusercontent.com"):
        res["warnings"].append("Klient-ID:t ser ovanligt ut (slutar inte på .apps.googleusercontent.com).")
    res["ok"] = not problems
    return res


def install_credentials_file(source: Any, data_dir: Any) -> Dict[str, Any]:
    """
    Kopiera en nedladdad klientfil till `<data>/google/credentials.json`
    (0600) — men bara om den klarar kontrollen. Returnerar kontrollresultatet
    (+ "installed": True/False).
    """
    res = validate_credentials_file(source)
    res["installed"] = False
    if not res["ok"]:
        return res
    try:
        text = Path(str(source)).read_text(encoding="utf-8-sig")
        _atomic_write_text(credentials_path(data_dir), text, mode=0o600)
        res["installed"] = True
        logger.info(f"{LOG_PREFIX} credentials.json installerad i {google_dir(data_dir)}")
    except Exception as e:
        res["ok"] = False
        res["problems"].append(f"Kunde inte kopiera filen: {type(e).__name__}")
    return res


def setup_steps(data_dir: Any, extra_dirs: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """
    Stegen i den guidade första kopplingen (visas som en guide i appen).

    Varje steg: key, title, text, url (valfri), done. `done` är True/False
    för det appen kan kontrollera själv (paket, filen, inloggning) och None
    för engångssteg hos Google som bara användaren kan bekräfta.
    """
    cred_file = discover_credentials_file(data_dir, extra_dirs=extra_dirs)
    check = validate_credentials_file(cred_file) if cred_file else None
    token_file = discover_token_file(data_dir)
    if cred_file is None:
        fil_text = (
            "Lägg den nedladdade JSON-filen här:\n"
            f"{credentials_path(data_dir)}\n\n"
            "Eller klicka “Välj fil…” så kopierar appen den åt dig."
        )
    elif check and check["ok"]:
        fil_text = f"✅ Filen hittades och ser rätt ut:\n{cred_file}"
    else:
        fil_text = (
            f"❌ Filen hittades ({cred_file}) men har problem:\n• "
            + "\n• ".join((check or {}).get("problems") or ["okänt fel"])
        )
    return [
        {"key": "library", "title": "Installera Google-paketen",
         "text": ("Appen behöver två små paket för att prata med Google.\n"
                  + ("✅ De är redan installerade." if is_google_library_available()
                     else f"Kör i en kommandotolk:\n    {install_hint()}\n"
                          "(eller starta via FORSTA_START.bat).")),
         "url": "", "done": is_google_library_available()},
        {"key": "project", "title": "Skapa ett projekt hos Google",
         "text": "Gratis och tar en minut. Namnet spelar ingen roll, t.ex. “TaskBord”.",
         "url": GOOGLE_CLOUD_PROJECT_URL, "done": None},
        {"key": "api", "title": "Aktivera Google Calendar API",
         "text": "Öppna sidan och klicka på knappen “Aktivera”.",
         "url": GOOGLE_CONSOLE_LIBRARY_URL, "done": None},
        {"key": "consent", "title": "Godkännandeskärmen",
         "text": ("Välj “Extern” → Skapa, fyll i appnamn och din e-post.\n"
                  "Viktigt: lägg till din egen Gmail-adress under “Testanvändare” — "
                  "annars får du felet 403 access_denied."),
         "url": GOOGLE_CONSOLE_CONSENT_URL, "done": None},
        {"key": "client", "title": "Skapa nyckeln (OAuth-klient)",
         "text": ("Skapa inloggningsuppgifter → OAuth-klient-ID.\n"
                  "Programtyp: “Datorapp” (Desktop app) — viktigt!\n"
                  "Klicka sedan “Ladda ner JSON”."),
         "url": GOOGLE_CONSOLE_CREDENTIALS_URL, "done": None},
        {"key": "file", "title": "Lägg filen i TaskBord",
         "text": fil_text, "url": "",
         "done": bool(check and check["ok"])},
        {"key": "login", "title": "Logga in",
         "text": ("Klicka “Koppla Google-konto” — webbläsaren öppnas, välj ditt konto "
                  "och tryck Tillåt." if not token_file else
                  "✅ Kontot är redan kopplat."),
         "url": "", "done": bool(token_file)},
    ]


# --------------------------------------------------------------------------
# Token & konto
# --------------------------------------------------------------------------
def save_token(credentials_obj: Any, data_dir: Any) -> Path:
    """
    Spara åtkomstbeviset lokalt (0600, atomiskt).

    Filen innehåller refresh-token och klienthemligheten — precis som
    Googles egna exempel. Den lämnar aldrig datorn.
    """
    _require_library()
    path = token_path(data_dir)
    try:
        text = credentials_obj.to_json()
    except Exception as e:
        raise GoogleCalendarError(
            "Kunde inte läsa av inloggningen från Google.",
            technical=f"to_json: {type(e).__name__}: {e}",
        )
    data = json.loads(text)
    if not isinstance(data, dict) or not data.get("refresh_token") and not data.get("token"):
        raise GoogleCalendarError(
            "Google svarade utan åtkomstbevis — försök koppla igen.",
            technical="token.json saknar token/refresh_token",
        )
    if not data.get("refresh_token"):
        # Utan refresh-token slutar inloggningen att fungera efter ~1 timme,
        # eftersom Google inte gav någon långlivad nyckel. Värt en varning.
        logger.warning(
            f"{LOG_PREFIX} Google gav ingen refresh-token — inloggningen "
            f"kommer att sluta gälla inom en timme. Koppla om kontot."
        )
    data["_taskbord_saved_at"] = _now_iso()
    data["_taskbord_scopes"] = list(SCOPES)
    _atomic_write_json(path, protect_token_info(data), mode=0o600)
    logger.info(
        f"{LOG_PREFIX} token sparad lokalt ({'krypterad' if is_token_protected(path) else 'klartext 0600'}): {path} "
        f"(refresh_token={'ja' if data.get('refresh_token') else 'nej'}, "
        f"behörigheter={len(SCOPES)})"
    )
    return path


def save_account_info(data_dir: Any, info: Dict[str, Any]) -> Path:
    """Spara kontoinfo (e-post, tidszon) — ingen hemlighet, men privat ändå."""
    path = account_path(data_dir)
    payload = dict(info or {})
    payload.setdefault("connected_at", _now_iso())
    _atomic_write_json(path, payload, mode=0o600)
    return path


def load_account_info(data_dir: Any) -> Optional[Dict[str, Any]]:
    """Läs sparad kontoinfo (None om ingen finns)."""
    path = account_path(data_dir)
    if not _is_file_nonempty(path):
        return None
    return _read_json(path)


def load_credentials(data_dir: Any, allow_refresh: bool = True) -> Optional[Any]:
    """
    Läs token och bygg ett Credentials-objekt.

    Förnyar automatiskt åtkomstbeviset om det har gått ut (Google ger
    korta access-tokens + en långlivad refresh-token). Returnerar None om
    det inte finns någon token eller om den inte går att använda.
    """
    token_file = discover_token_file(data_dir)
    if token_file is None:
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except Exception:
        _require_library()
        return None
    try:
        raw = _read_json(token_file)
        info = unprotect_token_info(raw)
        if info is None:
            return None
        creds = Credentials.from_authorized_user_info(info, list(SCOPES))
        if _dpapi_supported() and raw is not None and raw.get(TOKEN_PROTECT_KEY) != TOKEN_PROTECT_SCHEME:
            # Äldre klartext-token → kryptera den nu
            with suppress(Exception):
                _atomic_write_json(token_file, protect_token_info(info), mode=0o600)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} token kunde inte läsas: {type(e).__name__}")
        return None
    if not getattr(creds, "valid", False):
        if not (allow_refresh and getattr(creds, "refresh_token", None)):
            logger.info(f"{LOG_PREFIX} token är ogiltig och kan inte förnyas")
            return None
        try:
            creds.refresh(Request())
            save_token(creds, data_dir)
            logger.info(f"{LOG_PREFIX} åtkomstbevis förnyat (refresh OK)")
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte förnya token: {type(e).__name__}")
            return None
    return creds


def disconnect(data_dir: Any, remove_account: bool = True) -> bool:
    """
    Koppla från: radera token (och kontoinfo). credentials.json behålls,
    så nästa inloggning går snabbt.
    """
    bort = 0
    for path in [token_path(data_dir), account_path(data_dir) if remove_account else None]:
        if path is None:
            continue
        try:
            if path.exists():
                path.unlink()
                bort += 1
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte ta bort {path.name}: {e}")
            return False
    logger.info(f"{LOG_PREFIX} frånkopplad ({bort} fil(er) borttagna)")
    return True


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
def get_status(data_dir: Any, extra_dirs: Optional[List[Any]] = None) -> Dict[str, Any]:
    """
    Samlad status för dialogen och menyn.

    Nycklar: state (ConnectionStatus), label/meddelande (svensk text),
    email, calendar_id, has_library, has_credentials, paths.
    """
    har_bib = is_google_library_available()
    creds_file = discover_credentials_file(data_dir, extra_dirs=extra_dirs)
    token_file = discover_token_file(data_dir)
    konto = load_account_info(data_dir) or {}
    email = str(konto.get("email") or "").strip()

    if not har_bib:
        state = ConnectionStatus.NO_LIBRARY
        meddelande = (
            "Google-paketen är inte installerade.\n"
            f"Kör:  {install_hint()}"
        )
    elif creds_file is None:
        state = ConnectionStatus.NOT_CONFIGURED
        meddelande = (
            "Filen credentials.json saknas.\n"
            f"Lägg den i:  {credentials_path(data_dir)}"
        )
    elif token_file is None:
        state = ConnectionStatus.DISCONNECTED
        meddelande = "Redo att koppla upp — klicka på “Koppla Google-konto”."
    else:
        state = ConnectionStatus.CONNECTED
        meddelande = (
            f"Ansluten som {email}" if email else "Ansluten till Google Calendar"
        )

    return {
        "state": state,
        "label": state.etikett,
        "message": meddelande,
        "email": email,
        "calendar_id": str(konto.get("calendar_id") or DEFAULT_CALENDAR_ID),
        "timezone": str(konto.get("timezone") or ""),
        "has_library": har_bib,
        "has_credentials": creds_file is not None,
        "has_token": token_file is not None,
        "credentials_file": str(creds_file) if creds_file else "",
        "token_file": str(token_file) if token_file else "",
        "google_dir": str(google_dir(data_dir)),
        "missing_packages": missing_packages(),
    }


def is_connected(data_dir: Any, extra_dirs: Optional[List[Any]] = None) -> bool:
    """Sant om det finns en användbar token (utan att testa nätverket)."""
    st = get_status(data_dir, extra_dirs=extra_dirs)
    return st["state"] == ConnectionStatus.CONNECTED


# --------------------------------------------------------------------------
# Service-bygge (samma namn som i gamla Script/API.py)
# --------------------------------------------------------------------------
def build_calendar_service(data_dir: Any, allow_refresh: bool = True) -> Any:
    """
    Bygg en Google Calendar-tjänst från den lokala token-filen.

    Kastar GoogleCalendarError med begriplig svensk text om något saknas.
    """
    _require_library()
    creds = load_credentials(data_dir, allow_refresh=allow_refresh)
    if creds is None:
        raise GoogleCalendarError(
            "Inte ansluten till Google Calendar.\n\n"
            "Öppna ☁️ Google Calendar och klicka på “Koppla Google-konto…”.",
            technical="no usable credentials in token file",
        )
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        raise GoogleCalendarError(
            "Kunde inte starta Google-klienten.",
            technical=f"{type(e).__name__}: {e}",
        )


def authenticate_google_calendar(
    data_dir: Any,
    credentials_file: Optional[Any] = None,
    extra_dirs: Optional[List[Any]] = None,
    port: int = 0,
    open_browser: bool = True,
    timeout_seconds: Optional[int] = CONNECT_TIMEOUT_SEC,
    on_url: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Kör hela OAuth-flödet lokalt och spara token.

    Flödet: appen startar en tillfällig server på 127.0.0.1, öppnar
    webbläsaren, du godkänner hos Google, Google skickar tillbaka svaret
    till localhost-servern och appen sparar token. Klart.

    Returnerar {"ok", "email", "timezone", "token_file"}.
    """
    _require_library()

    cred_file = Path(str(credentials_file)) if credentials_file else \
        discover_credentials_file(data_dir, extra_dirs=extra_dirs)
    if cred_file is None or not _is_file_nonempty(Path(cred_file)):
        raise GoogleCalendarError(
            "Filen credentials.json saknas.\n\n"
            "1. Skapa ett projekt i Google Cloud Console (gratis)\n"
            "2. Aktivera Google Calendar API\n"
            "3. Skapa OAuth-klient av typen “Datorapp”\n"
            "4. Ladda ner JSON-filen och lägg den här:\n"
            f"   {credentials_path(data_dir)}\n\n"
            "Detaljerade steg finns i GOOGLE_CALENDAR.md.",
            technical=f"letade efter credentials i {google_dir(data_dir)}",
        )

    kontroll = validate_credentials_file(cred_file)
    if not kontroll["ok"]:
        raise GoogleCalendarError(
            "credentials.json går inte att använda:\n\n• "
            + "\n• ".join(kontroll["problems"])
            + "\n\nGuiden i appen (🧭 Guidad installation) visar hur du skapar rätt fil.",
            technical=f"credentials-kontroll: {kontroll['problems']}",
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as e:  # pragma: no cover - fångas av _require_library
        raise GoogleCalendarError(
            "Google-paketen är inte installerade.",
            technical=f"{type(e).__name__}: {e}",
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), list(SCOPES))
    except Exception as e:
        raise GoogleCalendarError(
            "Kunde inte läsa credentials.json.\n\n"
            "Ladda ner filen på nytt från Google Cloud Console och välj "
            "klienttypen “Datorapp” (Desktop app).",
            technical=f"{type(e).__name__}: {e}",
        )

    logger.info(
        f"{LOG_PREFIX} startar lokal OAuth-inloggning (loopback 127.0.0.1, "
        f"port={port or 'valfri'}) — öppnar webbläsaren"
    )
    try:
        creds = flow.run_local_server(
            # IP-literalen 127.0.0.1 i stället för "localhost": RFC 8252
            # rekommenderar den för loopback, och den strular inte på
            # datorer där "localhost" bara pekar på IPv6 (::1) medan
            # webbläsaren går till IPv4.
            host="127.0.0.1",
            port=port or 0,
            open_browser=open_browser,
            authorization_prompt_message=(
                "Öppna den här adressen i webbläsaren för att koppla TaskBord:\n{url}\n"
            ),
            success_message=(
                "TaskBord är kopplat! Du kan stänga den här fliken och gå "
                "tillbaka till appen."
            ),
            access_type="offline",   # ger refresh-token (långlivad)
            prompt="consent",
            timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        text = f"{type(e).__name__}: {e}"
        if "timeout" in type(e).__name__.lower() or "timed out" in text.lower() \
                or "timeout" in text.lower():
            raise GoogleCalendarError(
                "Inloggningen tog för lång tid.\n\n"
                "Lämna fönstret öppet och godkänn i webbläsaren inom några "
                "minuter, försök sedan igen.",
                technical=text,
            )
        raise GoogleCalendarError(
            "Kunde inte slutföra inloggningen hos Google.\n\n"
            "Kontrollera att:\n"
            "• webbläsaren öppnades och du godkände åtkomsten\n"
            "• internet fungerar\n"
            "• OAuth-klienten i Google Cloud är av typen “Datorapp”",
            technical=text,
        )

    if on_url:
        try:
            on_url("")
        except Exception:
            pass

    path = save_token(creds, data_dir)

    # Hämta e-post + tidszon (behövs för en tydlig statusrad i appen)
    info: Dict[str, Any] = {"calendar_id": DEFAULT_CALENDAR_ID}
    try:
        service = build_calendar_service(data_dir)
        prim = get_calendar_info(service, DEFAULT_CALENDAR_ID)
        info["email"] = prim.get("id") or ""
        info["timezone"] = prim.get("timezone") or ""
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte hämta kontoinfo: {type(e).__name__}")
    save_account_info(data_dir, info)

    logger.info(
        f"{LOG_PREFIX} ✓ kopplad till Google Calendar"
        f"{' som ' + info['email'] if info.get('email') else ''} "
        f"(token: {path.name})"
    )
    return {
        "ok": True,
        "email": info.get("email", ""),
        "timezone": info.get("timezone", ""),
        "token_file": str(path),
    }


# --------------------------------------------------------------------------
# Felöversättning + retry
# --------------------------------------------------------------------------
def _error_status(exc: BaseException) -> Optional[int]:
    """Plocka fram HTTP-status ur ett GoogleApi-fel (om det finns)."""
    for attr in ("status_code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "resp", None)
    if resp is not None:
        val = getattr(resp, "status", None)
        if isinstance(val, int):
            return val
    return None


def is_transient_error(exc: BaseException) -> bool:
    """Är felet tillfälligt (värt att försöka igen)?"""
    status = _error_status(exc)
    if status in TRANSIENT_STATUS:
        return True
    return isinstance(exc, (ConnectionError, TimeoutError))


def handle_http_error(exc: BaseException) -> str:
    """Översätt ett API-fel till en begriplig svensk mening."""
    status = _error_status(exc)
    if status == 401:
        return (
            "Google säger att inloggningen inte längre gäller.\n"
            "Koppla kontot på nytt (Koppla från → Koppla Google-konto)."
        )
    if status == 403:
        return (
            "Google nekade åtkomsten.\n\n"
            "Vanliga orsaker:\n"
            "• Google Calendar API är inte aktiverat i projektet\n"
            "• ditt konto är inte tillagt som testanvändare\n"
            "• dagskvoten är slut (försök igen senare)"
        )
    if status == 404:
        return "Händelsen eller kalendern finns inte kvar hos Google."
    if status == 410:
        return "Händelsen är borttagen hos Google."
    if status in TRANSIENT_STATUS:
        return (
            "Google svarade inte som det skulle (tillfälligt fel).\n"
            "Försök igen om en liten stund."
        )
    return f"Google-anropet misslyckades: {type(exc).__name__}"


def to_user_error(exc: BaseException) -> GoogleCalendarError:
    """Gör om vilket fel som helst till ett GoogleCalendarError (svensk text)."""
    if isinstance(exc, GoogleCalendarError):
        return exc
    return GoogleCalendarError(handle_http_error(exc), technical=f"{type(exc).__name__}: {exc}")


def with_retry(
    fn: Callable[[], Any],
    attempts: int = RETRY_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
    jitter: float = RETRY_JITTER,
    sleep: Callable[[float], None] = time.sleep,
    retry_predicate: Callable[[BaseException], bool] = is_transient_error,
) -> Any:
    """
    Kör `fn()` och försök igen vid tillfälliga fel.

    Exponentiell backoff med jitter (samma princip som i gamla
    Script/API.py): väntetiden fördubblas för varje försök och kryddas
    med slumpmässig variation så att flera anrop inte krockar.
    """
    försök = max(1, int(attempts))
    senaste: Optional[BaseException] = None
    for i in range(försök):
        try:
            return fn()
        except BaseException as e:  # noqa: BLE001 - skickas vidare nedan
            senaste = e
            if i == försök - 1 or not retry_predicate(e):
                raise
            vänta = min(max_delay, base_delay * (2 ** i))
            vänta += random.uniform(0, vänta * jitter)
            logger.info(
                f"{LOG_PREFIX} tillfälligt fel ({type(e).__name__}, "
                f"status={_error_status(e)}) — nytt försök {i + 2}/{försök} "
                f"om {vänta:.1f}s"
            )
            sleep(vänta)
    if senaste:  # pragma: no cover - nås bara om loopen är tom
        raise senaste
    return None


# --------------------------------------------------------------------------
# Händelsedata
# --------------------------------------------------------------------------
def _now_iso() -> str:
    return _datetime.now(_timezone.utc).isoformat()


def _parse_iso_date(value: Any) -> Optional[_date]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return _datetime.fromisoformat(s).date()
    except Exception:
        pass
    try:
        return _date.fromisoformat(s[:10])
    except Exception:
        return None


def resolve_task_dates(task: Dict[str, Any]) -> Optional[Tuple[_date, _date]]:
    """
    (första dagen, sista dagen) en uppgift upptar i kalendern, båda inkluderade.

    Start + förfallodatum = flera dagar; bara ett av dem = en dag. Delas med
    .ics-exporten (core.calendar_export.event_dates).
    """
    try:
        from core.calendar_export import event_dates
        return event_dates(task)
    except Exception:
        pass
    # Reserv: samma regler om calendar_export inte kan importeras
    due = _parse_iso_date((task or {}).get("due_date"))
    start = _parse_iso_date((task or {}).get("start_date"))
    if due is not None:
        return (start, due) if start is not None and start <= due else (due, due)
    return (start, start) if start is not None else None


def resolve_task_date(task: Dict[str, Any]) -> Optional[_date]:
    """Dagen en uppgift börjar i kalendern (startdatum, annars förfallodatum)."""
    dagar = resolve_task_dates(task)
    return dagar[0] if dagar else None


def strikethrough(text: str) -> str:
    """Överstruken text med Unicode-tecknet U+0336 (mellanslag lämnas orörda)."""
    return "".join(c if c.isspace() else c + _COMBINING_STROKE for c in str(text))


def build_event_body(
    task: Dict[str, Any],
    calendar_id: str = DEFAULT_CALENDAR_ID,
    color_by_priority: bool = True,
    done_style: str = DEFAULT_DONE_STYLE,
) -> Dict[str, Any]:
    """
    Bygg Google-händelsen för en uppgift (heldagshändelse; från startdatum till
    förfallodatum om båda finns, annars en dag).

    Händelsen märks med uppgiftens id i `extendedProperties`, så att vi
    alltid kan hitta tillbaka till den — även om mappningen på disk
    skulle försvinna.
    """
    titel = str(task.get("title") or "").strip()
    dagar = resolve_task_dates(task)
    if not titel or dagar is None:
        raise GoogleCalendarError(
            "Uppgiften behöver en titel och ett förfallodatum eller startdatum "
            "för att bli en kalenderhändelse."
        )
    d, sista = dagar

    body: Dict[str, Any] = {
        "summary": titel,
        "start": {"date": d.isoformat()},
        "end": {"date": (sista + _timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": True},
        "extendedProperties": {
            "private": {
                EVENT_TAG_KEY: str(task.get("id") or "").strip() or titel[:60],
                "taskbord_source": EVENT_SOURCE_VALUE,
            }
        },
    }

    beskrivning = _task_description(task)
    if beskrivning:
        body["description"] = beskrivning

    if color_by_priority:
        färg = COLOR_BY_PRIORITY.get(str(task.get("priority") or "").lower())
        if färg:
            body["colorId"] = färg

    # Heldagshändelser från TaskBord ska aldrig bokas som "upptagen"
    # (gäller både aktiva och klara uppgifter).
    body["transparency"] = "transparent"
    if task.get("done"):
        body["status"] = "confirmed"
        stil = done_style if done_style in DONE_STYLES else DEFAULT_DONE_STYLE
        if stil != "off":
            # Klar = grå (Grafit) och markerad i titeln. Slår prioritetsfärgen.
            body["colorId"] = DONE_COLOR_ID
            if stil == "strike":
                body["summary"] = DONE_PREFIX + strikethrough(titel)
            else:
                body["summary"] = DONE_PREFIX + titel

    return body


def _task_description(task: Dict[str, Any]) -> str:
    """Beskrivning: prioritering, taggar, delmoment, mailinfo (delas med .ics)."""
    try:
        from core.calendar_export import build_description
        return build_description(task)
    except Exception:
        pass
    rader: List[str] = []
    prio = str(task.get("priority") or "").strip()
    if prio and prio != "none":
        rader.append(f"Prioritet: {prio}")
    tags = [str(t) for t in (task.get("tags") or []) if str(t).strip()]
    if tags:
        rader.append("Taggar: " + ", ".join(tags))
    if task.get("done"):
        rader.append("✅ Klar i TaskBord")
    return "\n".join(rader)


def validate_event_data(body: Dict[str, Any]) -> Tuple[bool, str]:
    """Kontrollera att händelsedata håller innan vi skickar till Google."""
    if not isinstance(body, dict):
        return False, "Händelsen är inte ett objekt"
    if not str(body.get("summary") or "").strip():
        return False, "Händelsen saknar titel"
    start = (body.get("start") or {}).get("date") or (body.get("start") or {}).get("dateTime")
    end = (body.get("end") or {}).get("date") or (body.get("end") or {}).get("dateTime")
    if not start or not end:
        return False, "Händelsen saknar start eller slut"
    return True, ""


# --------------------------------------------------------------------------
# CRUD mot Google Calendar
# --------------------------------------------------------------------------
def test_connection(service: Any, calendar_id: str = DEFAULT_CALENDAR_ID) -> Dict[str, Any]:
    """Snabb ping: hämta kalenderns metadata. Returnerar {"ok", "id", ...}."""
    try:
        info = get_calendar_info(service, calendar_id)
        return {"ok": True, **info}
    except GoogleCalendarError:
        raise
    except Exception as e:
        raise to_user_error(e)


def get_calendar_info(service: Any, calendar_id: str = DEFAULT_CALENDAR_ID) -> Dict[str, Any]:
    """Hämta id/sammanfattning/tidszon för en kalender."""
    def _do() -> Any:
        return service.calendars().get(calendarId=calendar_id).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    if not isinstance(raw, dict):
        raise GoogleCalendarError("Google svarade med oväntad data.")
    return {
        "id": raw.get("id", ""),
        "summary": raw.get("summary", ""),
        "timezone": raw.get("timeZone") or raw.get("timezone") or "",
        "description": raw.get("description", ""),
    }


def list_calendars(service: Any, max_results: int = 50) -> List[Dict[str, Any]]:
    """Lista användarens kalendrar (för kalenderväljaren i dialogen)."""
    def _do() -> Any:
        return service.calendarList().list(maxResults=max_results).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    items = (raw or {}).get("items") if isinstance(raw, dict) else None
    ut: List[Dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        ut.append({
            "id": it.get("id", ""),
            "summary": it.get("summary", ""),
            "primary": bool(it.get("primary")),
            "timezone": it.get("timeZone") or "",
            "access_role": it.get("accessRole") or "",
        })
    ut.sort(key=lambda c: (not c["primary"], c["summary"].lower()))
    return ut


def create_event(service: Any, calendar_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Skapa händelse (INSERT)."""
    ok, fel = validate_event_data(body)
    if not ok:
        raise GoogleCalendarError(f"Kunde inte skapa händelsen: {fel}")

    def _do() -> Any:
        return service.events().insert(calendarId=calendar_id, body=body).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    return {"id": (raw or {}).get("id", ""), "htmlLink": (raw or {}).get("htmlLink", "")}


def update_event(service: Any, calendar_id: str, event_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Uppdatera händelse (PUT — hela objektet)."""
    def _do() -> Any:
        return service.events().update(
            calendarId=calendar_id, eventId=event_id, body=body
        ).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    return {"id": (raw or {}).get("id", ""), "htmlLink": (raw or {}).get("htmlLink", "")}


def patch_event(service: Any, calendar_id: str, event_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Uppdatera händelse (PATCH — bara ändrade fält, säkrare)."""
    def _do() -> Any:
        return service.events().patch(
            calendarId=calendar_id, eventId=event_id, body=body
        ).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    return {"id": (raw or {}).get("id", ""), "htmlLink": (raw or {}).get("htmlLink", "")}


def delete_event(service: Any, calendar_id: str, event_id: str) -> bool:
    """Ta bort händelse. Redan borttagen räknas som lyckat."""
    def _do() -> Any:
        return service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    try:
        with_retry(_do)
        return True
    except Exception as e:
        status = _error_status(e)
        if status in (404, 410):
            logger.info(f"{LOG_PREFIX} händelsen fanns redan inte kvar hos Google")
            return True
        raise to_user_error(e)


def get_event(service: Any, calendar_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    """Hämta en enskild händelse (None om den är borttagen)."""
    def _do() -> Any:
        return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    try:
        raw = with_retry(_do, attempts=1)
    except Exception as e:
        if _error_status(e) in (404, 410):
            return None
        raise to_user_error(e)
    return raw if isinstance(raw, dict) else None


def list_upcoming_events(
    service: Any,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    days: int = 14,
    max_results: int = MAX_EVENTS_PREVIEW,
) -> List[Dict[str, Any]]:
    """Kommande händelser (för förhandsvisning i dialogen)."""
    nu = _datetime.now(_timezone.utc)
    tmin = nu.isoformat()
    tmax = (nu + _timedelta(days=max(1, int(days)))).isoformat()

    def _do() -> Any:
        return service.events().list(
            calendarId=calendar_id,
            timeMin=tmin,
            timeMax=tmax,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

    try:
        raw = with_retry(_do)
    except Exception as e:
        raise to_user_error(e)
    ut: List[Dict[str, Any]] = []
    for it in ((raw or {}).get("items") or []):
        if not isinstance(it, dict):
            continue
        start = it.get("start") or {}
        ut.append({
            "id": it.get("id", ""),
            "summary": it.get("summary", ""),
            "start": start.get("date") or start.get("dateTime") or "",
            "taskbord_id": ((it.get("extendedProperties") or {}).get("private") or {})
                           .get(EVENT_TAG_KEY, ""),
        })
    return ut


def search_event_by_task(
    service: Any,
    calendar_id: str,
    task_id: str,
) -> Optional[str]:
    """
    Hitta händelsen som hör till en uppgift via märket i händelsen.

    Sista utvägen när den lokala mappningen saknas (t.ex. efter
    ominstallation eller om användaren bytt dator).
    """
    if not task_id:
        return None

    def _do() -> Any:
        return service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{EVENT_TAG_KEY}={task_id}",
            maxResults=1,
            singleEvents=True,
        ).execute()

    try:
        raw = with_retry(_do, attempts=1)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} sökning efter händelse misslyckades: {type(e).__name__}")
        return None
    items = (raw or {}).get("items") or []
    if items and isinstance(items[0], dict):
        return items[0].get("id") or None
    return None


# --------------------------------------------------------------------------
# Mappning uppgift → händelse (gör omkörningar ofarliga)
# --------------------------------------------------------------------------
class EventMap:
    """
    Lokal mappning `uppgifts-id → Google-händelse-id`.

    Sparas direkt vid varje ändring (samma princip som uppgifterna: det
    som är sparat finns kvar). Gör att en uppgift som skickas två gånger
    **uppdaterar** sin händelse i stället för att skapa en dubblett.
    """

    def __init__(self, path: Any) -> None:
        self.path = Path(str(path))
        self._lock = threading.RLock()
        self._data: Dict[str, str] = {}
        self.load()

    def load(self) -> int:
        with self._lock:
            raw = _read_json(self.path) if _is_file_nonempty(self.path) else None
            poster = (raw or {}).get("tasks")
            if isinstance(poster, dict):
                self._data = {
                    str(k): str(v) for k, v in poster.items() if str(k) and str(v)
                }
            else:
                self._data = {}
            return len(self._data)

    def save(self) -> bool:
        with self._lock:
            try:
                _atomic_write_json(
                    self.path,
                    {"_meta": {"saved_at": _now_iso(), "count": len(self._data)},
                     "tasks": dict(self._data)},
                    mode=0o600,
                )
                return True
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara mappningen: {e}")
                return False

    def get(self, task_id: str) -> Optional[str]:
        with self._lock:
            return self._data.get(str(task_id))

    def set(self, task_id: str, event_id: str) -> None:
        with self._lock:
            self._data[str(task_id)] = str(event_id)
            self.save()

    def pop(self, task_id: str) -> Optional[str]:
        with self._lock:
            gammal = self._data.pop(str(task_id), None)
            if gammal:
                self.save()
            return gammal

    def all(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._data)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"count": len(self._data), "path": str(self.path)}


def load_event_map(data_dir: Any) -> EventMap:
    """Hämta mappningen för den här data-mappen."""
    return EventMap(event_map_path(data_dir))


# --------------------------------------------------------------------------
# Sändningshistorik
# --------------------------------------------------------------------------
class SendHistory:
    """
    Lokal logg över vad som skickats till kalendern (`google/history.json`).

    Varje post: ts, task_id, title, due, action, ok, message, event_id,
    html_link, calendar_id. Äldsta posterna rensas när listan passerar
    HISTORY_MAX_ENTRIES. Innehåller inga hemligheter.
    """

    def __init__(self, path: Any, max_entries: int = HISTORY_MAX_ENTRIES) -> None:
        self.path = Path(str(path))
        self.max_entries = max(10, int(max_entries))
        self._lock = threading.RLock()
        self._items: List[Dict[str, Any]] = []
        self.load()

    def load(self) -> int:
        with self._lock:
            raw = _read_json(self.path) if _is_file_nonempty(self.path) else None
            poster = (raw or {}).get("entries")
            self._items = [e for e in poster if isinstance(e, dict)] \
                if isinstance(poster, list) else []
            return len(self._items)

    def save(self) -> bool:
        with self._lock:
            try:
                _atomic_write_json(
                    self.path,
                    {"_meta": {"saved_at": _now_iso(), "count": len(self._items)},
                     "entries": list(self._items)},
                    mode=0o600,
                )
                return True
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara historiken: {e}")
                return False

    def add(self, entry: Dict[str, Any]) -> None:
        with self._lock:
            post = dict(entry)
            post.setdefault("ts", _now_iso())
            self._items.append(post)
            if len(self._items) > self.max_entries:
                self._items = self._items[-self.max_entries:]
            self.save()

    def all(self) -> List[Dict[str, Any]]:
        """Alla poster, nyaste först."""
        with self._lock:
            return list(reversed(self._items))

    def for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Posterna för en uppgift, nyaste först."""
        tid = str(task_id)
        return [e for e in self.all() if str(e.get("task_id")) == tid]

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items = []
            self.save()
            return n


def load_history(data_dir: Any) -> SendHistory:
    """Hämta historiken för den här data-mappen."""
    return SendHistory(history_path(data_dir))


def calendar_open_url(entry: Dict[str, Any]) -> str:
    """
    Adress som öppnar händelsen i Google Calendar.

    Använder Googles egen länk (`htmlLink`) när den finns; annars dagsvyn för
    förfallodatumet (så knappen alltid tar användaren till rätt dag).
    """
    link = str((entry or {}).get("html_link") or "").strip()
    if link.startswith("https://"):
        return link
    due = str((entry or {}).get("due") or "").strip()
    try:
        d = _date.fromisoformat(due[:10])
        return f"https://calendar.google.com/calendar/r/day/{d.year}/{d.month}/{d.day}"
    except Exception:
        return GOOGLE_CALENDAR_URL


def history_time_text(entry: Dict[str, Any]) -> str:
    """Tidpunkten i lokal tid, t.ex. 2026-10-12 14:03 (tom sträng om okänd)."""
    try:
        t = _datetime.fromisoformat(str((entry or {}).get("ts") or ""))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_timezone.utc)
        return t.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def find_downloaded_credentials(dirs: Optional[List[Any]] = None) -> Optional[Path]:
    """
    Leta efter en nyligen nedladdad klientfil (client_secret*.json) i
    Hämtade filer och returnera den senaste som klarar kontrollen.
    """
    mappar = [Path(str(d)) for d in (dirs or [Path.home() / "Downloads",
                                            Path.home() / "Hämtade filer"])]
    kandidater: List[Path] = []
    for m in mappar:
        try:
            if m.is_dir():
                kandidater.extend(m.glob("client_secret*.json"))
        except Exception:
            continue
    kandidater.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for k in kandidater:
        if validate_credentials_file(k)["ok"]:
            return k
    return None


def history_result_text(entry: Dict[str, Any]) -> str:
    """Kort svensk text för resultatkolumnen i historiken."""
    action = str((entry or {}).get("action") or "")
    if entry.get("ok"):
        return {"skapad": "✅ Skapad", "uppdaterad": "🔄 Uppdaterad"}.get(action, f"✅ {action}")
    msg = str(entry.get("message") or "").splitlines()[0] if entry.get("message") else ""
    if action == "hoppad":
        return f"• Hoppades över — {msg}" if msg else "• Hoppades över"
    return f"✗ Misslyckades — {msg}" if msg else "✗ Misslyckades"


# --------------------------------------------------------------------------
# Skicka uppgifter till kalendern
# --------------------------------------------------------------------------
def push_task(
    service: Any,
    calendar_id: str,
    task: Dict[str, Any],
    event_map: Optional[EventMap] = None,
    color_by_priority: bool = True,
    done_style: str = DEFAULT_DONE_STYLE,
    history: Optional[SendHistory] = None,
) -> Dict[str, Any]:
    """
    Skicka EN uppgift till Google Calendar och för in resultatet i historiken
    (om `history` ges). Se `_push_task_impl` för själva logiken.
    """
    r = _push_task_impl(service, calendar_id, task, event_map,
                        color_by_priority, done_style)
    _record_history(history, calendar_id, task, r)
    return r


def _record_history(
    history: Optional[SendHistory],
    calendar_id: str,
    task: Dict[str, Any],
    r: Dict[str, Any],
) -> None:
    """Skriv en post i historiken (får aldrig fälla sändningen)."""
    if history is None:
        return
    try:
        d = resolve_task_date(task)
        history.add({
            "task_id": str(task.get("id") or ""),
            "title": str(task.get("title") or "").strip(),
            "due": d.isoformat() if d else "",
            "done": bool(task.get("done")),
            "action": r.get("action", ""),
            "ok": bool(r.get("ok")),
            "message": r.get("message", ""),
            "event_id": r.get("event_id", ""),
            "html_link": r.get("html_link", ""),
            "calendar_id": calendar_id,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{LOG_PREFIX} kunde inte skriva historik: {type(e).__name__}")


def _push_task_impl(
    service: Any,
    calendar_id: str,
    task: Dict[str, Any],
    event_map: Optional[EventMap] = None,
    color_by_priority: bool = True,
    done_style: str = DEFAULT_DONE_STYLE,
) -> Dict[str, Any]:
    """
    Skicka EN uppgift till Google Calendar.

    Är uppgiften redan skickad **uppdateras** händelsen (ingen dubblett).
    Om händelsen har tagits bort i Google skapas den på nytt.

    Returnerar {"ok", "action", "event_id", "title", "message"}.
    """
    titel = str(task.get("title") or "").strip()
    task_id = str(task.get("id") or "").strip()
    resultat: Dict[str, Any] = {
        "ok": False, "action": "ingen", "event_id": "", "title": titel, "message": "",
        "html_link": "",
    }

    if resolve_task_date(task) is None:
        resultat["action"] = "hoppad"
        resultat["message"] = "Uppgiften saknar förfallodatum och startdatum."
        return resultat

    try:
        body = build_event_body(task, calendar_id, color_by_priority=color_by_priority,
                                done_style=done_style)
    except GoogleCalendarError as e:
        resultat["action"] = "hoppad"
        resultat["message"] = e.user_message
        return resultat

    # 1. Känd sedan tidigare?
    event_id = event_map.get(task_id) if event_map else None

    # 2. Annars: fråga Google (märket i händelsen) — t.ex. efter ominstallation
    if not event_id and task_id:
        event_id = search_event_by_task(service, calendar_id, task_id)
        if event_id and event_map:
            event_map.set(task_id, event_id)
            logger.info(f"{LOG_PREFIX} hittade befintlig händelse för '{titel[:30]}'")

    if event_id:
        try:
            # null i PATCH tar bort fältet: en uppgift som inte längre är klar
            # får tillbaka sin vanliga färg i stället för att fastna på grått.
            patch_body = dict(body)
            patch_body.setdefault("colorId", None)
            svar = patch_event(service, calendar_id, event_id, patch_body)
            if event_map:
                event_map.set(task_id, svar.get("id") or event_id)
            resultat.update({
                "ok": True, "action": "uppdaterad",
                "event_id": svar.get("id") or event_id,
                "html_link": svar.get("htmlLink", ""),
                "message": "Händelsen fanns redan och uppdaterades.",
            })
            return resultat
        except GoogleCalendarError as e:
            # Bara "finns inte kvar" (404/410) betyder att vi ska skapa på nytt.
            # Andra fel (401, 403, nätverk …) skulle annars ge en dubblett.
            tekniskt = e.technical or ""
            borttagen = any(k in tekniskt for k in ("404", "410", "Not Found", "Gone")) \
                or "finns inte kvar" in e.user_message \
                or "borttagen" in e.user_message
            if not borttagen:
                resultat["message"] = e.user_message
                return resultat
            logger.info(
                f"{LOG_PREFIX} händelsen finns inte kvar hos Google "
                f"({tekniskt[:80]}) — skapar den på nytt"
            )
            if event_map:
                event_map.pop(task_id)
            try:
                svar = create_event(service, calendar_id, body)
            except GoogleCalendarError as e2:
                resultat["message"] = e2.user_message
                return resultat
            if event_map and task_id:
                event_map.set(task_id, svar.get("id") or "")
            resultat.update({
                "ok": True, "action": "skapad", "event_id": svar.get("id") or "",
                "html_link": svar.get("htmlLink", ""),
                "message": "Händelsen hade tagits bort i Google — skapade den på nytt.",
            })
            return resultat

    # 3. Ny händelse
    try:
        svar = create_event(service, calendar_id, body)
    except GoogleCalendarError as e:
        resultat["message"] = e.user_message
        return resultat
    if event_map and task_id:
        event_map.set(task_id, svar.get("id") or "")
    resultat.update({
        "ok": True, "action": "skapad", "event_id": svar.get("id") or "",
        "html_link": svar.get("htmlLink", ""),
        "message": "Ny händelse skapad i kalendern.",
    })
    return resultat


def push_tasks(
    service: Any,
    calendar_id: str,
    tasks: List[Dict[str, Any]],
    event_map: Optional[EventMap] = None,
    color_by_priority: bool = True,
    done_style: str = DEFAULT_DONE_STYLE,
    history: Optional[SendHistory] = None,
) -> Dict[str, Any]:
    """
    Skicka flera uppgifter. Returnerar sammanställning + resultat per uppgift.

    En uppgift som strular stoppar inte de andra.
    """
    resultat: List[Dict[str, Any]] = []
    skapade = uppdaterade = hoppade = misslyckade = 0

    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        try:
            r = push_task(service, calendar_id, task, event_map,
                          color_by_priority, done_style, history)
        except Exception as e:  # noqa: BLE001 - en uppgift får inte fälla resten
            r = {
                "ok": False, "action": "fel", "event_id": "", "html_link": "",
                "title": str(task.get("title") or ""),
                "message": to_user_error(e).user_message,
            }
            _record_history(history, calendar_id, task, r)
        resultat.append(r)
        if not r["ok"]:
            if r["action"] == "hoppad":
                hoppade += 1
            else:
                misslyckade += 1
        elif r["action"] == "skapad":
            skapade += 1
        else:
            uppdaterade += 1

    sammanstallning = {
        "total": len(resultat),
        "skapade": skapade,
        "uppdaterade": uppdaterade,
        "hoppade": hoppade,
        "misslyckade": misslyckade,
        "results": resultat,
    }
    logger.info(
        f"{LOG_PREFIX} sändning klar: {skapade} skapade, {uppdaterade} uppdaterade, "
        f"{hoppade} hoppade (utan datum), {misslyckade} misslyckades"
    )
    return sammanstallning


def describe_tasks_for_picker(
    tasks: List[Dict[str, Any]],
    event_map: Optional[EventMap] = None,
) -> List[Dict[str, Any]]:
    """
    Underlag till uppgiftsväljaren: användaren väljer själv vad som skickas.

    Varje rad får: id, title, due (ISO eller ""), priority, sent (redan
    skickad tidigare), sendable (har datum) och reason (varför den inte
    går att välja). Ordningen från `tasks` behålls.
    """
    rader: List[Dict[str, Any]] = []
    for t in tasks or []:
        if not isinstance(t, dict) or not str(t.get("title") or "").strip():
            continue
        dagar = resolve_task_dates(t)
        d = dagar[0] if dagar else None
        tid = str(t.get("id") or "").strip()
        rader.append({
            "id": tid,
            "title": str(t.get("title")).strip(),
            "due": d.isoformat() if d else "",
            # Visningstext: en dag, eller "start → slut" för flerdagarshändelser
            "span": (d.isoformat() if dagar[0] == dagar[1]
                     else f"{dagar[0].isoformat()} → {dagar[1].isoformat()}") if dagar else "",
            "priority": str(t.get("priority") or "none").lower(),
            "sent": bool(event_map and tid and event_map.get(tid)),
            "done": bool(t.get("done")),
            "sendable": d is not None,
            "reason": "" if d is not None else "saknar förfallodatum/startdatum",
            "task": t,
        })
    return rader


def select_tasks_by_ids(
    tasks: List[Dict[str, Any]],
    chosen_ids: List[str],
) -> List[Dict[str, Any]]:
    """Bara de uppgifter användaren valt (ordningen från `tasks` behålls)."""
    valda = {str(i) for i in (chosen_ids or [])}
    return [t for t in tasks or []
            if isinstance(t, dict) and str(t.get("id") or "") in valda]


def summarize(resultat: Dict[str, Any]) -> str:
    """Kort svensk sammanfattning av en sändning (för dialogrutan)."""
    if not isinstance(resultat, dict):
        return "Ingenting skickades."
    delar = [
        f"{resultat.get('skapade', 0)} nya händelser",
        f"{resultat.get('uppdaterade', 0)} uppdaterade",
    ]
    if resultat.get("hoppade"):
        delar.append(f"{resultat['hoppade']} utan förfallodatum/startdatum")
    if resultat.get("misslyckade"):
        delar.append(f"⚠ {resultat['misslyckade']} misslyckades")
    return ", ".join(delar) + "."


# --------------------------------------------------------------------------
# Självtest (körs med: python core/google_calendar.py)
# --------------------------------------------------------------------------
def _selftest() -> int:
    """Snabbkontroll utan nätverk: paket, bygge av händelsedata, mappning."""
    print("=" * 66)
    print("SJÄLVTEST: core/google_calendar.py")
    print("=" * 66)
    fel = 0

    print(f"\nGoogle-paket: {'✓ installerade' if is_google_library_available() else '✗ saknas'}")
    if missing_packages():
        print(f"  kör: {install_hint()}")
    print(f"Behörigheter som begärs ({len(SCOPES)}):")
    for s in SCOPES:
        print(f"  • {s.split('/auth/')[-1]}")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        print(f"\nDatamapp: {d}")
        print(f"  credentials → {credentials_path(d).relative_to(d)}")
        print(f"  token       → {token_path(d).relative_to(d)}")

        st = get_status(d)
        print(f"\nStatus utan filer: {st['label']} (state={st['state'].value})")
        if st["state"] not in (ConnectionStatus.NOT_CONFIGURED, ConnectionStatus.NO_LIBRARY):
            print("  ✗ fel status"); fel += 1

        # händelsedata
        task = {
            "id": "abc123", "title": "Betala fakturan", "due_date": "2026-10-20",
            "priority": "high", "tags": ["jobb"],
            "subtasks": [{"title": "Hämta underlag", "done": False}],
        }
        body = build_event_body(task)
        print(f"\nHändelse: {body['summary']!r}")
        print(f"  start/end : {body['start']['date']} → {body['end']['date']}")
        print(f"  colorId   : {body.get('colorId')} (hög prioritet)")
        print(f"  märke     : {body['extendedProperties']['private'][EVENT_TAG_KEY]}")
        ok, feltext = validate_event_data(body)
        if not ok:
            print(f"  ✗ validering: {feltext}"); fel += 1

        if (body["end"]["date"] != "2026-10-21") or (body["start"]["date"] != "2026-10-20"):
            print("  ✗ heldagsdatum fel"); fel += 1

        # mappning
        em = load_event_map(d)
        em.set("abc123", "google_event_1")
        em2 = load_event_map(d)
        print(f"\nMappning: {em2.stats()}")
        if em2.get("abc123") != "google_event_1":
            print("  ✗ mappningen sparades inte"); fel += 1
        em2.pop("abc123")
        if load_event_map(d).get("abc123") is not None:
            print("  ✗ mappningen togs inte bort"); fel += 1

        # felöversättning
        class _E(Exception):
            def __init__(self, status: int) -> None:
                super().__init__(f"HTTP {status}")
                self.status_code = status

        print("\nFelöversättning:")
        for s in (401, 403, 404, 429):
            rad = handle_http_error(_E(s)).splitlines()[0]
            print(f"  {s}: {rad}")
        print(f"  tillfälligt (429): {is_transient_error(_E(429))} | (400): {is_transient_error(_E(400))}")

        # retry-logik (utan att vänta på riktigt)
        försök = {"n": 0}
        sov: List[float] = []

        def _flaky() -> str:
            försök["n"] += 1
            if försök["n"] < 3:
                raise _E(503)
            return "klar"

        svar = with_retry(_flaky, sleep=sov.append)
        print(f"\nRetry: svar={svar!r} efter {försök['n']} försök, väntetider={[round(x, 2) for x in sov]}")
        if svar != "klar" or försök["n"] != 3 or len(sov) != 2:
            print("  ✗ retry-logiken fel"); fel += 1

    print("\n" + "=" * 66)
    print("✓ SJÄLVTESTET KLART" if fel == 0 else f"✗ {fel} fel")
    print("=" * 66)
    return 1 if fel else 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_selftest())
