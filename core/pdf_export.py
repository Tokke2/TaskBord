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

    css = (
        "<style>"
        "body { font-family: 'Segoe UI', Helvetica, Arial, sans-serif; "
        "color: #1a1a2e; }"
        "h1 { color: #4f46e5; margin: 0 0 4px 0; font-size: 26px; }"
        ".meta { color: #64748b; font-size: 11px; margin-bottom: 8px; }"
        ".section { margin-top: 14px; font-size: 14px; font-weight: 600; "
        "color: #4f46e5; border-bottom: 1px solid #e0e7ff; "
        "padding-bottom: 3px; }"
        "table { border-collapse: collapse; width: 100%; margin-top: 4px; }"
        "td { padding: 7px 4px; vertical-align: top; }"
        "tr.pin td.title { background: #fffbeb; font-weight: 600; }"
        "tr.done td.title { color: #94a3b8; text-decoration: line-through; }"
        ".box { font-size: 16px; color: #475569; width: 24px; }"
        ".prio { font-size: 13px; width: 28px; }"
        ".tags { color: #6366f1; font-size: 10px; margin-left: 6px; }"
        ".date { font-size: 10px; margin-left: 8px; white-space: nowrap; }"
        ".sublist { margin: 0; padding-left: 16px; "
        "font-size: 11px; color: #475569; }"
        ".pbar { margin-top: 4px; }"
        "td.pfill { background: #4f46e5; font-size: 2px; }"
        "td.pempty { background: #e2e8f0; font-size: 2px; }"
        ".footer { color: #94a3b8; font-size: 9px; "
        "text-align: center; margin-top: 16px; }"
        "</style>"
    )

    sections: Dict[str, List[tuple]] = {
        "📌 Pin": [], "🔴 Hög": [], "🟡 Medium": [],
        "🟢 Låg": [], "⚪ Ingen": [],
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
            sections["📌 Pin"].append(entry)
        elif p == "high":
            sections["🔴 Hög"].append(entry)
        elif p == "medium":
            sections["🟡 Medium"].append(entry)
        elif p == "low":
            sections["🟢 Låg"].append(entry)
        else:
            sections["⚪ Ingen"].append(entry)

    rows: List[str] = []
    for sec_name, items in sections.items():
        if not items:
            continue
        rows.append(
            f'<div class="section">{_html_escape(sec_name)} '
            f"<span style=\"font-weight:400;color:#64748b;font-size:11px\">"
            f"({len(items)})</span></div>"
        )
        rows.append("<table>")
        for t, title, tags, due, done, subs, p in items:
            badge, _ = _prio_meta(p)
            box = "☑" if done else "☐"
            tr_class = "done" if done else ("pin" if t.get("pinned") else "")
            tag_str = ""
            if tags:
                tag_str = (
                    " <span class='tags'>▪ "
                    + ", ".join(_html_escape(x) for x in tags)
                    + "</span>"
                )
            date_str = ""
            if due:
                # FIX v7-fix81: vänligt datum + färg (försenade = röda)
                label, color = _due_label(due)
                date_str = (
                    f"<span class='date' style='color:{color};"
                    f"font-weight:600'>📅 {_html_escape(label)}</span>"
                )
            rows.append(
                f"<tr class='{tr_class}'>"
                f"<td class='box'>{box}</td>"
                f"<td class='prio'>{badge}</td>"
                f"<td class='title'>{title}{tag_str}{date_str}</td>"
                f"</tr>"
            )
            # NY v8: delmoment + underdelmoment (rekursivt, indrag per nivå)
            def _sub_html(items: Any, depth: int = 1) -> List[str]:
                out: List[str] = []
                for s in items or []:
                    if not isinstance(s, dict):
                        continue
                    # FIX v7-fix81: ☑ när delmomentet är klart
                    sub_box = "☑" if s.get("done") else "☐"
                    indent = (depth - 1) * 14
                    out.append(
                        "<tr><td></td><td></td>"
                        f"<td class='sublist' style='padding-left:{indent}px'>"
                        f"{sub_box} {_html_escape(s.get('title', ''))}</td></tr>"
                    )
                    out.extend(_sub_html(s.get("children") or [], depth + 1))
                return out

            rows.extend(_sub_html(subs))
        rows.append("</table>")

    # FIX v7-fix81: progress-bar (tabell-baserad, Qt rich text-safe)
    bar = ""
    if n_total:
        bar = (
            "<table class='pbar' width='100%' cellspacing='0' "
            "cellpadding='0'><tr>"
            f"<td class='pfill' width='{pct}%'>&nbsp;</td>"
            f"<td class='pempty' width='{100 - pct}%'>&nbsp;</td>"
            "</tr></table>"
        )

    snoozed_note = (
        f" • {n_snoozed} senarelagda visas ej" if n_snoozed else ""
    )

    return (
        "<html><head>" + css + "</head><body>"
        f"<h1>📋 {_html_escape(app_name)} — Checklista</h1>"
        f"<div class='meta'>Skapad {now} • "
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
    Spara HTML till PDF via QPrinter + QTextDocument (PySide6 inbyggt).
    Returnerar True vid success.

    FIX v7-fix81: QPrinter.PageSizeId finns INTE i Qt6/PySide6 6.11 —
    gamla koden kastade tyst AttributeError → save_pdf returnerade
    ALLTID False (PDF-exporten har aldrig fungerat!). Qt6-rätt sätt:
    QPageSize(QPageSize.PageSizeId.A4) via pr.setPageSize(QPageSize).
    """
    try:
        from PySide6.QtPrintSupport import QPrinter
        from PySide6.QtGui import QTextDocument, QPageSize
    except ImportError:
        return False
    try:
        # Säkerställ att målmappen finns (t.ex. nätlagring/USB)
        try:
            Path(str(out_path)).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        pr = QPrinter(QPrinter.PrinterMode.HighResolution)
        pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        pr.setOutputFileName(out_path)
        # FIX v7-fix81: Qt6-API — QPageSize i stället för borttagen
        # QPrinter.PageSizeId
        size_id = (
            getattr(QPageSize.PageSizeId, page_size_id, None)
            or QPageSize.PageSizeId.A4
        )
        pr.setPageSize(QPageSize(size_id))
        doc = QTextDocument()
        doc.setHtml(html)
        doc.setPageSize(
            pr.pageRect(QPrinter.Unit.DevicePixel).size()
        )
        doc.print_(pr)
        return True
    except Exception:
        return False
