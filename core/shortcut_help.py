# -*- coding: utf-8 -*-
"""
shortcut_help.py — innehållet i tangentöversikten (F1): alla tangenter och snabbkommandon,
med användarens egna inställningar. Ingen Qt behövs (testas utan fönster).

``build_sections(settings)`` → [(rubrik, [(tangent, vad den gör), …]), …]
``as_html`` / ``as_text`` formaterar det för dialogen respektive "Kopiera som text".
"""
from __future__ import annotations

import html
import sys
from typing import Any, Dict, List, Optional, Tuple

Section = Tuple[str, List[Tuple[str, str]]]

# Fönsterkommandon från inställningarna som har en funktion i fönstret (resten har ingen hanterare)
_WINDOW_ACTIONS: Dict[str, str] = {
    "add_task": "Lägg till uppgiften i inmatningsfältet",
    "toggle_visible": "Lägg fönstret på rätt nivå igen",
    "open_search": "Gå till sökfältet",
    "next_task": "Markera nästa uppgift",
    "prev_task": "Markera föregående uppgift",
    "edit_task": "Ändra titeln på den markerade uppgiften",
}

_LIST_KEYS: List[Tuple[str, str]] = [
    ("↓ / ↑", "Markera nästa / föregående uppgift (↑ på den första går till inmatningsfältet)"),
    ("Home / End, PgUp / PgDn", "Första / sista uppgiften, 5 steg"),
    ("Mellanslag", "Markera klar (en klar uppgift flyttas till historiken)"),
    ("E eller F2", "Ändra titeln direkt på kortet (Enter sparar, Esc avbryter)"),
    ("P", "Fäst / lossa uppgiften överst"),
    ("1 / 2 / 3 / 0", "Prioritet hög / normal / låg / ingen"),
    ("Delete", "Ta bort uppgiften (frågar först; arkiverade uppgifter kan inte tas bort)"),
    ("Esc", "Lämna listan och gå tillbaka till inmatningsfältet"),
    ("Vanlig text", "Hamnar i inmatningsfältet"),
]

_FOCUS_KEYS: List[Tuple[str, str]] = [
    ("F3", "Fokusläge på / av (en uppgift i taget)"),
    ("← / →", "Föregående / nästa uppgift i fokusläget"),
    ("Enter / Mellanslag", "Markera klar i fokusläget"),
    ("Esc", "Lämna fokusläget"),
]

_MOUSE: List[Tuple[str, str]] = [
    ("Klick på ett kort", "Markerar uppgiften (och gör tangenterna ovan aktiva)"),
    ("Dubbelklick på titeln", "Ändra titeln direkt på kortet"),
    ("Högerklick på ett kort", "Åtgärder: klar, prioritet, datum, delmoment, länkar och bilagor, ta bort …"),
    ("Högerklick på fönstret", "Fönstermenyn: Alltid överst, lås, centrera, export, backup …"),
    ("Dra fönstret mot en kant", "Släpp nära vänster/höger/övre skärmkanten → fönstret glider ut och kommer tillbaka när musen nuddar kanten"),
    ("Klick på en tagg", "Filtrerar listan på taggen"),
    ("🔗 / 📎 på ett kort", "Öppnar länken i webbläsaren / bilagan i sitt program (högerklick: fler val)"),
]


def _combo(settings: Any, getter: str, default: str) -> str:
    try:
        v = str(getattr(settings, getter)() or "").strip()
    except Exception:
        v = ""
    return v or default


def _enabled(settings: Any, getter: str) -> bool:
    try:
        return bool(getattr(settings, getter)())
    except Exception:
        return True


def build_sections(settings: Any = None, platform: Optional[str] = None) -> List[Section]:
    """Alla tangenter, med de kombinationer användaren valt. ``platform`` = sys.platform (för test)."""
    plat = platform or sys.platform
    sections: List[Section] = []

    # --- Globala snabbtangenter (bara Windows) -------------------------------------------
    if plat == "win32":
        clip_on = _enabled(settings, "clip_task_enabled")
        top_on = _enabled(settings, "top_toggle_enabled")
        glob = [
            (_combo(settings, "quick_add_hotkey", "Ctrl+Alt+N"), "Ny uppgift från var som helst (snabbinmatning)"),
            (_combo(settings, "push_show_hotkey", "Ctrl+Alt+V"), "Visa fönstret så länge du håller tangenten"),
            (_combo(settings, "clip_task_hotkey", "Ctrl+Alt+K") + ("" if clip_on else "  (av)"),
             "Gör markerad text (eller urklipp) till en uppgift"),
            (_combo(settings, "top_toggle_hotkey", "Ctrl+Alt+T") + ("" if top_on else "  (av)"),
             "Alltid överst på / av"),
        ]
        sections.append(("🌐 Globala snabbtangenter (fungerar i alla program)", glob))
    else:
        sections.append(("🌐 Globala snabbtangenter",
                         [("—", "Finns bara i Windows. Använd tray-menyn eller högerklicka på fönstret "
                                "(📌 Alltid överst) på macOS och Linux.")]))

    # --- Fönstrets tangenter (när fönstret är aktivt) --------------------------------------
    win: List[Tuple[str, str]] = [("F1", "Den här översikten"), ("F3", "Fokusläge på / av")]
    try:
        sc = dict(settings.shortcuts()) if settings is not None else {}
    except Exception:
        sc = {}
    for action, text in _WINDOW_ACTIONS.items():
        seq = str(sc.get(action) or "").strip()
        if seq and seq.upper() != "F1":
            win.append((seq, text))
    sections.append(("🪟 När fönstret är aktivt (klicka i det först)", win))
    sections.append(("⌨️ Styra listan (när en uppgift är markerad)", list(_LIST_KEYS)))
    sections.append(("🎯 Fokusläge (F3)", list(_FOCUS_KEYS)))
    sections.append(("🖱️ Musen", list(_MOUSE)))
    return sections


def as_text(sections: List[Section]) -> str:
    """Ren text (för 'Kopiera som text')."""
    out: List[str] = []
    for title, rows in sections:
        out.append(title)
        w = max((len(k) for k, _ in rows), default=0)
        for k, v in rows:
            out.append(f"  {k.ljust(w)}  {v}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def as_html(sections: List[Section]) -> str:
    """HTML utan egna färger — ärver dialogens text- och bakgrundsfärg (alltid läsbar)."""
    parts: List[str] = []
    for title, rows in sections:
        parts.append(f"<h3 style='margin-bottom:2px'>{html.escape(title)}</h3>")
        parts.append("<table cellspacing='0' cellpadding='3' width='100%'>")
        for k, v in rows:
            parts.append(
                f"<tr><td width='34%' valign='top'><b>{html.escape(k)}</b></td>"
                f"<td valign='top'>{html.escape(v)}</td></tr>"
            )
        parts.append("</table>")
    return "".join(parts)
