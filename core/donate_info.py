# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
donate_info.py — donationsmottagare för Ledgebord, LÅSTA (stdlib, ingen Qt).

Mottagarna står bara här — de läses aldrig ur inställningar, datafiler eller miljövariabler, och det finns ingen
dialogruta där man kan ändra dem. Dessutom kontrolleras en SHA-256-kontrollsumma (``las_ok``) varje gång stöddialogen
öppnas: har mottagarna ändrats i en lokal kopia av filen avaktiveras betalknapparna och dialogen varnar, så ingen
skickar pengar till fel mottagare av misstag. ``core/updater.py`` jämför filernas innehåll mot releasen och lägger
tillbaka den ursprungliga filen vid nästa uppdateringskontroll.

Ärlig gräns: Ledgebord är öppen källkod (MIT) — den som själv ändrar koden och kontrollsumman kan förstås göra en egen
version. Låset skyddar mot oavsiktliga/tysta ändringar och mot att inställningar eller datafiler styr om betalningar.

Ändra mottagare (bara ägaren): redigera konstanterna nedan och kör ``python core/donate_info.py`` — skriv sedan in den
utskrivna kontrollsumman i ``_LAS_HASH``. Swish är standard: QR-koden visas direkt i dialogen (numret visas aldrig som text).
"""
from __future__ import annotations

import hashlib
import re
from typing import Final, Tuple
from urllib.parse import quote

PAYPAL_BAS: Final[str] = "https://paypal.me/Rickard3dPrint"
KOFI_URL: Final[str] = "https://ko-fi.com/tokke2"
SWISH_NUMMER: Final[str] = "0721817177"  # visas ALDRIG som text i appen — bara inbakat i QR-koden
SWISH_MEDDELANDE: Final[str] = "Ledgebord"

BELOPP_VAL: Final[Tuple[int, ...]] = (25, 50, 100, 200)
BELOPP_STANDARD: Final[int] = 50
BELOPP_MIN: Final[int] = 1
BELOPP_MAX: Final[int] = 99_999

_LAS_HASH: Final[str] = "10745a5601e42d246df0b8c0bb318f610f81c96c1abb243f5d10afa184221777"


def las_sträng() -> str:
    """Det som kontrollsumman gäller: alla mottagare i en bestämd ordning."""
    return "|".join((PAYPAL_BAS, KOFI_URL, SWISH_NUMMER, SWISH_MEDDELANDE))


def las_hash() -> str:
    return hashlib.sha256(las_sträng().encode("utf-8")).hexdigest()


def las_ok() -> bool:
    """True om mottagarna är oförändrade sedan kontrollsumman skrevs."""
    return las_hash() == _LAS_HASH


def clamp_belopp(v) -> int:
    """Gör om ett inmatat värde till ett heltal inom BELOPP_MIN…BELOPP_MAX (standard vid skräp)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return BELOPP_STANDARD
    return max(BELOPP_MIN, min(BELOPP_MAX, n))


def paypal_url(kr: int) -> str:
    return f"{PAYPAL_BAS}/{clamp_belopp(kr)}SEK"


def kofi_url() -> str:
    return KOFI_URL


def swish_nummer() -> str:
    return re.sub(r"\D", "", SWISH_NUMMER)


def swish_aktiv() -> bool:
    return 7 <= len(swish_nummer()) <= 15


def swish_payload(kr: int) -> str:
    """Swishs officiella QR-format: ``C<nummer>;<belopp>;<meddelande>;<mask>`` (mask 6 = belopp och meddelande kan
    ändras i appen, numret är låst). Läses av Swish-appens skanner."""
    return f"C{swish_nummer()};{clamp_belopp(kr)};{quote(SWISH_MEDDELANDE)};6"


if __name__ == "__main__":
    print("kontrollsumma (skriv in i _LAS_HASH):", las_hash())
    print("nuvarande läge:", "OK" if las_ok() else "ÄNDRAD (hash stämmer inte)")
