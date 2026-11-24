#!/usr/bin/env python3
"""
gcal_token_protect_test.py — Googles åtkomstbevis sparas som lokal, krypterad nyckelfil (Windows DPAPI).

DPAPI själv finns bara på Windows, så testet byter ut den mot en reversibel låtsas-kryptering och
kontrollerar allt runt omkring: filformat, att klartexten inte ligger i filen, läsning, migrering av
gamla klartext-tokens, reserv vid fel och att en nyckel för "ett annat konto" inte går att använda.

Kör:  python tester/gcal_token_protect_test.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from core import google_calendar as g  # noqa: E402

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


SECRET = "1//refresh-SECRET-xyz"
INFO = {"token": "ya29.access", "refresh_token": SECRET, "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "cs", "token_uri": "https://oauth2.googleapis.com/token", "scopes": list(g.SCOPES), "expiry": "2099-01-01T00:00:00Z"}


class FakeCreds:
    def to_json(self):
        return json.dumps(INFO)


USER = {"name": "rickard"}


def fake_crypt(data: bytes, encrypt: bool) -> bytes:
    """Låtsas-DPAPI: knuten till 'användaren' (fel användare → fel)."""
    if encrypt:
        return USER["name"].encode() + b"|" + bytes(b ^ 0x5A for b in data)
    owner, _, body = data.partition(b"|")
    if owner.decode() != USER["name"]:
        raise OSError("fel konto")
    return bytes(b ^ 0x5A for b in body)


tmp = Path(tempfile.mkdtemp(prefix="taskbord_tok_"))

# --- Windows-läge (låtsas-DPAPI) --------------------------------------------------------
g._dpapi_supported = lambda: True
g._dpapi_crypt = fake_crypt
p = g.save_token(FakeCreds(), tmp)
text = p.read_text(encoding="utf-8")
raw = json.loads(text)
check("token.json skapas i datamappen", p == g.token_path(tmp) and p.is_file() and p.parent.name == "google")
check("filen är markerad som krypterad", raw.get(g.TOKEN_PROTECT_KEY) == g.TOKEN_PROTECT_SCHEME)
check("refresh-token ligger INTE i klartext i filen", SECRET not in text and "ya29" not in text)
check("is_token_protected → True", g.is_token_protected(p))
check("filen är giltig JSON med 'data'", bool(raw.get("data")) and base64.b64decode(raw["data"]))
check("roundtrip: unprotect ger tillbaka nycklarna", (g.unprotect_token_info(raw) or {}).get("refresh_token") == SECRET)

if g.is_google_library_available():
    c = g.load_credentials(tmp, allow_refresh=False)
    check("load_credentials läser den krypterade filen", c is not None and c.refresh_token == SECRET)
else:
    print("  (google-paketen saknas — hoppar över load_credentials)")

# --- fel konto / annan dator ------------------------------------------------------------
USER["name"] = "någon-annan"
check("annat konto kan inte dekryptera", g.unprotect_token_info(raw) is None)
if g.is_google_library_available():
    check("annat konto: load_credentials → None (inte kopplad)", g.load_credentials(tmp, allow_refresh=False) is None)
USER["name"] = "rickard"

# --- gammal klartext-token migreras ------------------------------------------------------
p.write_text(json.dumps(INFO), encoding="utf-8")
check("klartext-token är inte 'skyddad'", not g.is_token_protected(p))
check("klartext-token läses som förut", g.unprotect_token_info(json.loads(p.read_text())) == INFO)
if g.is_google_library_available():
    c = g.load_credentials(tmp, allow_refresh=False)
    check("klartext-token fungerar fortfarande", c is not None)
    check("…och krypteras vid första läsningen", g.is_token_protected(p) and SECRET not in p.read_text())

# --- krypteringen kraschar → inloggningen förloras inte -----------------------------------
def boom(data, encrypt):
    raise OSError("DPAPI otillgängligt")

g._dpapi_crypt = boom
p2 = g.save_token(FakeCreds(), tmp)
check("krypteringsfel: token sparas ändå (klartext, 0600)", not g.is_token_protected(p2) and SECRET in p2.read_text())

# --- annat system än Windows: oförändrat beteende -----------------------------------------
g._dpapi_supported = lambda: False
g._dpapi_crypt = fake_crypt
p3 = g.save_token(FakeCreds(), tmp)
check("icke-Windows: klartext med 0600", not g.is_token_protected(p3))
if os.name == "posix":
    check("icke-Windows: filrättigheter 0600", (p3.stat().st_mode & 0o777) == 0o600)

# --- koden ska vara säker att läsa på Windows --------------------------------------------
src = (ROOT / "core/google_calendar.py").read_text(encoding="utf-8")
check("DPAPI-koden använder CRYPTPROTECT_UI_FORBIDDEN och frigör minnet", "0x1" in src and "LocalFree" in src)
check("nyckelfilen stannar i appens google-mapp", "token_path" in src and "APPDATA" not in src.split("def _dpapi_crypt")[0][-3000:])

print(f"\ngcal_token_protect_test: {_ok} lyckades, {_fail} misslyckades")
sys.stdout.flush()
os._exit(1 if _fail else 0)
