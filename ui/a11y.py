# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
a11y.py — tillgänglighet: synliga fokusringar, namn för skärmläsare och textstorlek upp till 200 %.

* ``focus_qss`` — tydlig ring runt det som har tangentbordsfokus (knappar, fält, flikar, rutor). Gul på mörkt,
  mörkblå på ljust, kraftigare i högkontrastläge.
* ``describe_task`` — den mening en skärmläsare läser för ett uppgiftskort ("Uppgift: Ring Anna. Hög prioritet.
  Förfaller 2026-11-20. Ej klar. Taggar: jobb.").
* ``clean_label`` / ``name_for`` / ``apply_names`` — ger varje knapp/fält ett läsbart namn (emoji tas bort ur namnet;
  verktygstipset används när knappen bara har en symbol).
* ``ZOOM_STEPS`` / ``next_zoom`` — Ctrl+Plus / Ctrl+Minus / Ctrl+0 (80–200 %).
Ren logik utan Qt-import i toppen (Qt hämtas bara i ``apply_names``).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

ZOOM_STEPS: List[int] = [80, 90, 100, 110, 125, 150, 175, 200]
ZOOM_MIN, ZOOM_MAX = ZOOM_STEPS[0], ZOOM_STEPS[-1]

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002190-\U000021FF\U00002300-\U000023FF\U00002460-\U000027BF\U00002900-\U0000297F"
    "\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U000020E3]+"
)
_PRIO = {"high": "Hög prioritet", "medium": "Normal prioritet", "low": "Låg prioritet"}


def clean_label(text: Any) -> str:
    """Text utan emoji/symboler och med enkla blanksteg (”📝  Ny anteckning” → ”Ny anteckning”)."""
    s = _EMOJI.sub(" ", str(text or ""))
    s = s.replace("&", "")
    return re.sub(r"\s+", " ", s).strip(" :·-–—…")


def next_zoom(current: int, direction: int) -> int:
    """Nästa steg uppåt (+1) eller nedåt (-1); 0 = tillbaka till 100 %."""
    if direction == 0:
        return 100
    cur = max(ZOOM_MIN, min(ZOOM_MAX, int(current)))
    if direction > 0:
        return next((z for z in ZOOM_STEPS if z > cur), ZOOM_MAX)
    return next((z for z in reversed(ZOOM_STEPS) if z < cur), ZOOM_MIN)


def focus_ring_color(is_dark: bool, high_contrast: bool) -> str:
    if high_contrast:
        return "#ffeb3b" if is_dark else "#0000a0"
    return "#fde047" if is_dark else "#1d4ed8"


def focus_qss(t: Dict[str, str], is_dark: bool, accent_hex: str, high_contrast: bool = False) -> str:
    """QSS som ritar en tydlig ring (2–3 px) runt allt som har tangentbordsfokus."""
    ring = focus_ring_color(is_dark, high_contrast)
    w = 3 if high_contrast else 2
    return (
        f"QPushButton:focus, QToolButton:focus, QComboBox:focus, QSpinBox:focus {{ border: {w}px solid {ring}; }} "
        f"QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: {w}px solid {ring}; }} "
        f"QCheckBox:focus, QRadioButton:focus {{ border: {w}px solid {ring}; border-radius: 6px; }} "
        f"QTabBar::tab:focus {{ border: {w}px solid {ring}; }} "
        + (
            f'QFrame[taskCard="true"][taskSelected="true"], QFrame[taskCard="true"][taskSelected="true"]:hover '
            f"{{ border: 3px solid {ring}; }} " if high_contrast else ""
        )
    )


def describe_task(task: Dict[str, Any], archived: bool = False) -> str:
    """Läsbar mening för skärmläsare."""
    parts = [f"Uppgift: {clean_label(task.get('title')) or str(task.get('title') or '').strip() or 'utan titel'}"]
    pr = _PRIO.get(str(task.get("priority") or ""))
    if pr:
        parts.append(pr)
    due = str(task.get("due_date") or "")[:16].replace("T", " kl ")
    if due:
        parts.append(f"Förfaller {due}")
    parts.append("Klar" if task.get("done") or archived else "Ej klar")
    tags = [str(x) for x in (task.get("tags") or []) if str(x).strip()]
    if tags:
        parts.append("Taggar: " + ", ".join(tags[:6]))
    if task.get("amount_cents"):
        parts.append(f"Belopp {int(task['amount_cents']) // 100} kronor")
    return ". ".join(parts) + "."


def name_for(widget: Any) -> str:
    """Bästa namnet för en knapp/ruta/fält: egen text → verktygstips → platshållartext."""
    for getter in ("text", "toolTip", "placeholderText"):
        fn = getattr(widget, getter, None)
        if not callable(fn):
            continue
        try:
            v = clean_label(fn().split("\n")[0])
        except Exception:
            v = ""
        if v and re.search(r"\w", v):
            return v
    return ""


def apply_names(root: Any, skip_cards: bool = True) -> int:
    """Ge alla knappar, fält och rutor under ``root`` ett tillgängligt namn (om de saknar). Returnerar antalet nya."""
    n = 0
    try:
        from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QPlainTextEdit, QSlider, QSpinBox, QTextEdit
    except Exception:
        return 0
    found: List[Any] = []
    for kind in (QAbstractButton, QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QSlider, QSpinBox):
        found.extend(root.findChildren(kind))
    for w in found:
        try:
            if w.accessibleName():
                continue
            nm = name_for(w)
            if nm:
                w.setAccessibleName(nm)
                tip = w.toolTip() if hasattr(w, "toolTip") else ""
                if tip and not w.accessibleDescription():
                    w.setAccessibleDescription(tip.replace("\n", " ")[:300])
                n += 1
        except RuntimeError:
            continue
    return n
