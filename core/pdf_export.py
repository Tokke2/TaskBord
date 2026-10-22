"""
pdf_export.py — NY v6.4.1 v7 (2026-09-25): Snygg PDF-checklista för Ledgebord.
Genererar HTML som renderas via QPrinter → PDF (ingen extern dep).

FIX v7-fix81 (Rickard 2026-10-07: "exportera aktiva till en pdf som en
modern checklista"):
  - Progress-bar i sidhuvudet (X% klart, tabell-baserad — Qt rich text-safe)
  - Vänliga förfallodatum: "idag" / "imorgon" / "om 3 dagar" /
    "⚠ 2 dagar sen" (röd) i stället för råa ISO-datum
  - Delmoment visar ☑ när de är klara (var alltid ☐ tidigare)
  - Större kryssrutor (16px) — trevligare att bocka av på papper
  - Senarelagda (snoozade) uppgifter exkluderas — samma vy som
    Aktiva-fliken — och antalet redovisas i sidhuvudet
"""
from __future__ import annotations

from datetime import datetime as _datetime, date as _date
from pathlib import Path
from typing import Any, Dict, List, Tuple


PDF_TITLE = "Ledgebord — checklista"


def _html_escape(s: Any) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _prio_meta(p: str) -> Tuple[str, str]:
    return {
        "high": ("🔴", "#dc2626"),
        "medium": ("🟡", "#d97706"),
        "low": ("🟢", "#16a34a"),
        "none": ("⚪", "#94a3b8"),
    }.get(str(p or "none").lower(), ("⚪", "#94a3b8"))


def _is_snoozed(t: Dict[str, Any]) -> bool:
    """Är uppgiften senarelagd (snoozed_until i framtiden)?"""
    try:
        until = str(t.get("snoozed_until") or "").strip()
        if not until:
            return False
        # ISO: ÅÅÅÅ-MM-DD eller ÅÅÅÅ-MM-DDTHH:MM
        d = _datetime.fromisoformat(until[:10])
        return d.date() >= _date.today()
    except (ValueError, TypeError):
        return False


def _due_label(due: Any) -> Tuple[str, str]:
    """
    FIX v7-fix81: vänligt datum + färg.
    Returnerar (text, färg). "" om inget datum.
    """
    try:
        iso = str(due or "").strip()
        if not iso:
            return ("", "#64748b")
        d = _datetime.fromisoformat(iso[:10]).date()
        delta = (d - _date.today()).days
        if delta < 0:
            return (f"⚠ {abs(delta)} dagar sen", "#dc2626")
        if delta == 0:
            return ("idag", "#d97706")
        if delta == 1:
            return ("imorgon", "#64748b")
        if delta <= 14:
            return (f"om {delta} dagar", "#64748b")
        return (d.strftime("%Y-%m-%d"), "#64748b")
    except (ValueError, TypeError):
        return (str(due or ""), "#64748b")


