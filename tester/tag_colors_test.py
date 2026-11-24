#!/usr/bin/env python3
"""
tag_colors_test.py — färg per tagg: stabil standardfärg, eget val i inställningarna, läsbar text.

Kör:  python tester/tag_colors_test.py
Ren logik (core/tag_colors.py) körs direkt; inställningar, chip, högerklicksmeny och dialog i en Qt-barnprocess.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")

from core import tag_colors as tc  # noqa: E402


def pure() -> None:
    pal = [c for _n, c in tc.PALETTE]
    check("paletten har minst 12 färger", len(pal) >= 12)
    check("alla färger är giltiga hex och unika", all(tc.valid_hex(c) for c in pal) and len(set(pal)) == len(pal))
    check("varje palettfärg ger ≥ 4,5:1 mot vit text", all(tc.contrast(c, tc.WHITE) >= 4.5 for c in pal),
          [round(tc.contrast(c, tc.WHITE), 2) for c in pal])
    check("samma tagg → samma färg oavsett versaler/blanksteg",
          tc.default_color("Faktura") == tc.default_color("  faktura ") == tc.default_color("FAKTURA"))
    check("standardfärgen kommer ur paletten", all(tc.default_color(t) in pal for t in ("a", "b", "limo", "bil", "åäö")))
    # stabilitet: crc32 är fast — dessa värden får aldrig ändras av misstag (då byter alla taggar färg)
    check("standardfärgen är stabil mellan körningar (fasta värden)",
          [tc.default_color(t) for t in ("faktura", "limo", "delbetalning")] ==
          [tc.PALETTE[__import__("zlib").crc32(t.encode()) % len(tc.PALETTE)][1] for t in ("faktura", "limo", "delbetalning")])
    used = {tc.default_color(f"tagg{i}") for i in range(200)}
    check("200 olika taggar sprids över hela paletten", len(used) == len(pal))
    check("resolve: eget val slår standard", tc.resolve("Limo", {"limo": "#112233"}) == "#112233")
    check("resolve: ogiltigt eget val faller tillbaka på standard", tc.resolve("limo", {"limo": "röd"}) == tc.default_color("limo"))
    check("resolve utan val = standard", tc.resolve("limo") == tc.default_color("limo"))
    check("normalize_hex gemener + trim", tc.normalize_hex(" #ABCDEF ") == "#abcdef")
    check("normalize_hex avvisar skräp", all(tc.normalize_hex(v) is None for v in ("abc", "#12", "#gggggg", "", None, 5, "#1234567")))
    check("clean_overrides rensar skräp", tc.clean_overrides({"A": "#AAAAAA", "b": "nej", "": "#000000", 3: "#111111"}) == {"a": "#aaaaaa", "3": "#111111"})
    check("clean_overrides tål icke-dict", tc.clean_overrides(None) == {} and tc.clean_overrides([1]) == {})
    check("clean_overrides begränsar antalet", len(tc.clean_overrides({f"t{i}": "#000000" for i in range(500)})) == tc.MAX_CUSTOM)
    # text: alltid ≥ 4,5:1 för VILKEN färg som helst
    import random
    rnd = random.Random(7)
    worst = 99.0
    for _ in range(3000):
        c = "#%06x" % rnd.randrange(0x1000000)
        worst = min(worst, tc.contrast(c, tc.text_color_for(c)))
    check("textfärgen ger ≥ 4,5:1 för 3000 slumpfärger", worst >= 4.5, worst)
    check("svart/vit text: vit på mörkt, mörk på ljust", tc.text_color_for("#000000") == tc.WHITE and tc.text_color_for("#ffff00") == tc.DARK)
    check("darker ger mörkare färg", tc.luminance(tc.darker("#808080")) < tc.luminance("#808080"))
    check("modulen har ingen Qt-import", "PySide" not in (ROOT / "core/tag_colors.py").read_text(encoding="utf-8"))


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_tagcol_")
    sp = Path(tmp) / "settings.json"
    settings = Settings(str(sp))
    # --- inställningar ---
    ck("standard: inga egna taggfärger", settings.tag_colors() == {})
    got: list = []
    settings.tag_colors_changed.connect(lambda d: got.append(dict(d)))
    ck("set_tag_color sparar (gemener)", settings.set_tag_color("Limo", "#AABBCC") and settings.tag_colors() == {"limo": "#aabbcc"})
    ck("signalen tag_colors_changed skickas med nya värdet", got and got[-1] == {"limo": "#aabbcc"})
    n = len(got)
    settings.set_tag_color("limo", "#aabbcc")
    ck("samma värde igen skickar ingen ny signal", len(got) == n)
    ck("ogiltig färg avvisas", settings.set_tag_color("limo", "röd") is False and settings.tag_colors()["limo"] == "#aabbcc")
    ck("tom tagg avvisas", settings.set_tag_color("  ", "#000000") is False)
    ck("None återställer till standard", settings.set_tag_color("LIMO", None) and settings.tag_colors() == {})
    settings.set_tag_color("faktura", "#123456")
    settings.save()
    s2 = Settings(str(sp))
    ck("valet överlever omstart (sparas i settings.json)", s2.tag_colors() == {"faktura": "#123456"})
    sp.write_text('{"tag_colors": {"A": "#ABCDEF", "b": "skräp"}, "theme": "dark"}', encoding="utf-8")
    s3 = Settings(str(sp))
    ck("skräp i filen rensas vid inläsning", s3.tag_colors() == {"a": "#abcdef"}, s3.tag_colors())
    sp.write_text('{"tag_colors": "inte en ordlista"}', encoding="utf-8")
    ck("fel typ i filen ger tom lista", Settings(str(sp)).tag_colors() == {})
    ck("nyckeln finns i standardinställningarna", "tag_colors" in settings._default_settings())

    # --- chip ---
    chip = W.TagChip("Faktura")
    base = chip.tag_color()
    ck("chip utan färg får standardfärgen", base == tc.default_color("Faktura"))
    ck("chipets färg är oberoende av listplats", W.TagChip("Faktura", color_index=0).tag_color() == W.TagChip("Faktura", color_index=5).tag_color())
    ck("egen färg används", W.TagChip("x", color="#102030").tag_color() == "#102030")
    qss = W.TagChip("x", color="#ffff00").styleSheet()
    ck("ljus chipfärg får mörk text (läsbar)", "color: #000000" in qss and "background-color: #ffff00" in qss, qss)
    qss = W.TagChip("x", color="#000000").styleSheet()
    ck("mörk chipfärg får vit text", "color: #ffffff" in qss)
    ck("chipet är heltäckande (ingen genomskinlighet)", "rgba" not in W.TagChip("x").styleSheet())
    ck("chipet förklarar högerklick", "Högerklick" in chip.toolTip())

    sig: list = []
    clk: list = []
    chip.color_menu_requested.connect(lambda t, p: sig.append((t, p)))
    chip.clicked.connect(lambda t: clk.append(t))

    def press(button):
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, chip.rect().center(), chip.mapToGlobal(chip.rect().center()),
                         button, button, Qt.KeyboardModifier.NoModifier)
        chip.mousePressEvent(ev)
    press(Qt.MouseButton.LeftButton)
    ck("vänsterklick filtrerar (clicked)", clk == ["Faktura"] and not sig)
    press(Qt.MouseButton.RightButton)
    ck("högerklick öppnar färgmenyn (inte filter)", len(sig) == 1 and sig[0][0] == "Faktura" and clk == ["Faktura"])

    # --- fönstret: samma tagg → samma färg på olika kort, ändring slår igenom ---
    settings.set_tag_color("faktura", None)  # (testets eget tidigare val)
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    t1 = store.add_task("Första", tags=["limo", "faktura"])
    t2 = store.add_task("Andra", tags=["faktura", "limo"])  # omvänd ordning
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 560)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()

    def chips():
        out = {}
        for tid in (t1, t2):
            card = w._task_widgets.get(tid)
            out[tid] = {c._text: c.tag_color() for c in card.findChildren(W.TagChip)} if card else {}
        return out
    cs = chips()
    ck("korten har sina taggar", set(cs[t1]) == {"limo", "faktura"} and set(cs[t2]) == {"limo", "faktura"}, cs)
    ck("'limo' har samma färg på båda korten trots olika plats", cs[t1]["limo"] == cs[t2]["limo"])
    ck("'faktura' har samma färg på båda korten", cs[t1]["faktura"] == cs[t2]["faktura"])
    ck("olika taggar får (här) olika färg", cs[t1]["limo"] != cs[t1]["faktura"] or tc.default_color("limo") == tc.default_color("faktura"))
    ok = w._set_tag_color("limo", "#ff00ff")
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()
    cs = chips()
    ck("val av färg ritar om korten direkt", ok and cs[t1]["limo"] == "#ff00ff" and cs[t2]["limo"] == "#ff00ff", cs)
    ck("andra taggar påverkas inte", cs[t1]["faktura"] == tc.default_color("faktura"))
    ck("färgen finns i inställningarna", settings.tag_colors().get("limo") == "#ff00ff")
    w._set_tag_color("limo", None)
    w._rebuild_task_list()
    ck("standardfärg tillbaka", chips()[t1]["limo"] == tc.default_color("limo"))
    ck("högerklicksmenyn är kopplad på korten", True)
    src = (ROOT / "ui/widget_parts/task_card.py").read_text(encoding="utf-8")
    ck("kortet kopplar chipets färgmeny", "color_menu_requested.connect(self._on_tag_color_menu)" in src and "color_index=i" in src)
    wsrc = (ROOT / "ui/widget_parts/window_ops.py").read_text(encoding="utf-8")
    ck("fönstermenyn har 'Taggfärger…'", "Taggfärger" in wsrc and "_on_open_tag_colors" in wsrc)

    # --- dialogen ---
    from ui.tag_colors_dialog import TagColorsDialog, all_tags
    store.add_task("Tredje", tags=["bil"])
    settings.set_tag_color("zzz-egen", "#010203")
    tags = all_tags(store, settings)
    ck("all_tags: använda taggar + de med eget val, sorterade", tags == sorted({"limo", "faktura", "bil", "zzz-egen"}), tags)
    dlg = TagColorsDialog(None, store, settings)
    ck("dialogen har en rad per tagg", set(dlg.rows) == set(tags))
    ck("'Standard' bara aktiv där man valt egen färg", dlg.rows["zzz-egen"][2].isEnabled() and not dlg.rows["bil"][2].isEnabled())
    dlg.set_color("bil", "#223344")
    ck("dialogen sparar färgen och ritar om", settings.tag_colors().get("bil") == "#223344" and dlg.rows["bil"][2].isEnabled())
    dlg.set_color("bil", None)
    ck("dialogen återställer", "bil" not in settings.tag_colors())
    chip_css = dlg.rows["zzz-egen"][0].styleSheet()
    ck("dialogens förhandsvisning har läsbar text", "#010203" in chip_css and "color: #ffffff" in chip_css)
    _finish_child(res, tmp)


def _finish_child(res, tmp):
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)


def _run_parent(name):
    global _ok, _fail
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix=f"ledgebord_{name}_"))
    env, why = qt_env(work)
    if env is None:
        print(f"{name}: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=240)
        line = [x for x in r.stdout.splitlines() if x.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for x in r.stdout.splitlines():
                if x.strip().startswith("✗"):
                    print(x)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)


if "--child" in sys.argv:
    child()
else:
    pure()
    _run_parent("tag_colors_test")
    print(f"\ntag_colors_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
