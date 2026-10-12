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
TOKEN_FILENAME: str = "token.json"
ACCOUNT_FILENAME: str = "account.json"
EVENT_MAP_FILENAME: str = "event_map.json"

# Private-märke på varje händelse → vi hittar tillbaka till uppgiften
# även om mappningen skulle tappas (t.ex. ominstallation).
EVENT_TAG_KEY: str = "taskbord_id"
EVENT_SOURCE_VALUE: str = "taskbord"

# Google-färger per prioritet (11 = Tomat/röd, 5 = Banan/gul, 10 = Basilika/grön)
COLOR_BY_PRIORITY: Dict[str, str] = {"high": "11", "medium": "5", "low": "10"}

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
    _atomic_write_json(path, data, mode=0o600)
    logger.info(
        f"{LOG_PREFIX} token sparad lokalt: {path} "
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
        creds = Credentials.from_authorized_user_file(str(token_file), list(SCOPES))
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


def resolve_task_date(task: Dict[str, Any]) -> Optional[_date]:
    """Datumet en uppgift ska hamna på (delas med .ics-exporten)."""
    try:
        from core.calendar_export import parse_due_date
        return parse_due_date(task.get("due_date"))
    except Exception:
        pass
    # Reserv: enkel ISO-tolkning om calendar_export inte kan importeras
    s = str((task or {}).get("due_date") or "").strip()
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


def build_event_body(
    task: Dict[str, Any],
    calendar_id: str = DEFAULT_CALENDAR_ID,
    color_by_priority: bool = True,
) -> Dict[str, Any]:
    """
    Bygg Google-händelsen för en uppgift (heldagshändelse på förfallodatumet).

    Händelsen märks med uppgiftens id i `extendedProperties`, så att vi
    alltid kan hitta tillbaka till den — även om mappningen på disk
    skulle försvinna.
    """
    titel = str(task.get("title") or "").strip()
    d = resolve_task_date(task)
    if not titel or d is None:
        raise GoogleCalendarError(
            "Uppgiften behöver en titel och ett förfallodatum för att bli "
            "en kalenderhändelse."
        )

    body: Dict[str, Any] = {
        "summary": titel,
        "start": {"date": d.isoformat()},
        "end": {"date": (d + _timedelta(days=1)).isoformat()},
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
# Skicka uppgifter till kalendern
# --------------------------------------------------------------------------
def push_task(
    service: Any,
    calendar_id: str,
    task: Dict[str, Any],
    event_map: Optional[EventMap] = None,
    color_by_priority: bool = True,
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
    }

    if resolve_task_date(task) is None:
        resultat["action"] = "hoppad"
        resultat["message"] = "Uppgiften saknar förfallodatum."
        return resultat

    try:
        body = build_event_body(task, calendar_id, color_by_priority=color_by_priority)
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
            svar = patch_event(service, calendar_id, event_id, body)
            if event_map:
                event_map.set(task_id, svar.get("id") or event_id)
            resultat.update({
                "ok": True, "action": "uppdaterad",
                "event_id": svar.get("id") or event_id,
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
        "message": "Ny händelse skapad i kalendern.",
    })
    return resultat


def push_tasks(
    service: Any,
    calendar_id: str,
    tasks: List[Dict[str, Any]],
    event_map: Optional[EventMap] = None,
    color_by_priority: bool = True,
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
            r = push_task(service, calendar_id, task, event_map, color_by_priority)
        except Exception as e:  # noqa: BLE001 - en uppgift får inte fälla resten
            r = {
                "ok": False, "action": "fel", "event_id": "",
                "title": str(task.get("title") or ""),
                "message": to_user_error(e).user_message,
            }
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
        d = resolve_task_date(t)
        tid = str(t.get("id") or "").strip()
        rader.append({
            "id": tid,
            "title": str(t.get("title")).strip(),
            "due": d.isoformat() if d else "",
            "priority": str(t.get("priority") or "none").lower(),
            "sent": bool(event_map and tid and event_map.get(tid)),
            "sendable": d is not None,
            "reason": "" if d is not None else "saknar förfallodatum",
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
        delar.append(f"{resultat['hoppade']} utan förfallodatum")
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
