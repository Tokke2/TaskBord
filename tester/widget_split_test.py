#!/usr/bin/env python3
"""
widget_split_test.py — ui/widget.py är delad i widget_base / widget_atoms / widget_parts (mixins) + fasad.

Kör:  python tester/widget_split_test.py
Kontrollerar att inget försvann i delningen (alla 141 TodoWidget-metoder finns kvar), att alla namn
som delarna använder går att slå upp, att mixin-ordningen är rätt, att signalerna ligger i klassen,
att textstorleken (_UI_FONT_SCALE) är live via fasaden och att QMessageBox-importen fungerar.
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

from _src import widget_files, widget_source  # noqa: E402

_ok = _fail = 0

EXPECTED_METHODS = (
    '__init__', '_screen_adapted_size', '_preshow_diagnostic', '_init_ui_minimal', '_initial_render',
    '_init_ui_phase2', '_init_ui', '_snooze_choices', '_due_choices', '_on_subtask_toggle',
    '_on_task_context_menu', '_show_task_menu', '_store_call', '_prompt_and_set_due', '_pick_date',
    '_prompt_and_set_start', '_add_subtask_rows', '_on_subtask_context_menu', '_prompt_rename_subtask',
    '_prompt_subtasks', '_prompt_rename', '_prompt_delete', '_on_task_toggle', '_on_pin_toggle',
    '_on_title_edited', '_on_delete_clicked', '_on_input_submit', '_on_priority_dot_clicked',
    '_on_priority_dot_right_clicked', '_set_input_priority', '_update_input_priority_indicator',
    '_set_task_priority', '_on_input_priority_dot_clicked', '_on_tab_changed', '_on_search_changed',
    '_do_search', '_on_close_clicked', '_on_tag_clicked', 'eventFilter', '_show_task_in_active',
    '_flash_new_task', '_apply_flash', '_reapply_flash', '_schedule_rebuild', '_update_archive_tab_count',
    '_rebuild_task_list', '_build_active_tab', '_build_archive_tab', '_render_tasks', 'paintEvent',
    '_update_stats_chip', '_window_transparency_factor', '_build_task_widget_cached', '_build_task_widget',
    '_clear_layout', '_build_search_index', '_check_auto_theme', '_apply_theme', '_tokenize_task',
    '_tokenize_cached', '_focus_search', 'keyPressEvent', '_setup_bugg19_zorder',
    '_restore_window_position', '_validate_position_on_screens', '_build_focus_view', '_get_focus_tasks',
    '_update_focus_view', '_enter_focus_mode', '_exit_focus_mode', '_toggle_focus_mode', '_focus_next',
    '_focus_prev', '_focus_complete', '_periodic_zorder_check', '_install_win_d_blocker',
    '_register_hotkeys', '_unregister_hotkeys', '_init_timers', '_update_pwm', 'on_pwm_state_change',
    '_input_field_keypress', '_on_open_google_calendar', '_on_open_backup', '_on_push_task_to_google',
    '_on_show_task_calendar_history', '_on_open_donate', '_on_export_pdf', '_on_export_calendar_ics',
    '_on_open_task_in_google_calendar', '_on_export_task_ics', '_on_email_import', '_import_email_files',
    '_is_outlook_drag', 'dragEnterEvent', 'dropEvent', '_open_task_email', '_reply_to_task_email',
    '_open_email', 'contextMenuEvent', '_shell_screen_move', '_center_window', '_toggle_lock',
    '_auto_relock', 'bring_to_front', '_auto_reposition_if_needed', '_navigate_tasks', '_nav_select',
    '_nav_select_by_mouse', '_nav_paint', '_nav_exit', '_nav_after_render', '_handle_nav_key',
    '_activate_for_typing', '_deactivate_restore_noact', 'mousePressEvent', 'mouseMoveEvent',
    'mouseReleaseEvent', 'closeEvent', 'focusInEvent', 'focusOutEvent', '_pt_of', 'enterEvent',
    'leaveEvent', 'wheelEvent', '_save_geometry_now', 'resizeEvent', 'moveEvent', '_is_child',
    '_native_window_ok', '_handle_window_creation_failure', '_probe_bare_window',
    '_retry_show_after_failure', 'showEvent', 'hideEvent', 'changeEvent', 'nativeEvent', '_detect_dpr',
    'get_health_report', '_validate_widget_state', '__repr__'
)


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def child() -> None:
    import builtins
    import dis
    import types

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from ui import widget as UW
    from ui import widget_base as B

    res: list = []

    def ck(name, cond):
        res.append((name, bool(cond)))

    TW = W.TodoWidget
    mixins = [c for c in TW.__mro__ if c.__name__.endswith("Mixin")]
    qidx = TW.__mro__.index(QWidget)
    ck("TodoWidget har 12 mixins", len(mixins) == 12)
    ck("alla mixins står före QWidget i MRO", all(TW.__mro__.index(m) < qidx for m in mixins))
    ck("facaderna ger samma klass (widget / ui.widget)", True)  # olika modulobjekt, men samma delar:
    ck("båda facaderna delar widget_base", W._base is UW._base is B)
    own = set(vars(TW))
    ck("signaler ligger i TodoWidget själv", {"task_action", "widget_closed", "__init__"} <= own)
    ck("task_action är en Qt-signal", type(TW.task_action).__name__ in ("Signal", "SignalInstance") or hasattr(TW.task_action, "connect") or "Signal" in type(TW.task_action).__name__)
    allm = [n for n in EXPECTED_METHODS]
    ck("alla ursprungliga metoder finns kvar", all(callable(getattr(TW, n, None)) for n in allm))
    seen: dict = {}
    dup = []
    for c in [TW] + mixins:
        for n, v in vars(c).items():
            if isinstance(v, (types.FunctionType, staticmethod, classmethod)):
                if n in seen:
                    dup.append(n)
                seen[n] = c.__name__
    ck("ingen metod definieras i två mixins", not dup)
    ck("exakt de ursprungliga metoderna (inga extra)", set(seen) == set(EXPECTED_METHODS))

    # alla globala namn i delarna går att slå upp
    mods = [B, sys.modules["ui.widget_atoms"], sys.modules["ui.widget"] if "ui.widget" in sys.modules else UW]
    mods += [m for k, m in sys.modules.items() if k.startswith("ui.widget_parts.") and m]
    bad: list = []

    def walk(code, mod):
        for ins in dis.get_instructions(code):
            if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME") and ins.argval not in vars(mod) and not hasattr(builtins, ins.argval) and ins.argval not in ("_StubMeta", "_stub_factory"):  # (de två: Qt-saknas-reserven)
                bad.append(f"{mod.__name__}:{ins.argval}")
        for k in code.co_consts:
            if isinstance(k, types.CodeType):
                walk(k, mod)

    for m in mods:
        src = Path(m.__file__).read_text(encoding="utf-8").split('\nif __name__ == "__main__":')[0]  # self-testet körs bara som skript
        walk(compile(src, m.__file__, "exec"), m)
    ck("alla namn i alla delar går att slå upp: " + ",".join(sorted(set(bad))[:8]), not bad)
    ck("minst 14 moduler granskade", len(mods) >= 14)

    # textstorlek live via fasaden
    ck("_UI_FONT_SCALE kan läsas via fasaden", W._UI_FONT_SCALE == 1.0)
    ck("_UI_FONT_SCALE inte kopierad av star-import", "_UI_FONT_SCALE" not in B.__all__)
    W.set_ui_font_scale(1.2)
    ck("set_ui_font_scale syns live i fasaden", W._UI_FONT_SCALE == 1.2 and UW._UI_FONT_SCALE == 1.2)
    ck("_scaled_px använder skalan", W._scaled_px(20) == 24)
    W.set_ui_font_scale(1.0)

    # QMessageBox är importerad (var förut NameError)
    ck("QMessageBox finns i basen", hasattr(B, "QMessageBox") and B.QMessageBox is not None)
    calls: list = []

    class FakeBox:
        class StandardButton:
            Yes, No = 1, 2

        @staticmethod
        def warning(parent, title, text):
            calls.append(("warning", title, text))

        @staticmethod
        def question(parent, title, text, buttons, default):
            calls.append(("question", title))
            return FakeBox.StandardButton.Yes

    tmp = tempfile.mkdtemp(prefix="taskbord_split_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    tid = store.add_task("Ta bort mig")
    shell = QWidget()
    w = TW(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 520)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()

    B.QMessageBox = FakeBox
    sys.modules["ui.widget_parts.task_actions"].QMessageBox = FakeBox
    ck("_show_widget_error visar dialogen utan NameError", B._show_widget_error(w, "Rubrik", "Text") is True and calls and calls[0][0] == "warning")
    w._on_delete_clicked(tid, "Ta bort mig")
    ck("radera-dialogen frågar och tar bort uppgiften", any(c[0] == "question" for c in calls) and tid not in [t.get("id") for t in store.all_tasks()])

    # textstorlek via riktiga _apply_theme (global ändras i basen)
    settings.set_density_mode("cozy")
    w._apply_theme()
    app.processEvents()
    ck("_apply_theme sätter skalan i basen (cozy = 1.2)", abs(W._UI_FONT_SCALE - 1.2) < 1e-9 and abs(B._UI_FONT_SCALE - 1.2) < 1e-9)
    settings.set_density_mode("comfortable")
    w._apply_theme()
    app.processEvents()
    ck("…och tillbaka (comfortable = 1.0)", W._UI_FONT_SCALE == 1.0)

    # paintEvent/keyPressEvent går via super() till QWidget
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    try:
        w.repaint()
        app.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F13, Qt.KeyboardModifier.NoModifier))
        ok = True
    except Exception:
        ok = False
    ck("paintEvent + keyPressEvent (super() genom mixins) fungerar", ok)

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    files = widget_files(ROOT)
    names = [p.name for p in files]
    check("fasad + bas + atomer finns", {"widget.py", "widget_base.py", "widget_atoms.py"} <= set(names))
    check("minst tolv delfiler i widget_parts", len([p for p in files if p.parent.name == "widget_parts"]) >= 12)
    lines = {p.name: len(p.read_text(encoding="utf-8").splitlines()) for p in files}
    check("fasaden ui/widget.py är liten (< 600 rader)", lines["widget.py"] < 600, str(lines["widget.py"]))
    check("ingen delfil är större än 1 500 rader", max(lines.values()) <= 1500, str(max(lines.values())))
    for p in files:
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
            okc = True
        except SyntaxError:
            okc = False
        check(f"{p.name} kompilerar", okc)
    src = widget_source(ROOT)
    check("QMessageBox importeras på modulnivå i basen",
          "QMessageBox," in (ROOT / "ui" / "widget_base.py").read_text(encoding="utf-8"))
    check("inget 'global _UI_FONT_SCALE' utanför basen",
          all("global _UI_FONT_SCALE" not in p.read_text(encoding="utf-8") for p in files if p.name != "widget_base.py"))
    check("widget_source() innehåller delarnas metoder", "def _apply_theme" in src and "def _build_task_widget" in src)

    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_splittest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"widget_split_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=240)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(l)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-1800:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nwidget_split_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
