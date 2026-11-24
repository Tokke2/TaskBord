#!/usr/bin/env python3
"""
start_minimized_test.py — "starta alltid minimerat": standardvärdet, engångsmigreringen av äldre inställningar
och att fönstret göms direkt (utan att tvingas fram) när minimerad start gäller.

Kör:  python tester/start_minimized_test.py   (ren Python, inget Qt)
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "core", ROOT / "ui"):
    sys.path.insert(0, str(p))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


from core.settings import Settings  # noqa: E402
from app.mixins.tray_hide import TrayHideMixin  # noqa: E402


class Ctl(TrayHideMixin):
    def __init__(self, settings):
        self.settings = settings
        self._log = logging.getLogger("sm")


with tempfile.TemporaryDirectory() as tmp:
    # 1. ny installation: standard = PÅ
    s = Settings(str(Path(tmp) / "ny.json"))
    check("ny installation: 'Starta minimerad i tray' är på som standard", s.start_minimized() is True)
    c = Ctl(s)
    check("…och migreringen ändrar inget som redan är på", (c._migrate_start_minimized_default(), s.start_minimized())[1] is True)
    check("…markerar migreringen som gjord", s.pref("start_min_default") is True)

    # 2. äldre inställningsfil med sparat 'av' → slås på EN gång
    s2 = Settings(str(Path(tmp) / "gammal.json"))
    s2.set_start_minimized(False)
    c2 = Ctl(s2)
    c2._migrate_start_minimized_default()
    check("äldre inställning (sparat av) slås på vid första starten", s2.start_minimized() is True)
    s2.set_start_minimized(False)          # användaren stänger av själv i tray-menyn
    c2._migrate_start_minimized_default()
    check("…men en senare egen avstängning respekteras (migreringen körs bara en gång)", s2.start_minimized() is False)
    check("_start_minimized_wanted följer inställningen", c2._start_minimized_wanted() is False)
    s2.set_start_minimized(True)
    check("…och är True när den är på", c2._start_minimized_wanted() is True)

    # 3. tyst omstart efter uppdatering → gömd även om inställningen är av
    s2.set_start_minimized(False)
    import time
    s2.set_restart_hidden_until(time.time() + 60)
    check("tyst omstart (restart_hidden_until) → minimerad", c2._start_minimized_wanted() is True)
    s2.set_restart_hidden_until(0)

# 3b. start med datorn → dockas i skärmkanten (tray-ikonen finns kvar), annars göms fönstret i tray
class W:
    def __init__(self, ok):
        self.ok, self.calls = ok, 0

    def _edge_dock_at_start(self):
        self.calls += 1
        return self.ok


class S:
    def __init__(self, dock=True, enabled=True):
        self.dock, self.enabled = dock, enabled

    def pref(self, k):
        return self.dock if k == "autostart_dock" else False

    def edge_dock_enabled(self):
        return self.enabled

    def start_minimized(self):
        return True

    def restart_hidden_until(self):
        return 0


class C2(TrayHideMixin):
    def __init__(self, auto, ok=True, **kw):
        self.settings = S(**kw)
        self._log = logging.getLogger("sm2")
        self._widget_lock = threading.RLock()
        self.w = W(ok)
        self._widgets = {"a": self.w}
        self.auto = auto
        self.hidden = 0

    def _started_by_autostart(self):
        return self.auto

    def _hide_to_tray(self, notice=True):
        self.hidden += 1
        return True


c = C2(True)
c._apply_start_minimized()
check("start med datorn: fönstret läggs i skärmkanten, inte i tray", c.w.calls == 1 and c.hidden == 0)
c = C2(True, ok=False)
c._apply_start_minimized()
check("…går det inte att docka göms det i tray som reserv", c.w.calls == 1 and c.hidden == 1)
c = C2(True, dock=False)
c._apply_start_minimized()
check("…inställningen 'autostart_dock' av → tray som förut", c.w.calls == 0 and c.hidden == 1)
c = C2(True, enabled=False)
c._apply_start_minimized()
check("…dockning avstängd → tray som förut", c.w.calls == 0 and c.hidden == 1)
c = C2(False)
c._apply_start_minimized()
check("manuell start (inte med datorn) dockar inte — gömmer i tray", c.w.calls == 0 and c.hidden == 1)
check("pref autostart_dock är på som standard", Settings(str(Path(tempfile.gettempdir()) / "sm_x.json")).pref("autostart_dock") is True)

# 4. controller: fönstret tvingas inte fram vid minimerad start, och gömmandet sker snabbt
src = (ROOT / "app/controller.py").read_text(encoding="utf-8")
check("controller: force_show hoppas över vid minimerad start", "if self._config.force_show_widget and not _min_start:" in src)
check("controller: göm till tray efter 250 ms vid minimerad start (annars 3000 ms)",
      "250 if _min_start else 3000" in src)
check("controller: migreringen körs före beslutet", src.index("_migrate_start_minimized_default()") < src.index("_start_minimized_wanted()"))

print(f"\nstart_minimized_test: {_ok} lyckades, {_fail} misslyckades")
sys.exit(1 if _fail else 0)
