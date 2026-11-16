#!/usr/bin/env python3
"""
donate_test.py — stöddialogen 💖: valfritt belopp, Swish-QR som standard (+ knapparna PayPal/Ko-fi), och att MOTTAGARNA ÄR LÅSTA.

Kör:  python tester/donate_test.py
Del 1 (ren Python): core/donate_info.py — kontrollsumma, belopp, länkar, Swish-payload, att inget kan styra om mottagarna.
Del 2 (Qt i egen process): dialogen offscreen.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def pure() -> None:
    from core import donate_info as DI
    check("kontrollsumman stämmer med mottagarna (las_ok)", DI.las_ok())
    check("kontrollsumman är en riktig SHA-256 (64 hextecken)", bool(re.fullmatch(r"[0-9a-f]{64}", DI._LAS_HASH)))
    check("PayPal- och Ko-fi-länkarna är de officiella", DI.PAYPAL_BAS == "https://paypal.me/Rickard3dPrint" and DI.KOFI_URL == "https://ko-fi.com/tokke2")
    check("PayPal-länk med belopp", DI.paypal_url(50) == "https://paypal.me/Rickard3dPrint/50SEK" and DI.paypal_url(1234) == "https://paypal.me/Rickard3dPrint/1234SEK")
    check("belopp begränsas 1…99 999 och skräp → standard", DI.clamp_belopp(0) == 1 and DI.clamp_belopp(10**9) == 99_999 and DI.clamp_belopp("abc") == 50 and DI.clamp_belopp(None) == 50 and DI.clamp_belopp("75") == 75)
    check("genvägarna är 25/50/100/200 och standard 50", DI.BELOPP_VAL == (25, 50, 100, 200) and DI.BELOPP_STANDARD == 50)
    check("Swish är standard: nummer inlagt och aktivt", DI.swish_nummer() == "0721817177" and DI.swish_aktiv())
    check("Swish-payload i officiellt C-format (belopp förifyllt, nummer låst = mask 6)", DI.swish_payload(75) == "C0721817177;75;Ledgebord;6", DI.swish_payload(75))

    # ändrad mottagare upptäcks (kontrollsumman är kopplad till alla fält)
    saved = (DI.PAYPAL_BAS, DI.KOFI_URL, DI.SWISH_NUMMER, DI.SWISH_MEDDELANDE)
    try:
        for fld, val in (("PAYPAL_BAS", "https://paypal.me/Annan"), ("KOFI_URL", "https://ko-fi.com/annan"),
                         ("SWISH_NUMMER", "0700000000"), ("SWISH_MEDDELANDE", "x")):
            old = getattr(DI, fld)
            setattr(DI, fld, val)
            check(f"ändrad {fld} → las_ok() är False", DI.las_ok() is False)
            setattr(DI, fld, old)
        check("…och efter återställning är den True igen", DI.las_ok())
        DI.SWISH_NUMMER = "072-181 71 77"
        check("Swish-nummer med streck/mellanslag rensas till siffror", DI.swish_nummer() == "0721817177" and DI.swish_aktiv())
    finally:
        DI.PAYPAL_BAS, DI.KOFI_URL, DI.SWISH_NUMMER, DI.SWISH_MEDDELANDE = saved

    # LÅST: ingen inställning/datafil/miljövariabel styr mottagarna
    for f in ("core/donate_info.py", "ui/donate.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        check(f"{f}: läser inga inställningar, datafiler eller miljövariabler",
              not re.search(r"os\.environ|getenv|settings|Settings|open\(|json\.load|read_text\(", code.replace("(ROOT", "")) or f == "ui/donate.py" and "os.environ" not in code and "getenv" not in code and "Settings" not in code and "json" not in code)
    sett = (ROOT / "core/settings.py").read_text(encoding="utf-8").lower()
    check("inga donationsinställningar finns i settings.py", "paypal" not in sett and "kofi" not in sett and "swish" not in sett and "donat" not in sett)
    updater = (ROOT / "core/updater.py").read_text(encoding="utf-8")
    m = re.search(r"PROTECTED_TOP[^=]*=\s*frozenset\(\{([^}]*)\}\)", updater)
    check("uppdateraren skyddar INTE donationsfilerna (en lokalt ändrad fil skrivs över av originalet)",
          bool(m) and "donate" not in m.group(1) and '"core"' not in m.group(1) and '"ui"' not in m.group(1), m.group(0)[:200] if m else "")
    for f in ("app/mixins/tray.py", "ui/widget_parts/window_ops.py"):
        check(f"stödvalet finns i {f}", "Stöd Ledgebord" in (ROOT / f).read_text(encoding="utf-8"))
    check("Om-rutan säger inte längre 'Donation: inaktiverad'", "Donation: inaktiverad" not in (ROOT / "app/mixins/diagnostics.py").read_text(encoding="utf-8"))
    check("segno finns i requirements.txt (QR för Swish)", "segno" in (ROOT / "requirements.txt").read_text(encoding="utf-8"))
    for f in ("README.md", "docs/MANUAL.md"):
        t = (ROOT / f).read_text(encoding="utf-8")
        check(f"{f}: ingen egen donationssida/länkar till PayPal eller Ko-fi", "paypal.me" not in t and "ko-fi.com" not in t)
        check(f"{f}: Swish-numret står inte i klartext", "0721817177" not in t and "072-181" not in t)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from core import donate_info as DI
    import ui.donate as D

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    opened: list = []
    D._open_url = lambda u: opened.append(u) or True

    dlg = D.DonateDialog()
    dlg.show()
    app.processEvents()
    ck("dialogen skapas, lås OK", dlg._lock_ok and "låsta" in dlg.lock_label.text())
    ck("standardbelopp 50 kr är valt (genväg markerad)", dlg.belopp() == 50 and dlg.chips[50].isChecked() and not dlg.chips[25].isChecked())
    ck("banner med ikon", dlg.logo.pixmap() is not None and not dlg.logo.pixmap().isNull())
    ck("Swish-QR visas direkt (standard) med bild", dlg.qr_box.isVisible() and dlg.qr_label.pixmap() is not None and not dlg.qr_label.pixmap().isNull())
    ck("det finns ingen Swish-knapp — bara QR; bara PayPal och Ko-fi som knappar", not hasattr(dlg, "btn_swish"))
    from PySide6.QtWidgets import QLabel, QPushButton
    alltext = " ".join([w.text() + " " + w.toolTip() for w in dlg.findChildren(QLabel)] + [w.text() + " " + w.toolTip() for w in dlg.findChildren(QPushButton)])
    ck("Swish-numret står inte som text någonstans i dialogen", "0721817177" not in alltext and "072-181" not in alltext and "721817177" not in alltext)
    q50 = dlg.qr_label.pixmap().toImage()
    ck("PayPal-knappen visar beloppet", "50 kr" in dlg.btn_paypal.text())
    dlg.chips[200].click()
    ck("QR:n ritas om när beloppet ändras", dlg.qr_label.pixmap().toImage() != q50)
    ck("klick på genväg sätter beloppet", dlg.belopp() == 200 and dlg.chips[200].isChecked() and not dlg.chips[50].isChecked() and "200 kr" in dlg.btn_paypal.text())
    dlg.eget.setValue(75)
    ck("eget belopp avmarkerar genvägarna", dlg.belopp() == 75 and not any(b.isChecked() for b in dlg.chips.values()) and "75 kr" in dlg.info.text())
    dlg.eget.setValue(100)
    ck("eget belopp som matchar en genväg markerar den", dlg.chips[100].isChecked())
    dlg.eget.setValue(75)
    dlg.btn_paypal.click()
    dlg.btn_kofi.click()
    ck("PayPal öppnar rätt länk med valt belopp", opened[0] == "https://paypal.me/Rickard3dPrint/75SEK", opened)
    ck("Ko-fi öppnar rätt länk", opened[1] == "https://ko-fi.com/tokke2", opened)
    ck("spinrutan går inte under 1 eller över 99 999", (dlg.eget.setValue(-5), dlg.eget.value())[1] == 1 and (dlg.eget.setValue(10**7), dlg.eget.value())[1] == 99_999)
    dlg.close()

    # ändrade mottagare → knappar av + varning, inget öppnas
    saved = DI.PAYPAL_BAS
    DI.PAYPAL_BAS = "https://paypal.me/Annan"
    try:
        bad = D.DonateDialog()
        bad.show()
        n = len(opened)
        bad._open_paypal()
        bad._show_qr()
        ck("ändrade mottagare: betalknapparna är avstängda", not bad.btn_paypal.isEnabled() and not bad.btn_kofi.isEnabled() and not bad.qr_box.isVisible())
        ck("…varnar tydligt och öppnar ingenting", "stämmer inte" in bad.lock_label.text() and len(opened) == n)
        bad.close()
    finally:
        DI.PAYPAL_BAS = saved

    png = D.swish_qr_png(75)
    ck("Swish-QR är en PNG", bool(png) and png[:8] == b"\x89PNG\r\n\x1a\n")
    ck("QR-bytes innehåller inte numret i klartext", b"0721817177" not in png)
    shot = os.environ.get("DONATE_SHOT")
    if shot:
        dlg3 = D.DonateDialog()
        dlg3.show()
        app.processEvents()
        dlg3.grab().save(shot)
        dlg3.close()

    dlg2 = D.DonateDialog()
    dlg2.show()
    app.processEvents()
    shot2 = os.environ.get("DONATE_SHOT2")
    if shot2:
        dlg2.grab().save(shot2)
    ck("öppnas igen efter testerna med låset intakt", dlg2._lock_ok)
    dlg2.close()

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    pure()
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="ledgebord_donate_"))
    env, why = qt_env(work)
    if env is None:
        print(f"donate_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=240)
        line = [x for x in r.stdout.splitlines() if x.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for x in r.stdout.splitlines():
                if x.startswith("  ✗"):
                    print(x)
        else:
            _fail += 1
            print("  ✗ Qt-barnet gav inget resultat", r.stdout[-400:], r.stderr[-600:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\ndonate_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