def render_checklist_html(
    tasks: List[Dict[str, Any]],
    app_name: str = "Ledgebord",
    app_version: str = "6.4.1 v7",
) -> str:
    """
    Generera snygg HTML-checklista.
    Sektioner: 📌 Pin • 🔴 Hög • 🟡 Medium • 🟢 Låg • ⚪ Ingen.
    """
    # FIX v7-fix81: senarelagda exkluderas (samma vy som Aktiva-fliken)
    n_snoozed = sum(1 for t in tasks if _is_snoozed(t))
    tasks = [t for t in tasks if not _is_snoozed(t)]

    prio_order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    sorted_tasks = sorted(
        tasks,
        key=lambda t: (
            0 if t.get("pinned") else 1,
            prio_order.get(str(t.get("priority", "none")).lower(), 3),
            str(t.get("title", "")).lower(),
        ),
    )

    now = _datetime.now().strftime("%Y-%m-%d %H:%M")
    n_total = len(sorted_tasks)
    n_done = sum(1 for t in sorted_tasks if t.get("done"))
    pct = int(round(100 * n_done / n_total)) if n_total else 0

    # Ritas utan emoji i rubriker/prio (typsnittet på en annan dator kan sakna dem → rutor i PDF:en)
    css = (
        "<style>"
        "body { font-family: 'Segoe UI', Helvetica, Arial, sans-serif; "
        "color: #1e293b; font-size: 14px; }"
        "h1 { color: #3730a3; margin: 0; font-size: 30px; }"
        ".sub { color: #475569; font-size: 13px; margin: 2px 0 10px 0; }"
        ".section { margin-top: 20px; font-size: 16px; font-weight: 600; "
        "padding-bottom: 3px; }"
        "table.list { border-collapse: collapse; width: 100%; margin-top: 4px; }"
        "td { vertical-align: top; }"
        "td.title { padding: 8px 4px 8px 6px; font-size: 14px; "
        "border-bottom: 1px solid #e2e8f0; }"
        "td.box { padding: 8px 4px; font-size: 17px; color: #334155; width: 22px; "
        "border-bottom: 1px solid #e2e8f0; }"
        "td.bar { width: 5px; }"
        "tr.pin td.title, tr.pin td.box { background: #fffbeb; }"
        "tr.done td.title { color: #64748b; text-decoration: line-through; }"
        "td.subbox { padding: 2px 4px 2px 0; font-size: 13px; color: #475569; width: 22px; }"
        "td.subt { padding: 2px 4px; font-size: 13px; color: #475569; }"
        "tr.subdone td.subt { color: #64748b; text-decoration: line-through; }"
        ".tags { color: #4338ca; font-size: 12px; }"
        ".date { font-size: 12px; font-weight: 600; }"
        "td.pfill { background: #4f46e5; font-size: 9px; }"
        "td.pempty { background: #e2e8f0; font-size: 9px; }"
        ".footer { color: #64748b; font-size: 11px; margin-top: 22px; }"
        "</style>"
    )

    prio_color = {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a", "none": "#94a3b8"}
    sections: Dict[str, List[tuple]] = {
        "Fästa": [], "Hög prioritet": [], "Medel": [],
        "Låg prioritet": [], "Utan prioritet": [],
    }
    sec_color = {
        "Fästa": "#b45309", "Hög prioritet": "#b91c1c", "Medel": "#b45309",
        "Låg prioritet": "#15803d", "Utan prioritet": "#475569",
    }
    for t in sorted_tasks:
        p = str(t.get("priority", "none")).lower()
        title = _html_escape(t.get("title", "(ingen titel)"))
        tags = t.get("tags", [])
        due = t.get("due_date", "")
        done = bool(t.get("done"))
        pinned = bool(t.get("pinned"))
        subs = t.get("subtasks", []) or []
        entry = (t, title, tags, due, done, subs, p)
        if pinned:
            sections["Fästa"].append(entry)
        elif p == "high":
            sections["Hög prioritet"].append(entry)
        elif p == "medium":
            sections["Medel"].append(entry)
        elif p == "low":
            sections["Låg prioritet"].append(entry)
        else:
            sections["Utan prioritet"].append(entry)

    def _sub_html(items: Any, depth: int = 1) -> List[str]:
        out: List[str] = []
        for s in items or []:
            if not isinstance(s, dict):
                continue
            sdone = bool(s.get("done"))
            indent = (depth - 1) * 16
            out.append(
                f"<tr class='{'subdone' if sdone else ''}'><td width='6'></td>"
                f"<td class='subbox' width='26' align='right'>{'☑' if sdone else '☐'}</td>"
                f"<td class='subt' width='100%' style='padding-left:{6 + indent}px'>"
                f"{_html_escape(s.get('title', ''))}</td></tr>"
            )
            out.extend(_sub_html(s.get("children") or [], depth + 1))
        return out

    rows: List[str] = []
    for sec_name, items in sections.items():
        if not items:
            continue
        rows.append(
            f'<div class="section" style="color:{sec_color[sec_name]}">'
            f"{_html_escape(sec_name)} "
            f"<span style=\"font-weight:400;color:#475569;font-size:13px\">"
            f"({len(items)})</span></div>"
        )
        rows.append("<table class='list' width='100%' cellspacing='0' cellpadding='0'>")
        for t, title, tags, due, done, subs, p in items:
            box = "☑" if done else "☐"
            tr_class = "done" if done else ("pin" if t.get("pinned") else "")
            extra = ""
            if tags:
                extra += (
                    " &nbsp;<span class='tags'>#"
                    + " #".join(_html_escape(x) for x in tags)
                    + "</span>"
                )
            if due:
                # vänligt datum + färg (försenade = röda)
                label, color = _due_label(due)
                extra += (
                    f" &nbsp;<span class='date' style='color:{color}'>"
                    f"{_html_escape(label)}</span>"
                )
            bar = prio_color.get(p, "#94a3b8")
            rows.append(
                f"<tr class='{tr_class}'>"
                f"<td class='bar' width='6' bgcolor='{bar}'>&nbsp;</td>"
                f"<td class='box' width='26' align='right'>{box}</td>"
                f"<td class='title' width='100%'>{title}{extra}</td>"
                f"</tr>"
            )
            rows.extend(_sub_html(subs))
        rows.append("</table>")

    # progress-bar (tabell-baserad, Qt rich text-safe)
    bar = ""
    if n_total:
        if 0 < pct < 100:
            cells = (f"<td class='pfill' width='{pct}%'>&nbsp;</td>"
                     f"<td class='pempty' width='{100 - pct}%'>&nbsp;</td>")
        elif pct >= 100:
            cells = "<td class='pfill' width='100%'>&nbsp;</td>"
        else:
            cells = "<td class='pempty' width='100%'>&nbsp;</td>"
        bar = (
            "<table class='pbar' width='100%' cellspacing='0' "
            f"cellpadding='0'><tr>{cells}</tr></table><div style='font-size:2px'>&nbsp;</div>"
        )

    snoozed_note = (
        f" • {n_snoozed} senarelagda visas ej" if n_snoozed else ""
    )

    return (
        "<html><head>" + css + "</head><body>"
        f"<h1>{_html_escape(app_name)} — Checklista</h1>"
        f"<div class='sub'>Skapad {now} • "
        f"{n_total} uppgifter ({n_done} klara • "
        f"{n_total - n_done} kvar • {pct}% klart){snoozed_note}</div>"
        + bar
        + "".join(rows)
        + f"<div class='footer'>{_html_escape(app_name)} "
          f"v{_html_escape(app_version)}</div>"
        + "</body></html>"
    )


def save_pdf(
    html: str,
    out_path: str,
    page_size_id: str = "A4",
) -> bool:
    """
    Spara HTML till PDF (vektor) via QPdfWriter + QTextDocument (PySide6 inbyggt).
    Returnerar True vid success.

    FIX (2026-10-22): texten blev pyttliten (0,1–1,4 pt) i uppe i hörnet på sidan.
    Orsak: QPrinter(HighResolution) = 1200 dpi → sidans storlek räknades i 1200-dpi-pixlar
    medan QTextDocument lägger ut text/CSS-px med 96 dpi. Nu används ett och samma dpi (96)
    för både dokumentets layout och sidan, så px i CSS:en blir verkliga storlekar
    (1 px = 0,75 pt) och sidan fylls med marginaler på 15 mm. PDF:en är vektorbaserad, så
    texten är skarp ändå.
    """
    try:
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    except ImportError:
        return False
    try:
        # Säkerställ att målmappen finns (t.ex. nätlagring/USB)
        try:
            Path(str(out_path)).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        size_id = (
            getattr(QPageSize.PageSizeId, page_size_id, None)
            or QPageSize.PageSizeId.A4
        )
        dpi = 96
        w = QPdfWriter(str(out_path))
        w.setResolution(dpi)
        w.setPageLayout(QPageLayout(
            QPageSize(size_id), QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter,
        ))
        try:
            w.setTitle(PDF_TITLE)
            w.setCreator("Ledgebord")
        except Exception:
            pass
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setHtml(html)
        rect = w.pageLayout().paintRectPixels(dpi)
        doc.setPageSize(QSizeF(rect.width(), rect.height()))
        doc.print_(w)
        return Path(str(out_path)).is_file() and Path(str(out_path)).stat().st_size > 0
    except Exception:
        return False
