#!/usr/bin/env python3
"""
pdf_export_test.py — PDF-checklistan (core/pdf_export.py).

Kör:  python tester/pdf_export_test.py
Regression: texten blev 0,1–1,4 pt stor (QPrinter HighResolution 1200 dpi + dokumentlayout i 96 dpi).
Kontrollerar HTML:en (utan Qt) och den riktiga PDF:en (Qt offscreen; sidor/teckenstorlek via PyMuPDF om den finns).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def mk(n, **k):
    d = {"id": str(n), "title": f"Uppgift {n}", "priority": "none", "done": False, "tags": []}
    d.update(k)
    return d


def html_tests() -> None:
    from core.pdf_export import render_checklist_html
    today = date.today()
    tasks = [
        mk(1, title="Hög <b>&</b> viktig", priority="high", tags=["Info", "Jobb"], due_date=(today - timedelta(days=2)).isoformat()),
        mk(2, title="Fäst", priority="low", pinned=True),
        mk(3, title="Klar", done=True),
        mk(4, title="Senare", snoozed_until=(today + timedelta(days=3)).isoformat()),
        mk(5, title="Med delmoment", priority="medium", subtasks=[{"title": "A", "done": True, "children": [{"title": "A1", "done": False}]}, {"title": "B"}]),
    ]
    h = render_checklist_html(tasks, app_name="Ledgebord", app_version="1.0")
    check("rubrik med appnamnet", "Ledgebord — Checklista" in h)
    check("HTML-tecken i titlar escapas", "Hög &lt;b&gt;&amp;&lt;/b&gt; viktig" in h and "<b>&</b>" not in h)
    check("senarelagda visas inte men räknas", "Senare" not in h.split("</style>")[1].replace("senarelagda", "") and "1 senarelagda visas ej" in h)
    check("4 uppgifter, 1 klar, 25 %", "4 uppgifter (1 klara • 3 kvar • 25% klart)" in h, re.findall(r"\d+ uppgifter[^<]*", h))
    for sec in ("Fästa", "Hög prioritet", "Medel", "Utan prioritet"):
        check(f"sektion {sec}", f">{sec} " in h)
    check("tom sektion (Låg) utelämnas", "Låg prioritet" not in h)
    check("försenad uppgift visas röd", "2 dagar sen" in h and "#dc2626" in h)
    check("taggar visas", "#Info #Jobb" in h)
    check("delmoment och underdelmoment visas, klara som ☑", all(x in h for x in (">A<", ">A1<", ">B<", "☑")))
    check("ingen emoji i rubriker (typsnitt kan saknas → rutor)", not re.search("[\U0001F300-\U0001FAFF]", h))
    check("tabellerna är fullbredd", h.count("width='100%' cellspacing='0' cellpadding='0'>") >= 3)
    check("0 % och 100 % ger giltig förloppsrad", "pempty" in render_checklist_html([mk(1)]) and "width='100%'>&nbsp;" in render_checklist_html([mk(1, done=True)]))
    check("inga uppgifter → ingen krasch", "Checklista" in render_checklist_html([]))


def child(out_dir: str) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from core.pdf_export import render_checklist_html, save_pdf
    res = []

    def ck(n, c, extra=""):
        res.append((n + (f" {extra}" if not c and extra else ""), bool(c)))

    few = [mk(1, title="Köp mjölk", priority="high"), mk(2, title="Ring Anna"), mk(3, title="Klar", done=True)]
    p1 = Path(out_dir) / "few.pdf"
    ck("save_pdf → True", save_pdf(render_checklist_html(few), str(p1)))
    ck("filen är en PDF", p1.is_file() and p1.read_bytes()[:5] == b"%PDF-")
    many = [mk(i, title=f"Uppgift nummer {i} med lite längre text för att fylla raden", priority=["high", "medium", "low", "none"][i % 4],
               subtasks=[{"title": "Delsteg"}]) for i in range(80)]
    p2 = Path(out_dir) / "many.pdf"
    ck("80 uppgifter sparas", save_pdf(render_checklist_html(many), str(p2)))
    ck("sparar i en mapp som inte finns än", save_pdf(render_checklist_html(few), str(Path(out_dir) / "ny" / "mapp" / "x.pdf")))
    ck("ogiltig sökväg → False, ingen krasch", save_pdf(render_checklist_html(few), "/proc/finns/inte/x.pdf") is False)
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            fitz = None
    if fitz:
        d1 = fitz.open(str(p1))
        ck("1 sida, A4 (595×842 pt)", len(d1) == 1 and round(d1[0].rect.width) == 595 and round(d1[0].rect.height) == 842, (len(d1), d1[0].rect))
        sizes = [s["size"] for b in d1[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()]
        ck("brödtexten är läsbar (≥ 8 pt, inte 0,1–1,4 pt)", sizes and min(sizes) >= 8 and max(sizes) >= 18, (min(sizes), max(sizes)) if sizes else None)
        words = d1[0].get_text("words")
        right = max(w[2] for w in words)
        ck("innehållet ligger inom marginalerna (15 mm = 42,5 pt)", min(w[0] for w in words) >= 40 and right <= 595 - 40, right)
        txt = d1[0].get_text()
        ck("texten finns i PDF:en (sökbar)", "Köp mjölk" in txt and "Ring Anna" in txt and "Checklista" in txt)
        d2 = fitz.open(str(p2))
        ck("80 uppgifter → flera sidor", len(d2) >= 3, len(d2))
        ck("alla uppgifter finns med över sidorna", all(f"nummer {i} " in "".join(pg.get_text() for pg in d2) for i in (0, 41, 79)))
        meta = d1.metadata or {}
        ck("PDF-titeln är satt", "Ledgebord" in (meta.get("title") or ""), meta)
    else:
        print("  (PyMuPDF saknas — sid-/teckenstorlekskontroller hoppas över)")
        ck("flera sidor för 80 uppgifter", len(re.findall(rb"/Type\s*/Page\b", p2.read_bytes())) >= 3)
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child(sys.argv[-1])
else:
    html_tests()
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="pdftest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"pdf_export_test: PDF-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(work)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith(("✗", "(PyMuPDF")):
                    print(l)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2000:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\npdf_export_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
