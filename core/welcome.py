# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
welcome.py — välkomstguiden vid första start (ren logik, ingen Qt).

* Visas EN gång, bara på en ny installation (inga uppgifter alls) och bara när fönstret syns (inte vid tyst autostart).
* En exempeluppgift läggs in som visar hur kortet fungerar — den kan bockas av eller tas bort som vilken uppgift som helst.
* Den som redan har uppgifter (uppdatering från äldre version) får aldrig guiden uppdragen — den markeras bara som klar.
* Guiden kan alltid öppnas igen: tray-menyn och högerklicksmenyn → 👋 Välkomstguide.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

SHOW = "show"
MARK_ONLY = "mark_only"
SKIP = "skip"

EXAMPLE_TITLE = "👋 Välkommen! Bocka av mig med ✓ när du vill"
EXAMPLE_NOTE = (
    "Det här är en exempeluppgift — du kan bocka av den (✓), redigera den (F2) eller ta bort den (Delete).\n\n"
    "• Skriv en ny uppgift i fältet längst ned och tryck Enter.\n"
    "• Skriv gärna som du tänker: Ring Anna fre 14 kl 9 !hög #jobb\n"
    "• Högerklicka en uppgift för fler val: datum, tagg, belopp, anteckning, bilagor.\n"
    "• Ctrl+Alt+N lägger till en uppgift från vilket program som helst."
)

TIPS: List[Tuple[str, str, str]] = [
    ("✍️", "Skriv och tryck Enter", "Ny uppgift i fältet längst ned. Skriv som du tänker: Ring Anna fre 14 kl 9 !hög #jobb."),
    ("⌨️", "Ctrl+Alt+N var som helst", "Lägg till en uppgift från vilket program som helst — Ledgebord behöver inte vara synligt."),
    ("🖱", "Högerklicka en uppgift", "Datum, taggar, belopp, anteckning, bilagor och mer. Dubbelklicka på titeln för att ändra den."),
    ("🔔", "Påminnelser", "Ledgebord påminner tills uppgiften är klar — tyst på natten (🌙 i tray-menyn)."),
    ("🗕", "✕ gömmer bara fönstret", "Appen ligger kvar vid klockan. Avsluta via tray-menyn eller högerklick → ❌ Avsluta."),
    ("📧", "Mail till uppgift", "Högerklicka ett mail i Thunderbird → Ledgebord (se MANUAL.md)."),
    ("⌨️", "F1 visar alla tangenter", "Där finns också stöd-knappen om du vill stödja projektet."),
]

EMPTY_ACTIVE = (
    "✨  Inga uppgifter ännu\n\n"
    "✍️  Skriv nedan och tryck Enter — t.ex.  Ring Anna fre 14 kl 9 !hög #jobb\n"
    "⌨️  Ctrl+Alt+N lägger till från vilket program som helst\n"
    "🖱  Högerklicka en uppgift för datum, tagg, belopp och bilagor\n"
    "👋  Högerklicka fönstret → Välkomstguide  ·  F1 = alla tangenter"
)
EMPTY_ARCHIVE = "🗄️  Inga arkiverade uppgifter\nKlara uppgifter hamnar här och sparas för alltid"


def decide(n_active: int, n_archived: int, welcome_done: bool, visible: bool) -> str:
    """SHOW = visa guiden + lägg in exempeluppgift · MARK_ONLY = markera som klar utan att visa · SKIP = gör ingenting nu."""
    if welcome_done:
        return SKIP
    if n_active > 0 or n_archived > 0:
        return MARK_ONLY            # befintlig användare (uppdatering) — aldrig uppdragen guide
    if not visible:
        return SKIP                 # tyst autostart: vänta tills fönstret syns
    return SHOW


def example_task() -> Dict[str, object]:
    return {"title": EXAMPLE_TITLE, "priority": "medium", "tags": ["exempel"], "note": EXAMPLE_NOTE}
