"""
mail_open_test.py — "Öppna mejlet" på uppgifter som kommer från mail.

Logik (core/email_import): hitta originalfilen även när den sparade sökvägen pekar fel (appmappen
flyttad), öppna den, annars returnera False så att kortet kan visa den sparade mailtexten.
Plus: de nya mail-fälten överlever omstart i TaskStore, och MailViewDialog (riktig Qt, offscreen,
egen process med --dialog) visar avsändare/ämne/text.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core", "ui"):
    sys.path.insert(0, str(ROOT / sub))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


if "--dialog" in sys.argv:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.mail_view_dialog import MailViewDialog
    task = {"id": "abc12345", "title": "Svara Anna", "email_from": "Anna <anna@example.com>",
            "email_subject": "Rapport", "email_body": "Hej!\nKan du skicka rapporten?",
            "email_message_id": "<m1@example.com>", "email_date": "2026-10-15"}
    d = MailViewDialog(task, None, "Originalfilen finns inte kvar")
    check("dialog: brödtext", "rapporten" in d.body.toPlainText())
    check("dialog: läsbar men inte redigerbar", d.body.isReadOnly())
    check("dialog: rubrik har ämnet", "Rapport" in d.windowTitle())
    check("dialog: Message-ID-knapp syns", not d.btn_mid.isHidden())
    d.btn_text.click()
    check("dialog: kopiera texten", "rapporten" in app.clipboard().text())
    d.btn_mid.click()
    check("dialog: kopiera Message-ID", app.clipboard().text() == "<m1@example.com>")
    d2 = MailViewDialog({"id": "x", "title": "T", "email_body": "bara text"}, None)
    check("dialog: utan Message-ID är knappen dold", d2.btn_mid.isHidden())
    d3 = MailViewDialog({"id": "x", "title": "T"}, None)
    check("dialog: utan text säger det", "ingen text" in d3.body.toPlainText())
    print(f"DIALOG {ok} {fail}")
    sys.exit(1 if fail else 0)

import core.email_import as ei  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="taskbord_mailopen_"))
data = tmp / "js"
(data / "emails").mkdir(parents=True)
eml = data / "emails" / "abc12345.eml"
eml.write_text("From: a@b\nSubject: x\n\nhej\n", encoding="utf-8")

check("has_email: ingenting", not ei.has_email({"id": "1", "title": "x"}))
for k in ("email_path", "email_message_id", "email_subject", "email_from", "email_body"):
    check(f"has_email: {k}", ei.has_email({k: "x"}))

# 1. sparad sökväg giltig
t = {"id": "abc12345", "email_path": str(eml)}
check("find: giltig sökväg", ei.find_email_file(t, data) == eml)
# 2. appmappen flyttad: absolut Windows-sökväg som inte finns → filnamn i emails\
t = {"id": "abc12345", "email_path": r"D:\Program\todo\js\emails\abc12345.eml"}
check("find: flyttad mapp (Windows-sökväg) → hittas via filnamn", ei.find_email_file(t, data) == eml)
t = {"id": "abc12345", "email_path": "/gammal/plats/emails/abc12345.eml"}
check("find: flyttad mapp (POSIX-sökväg)", ei.find_email_file(t, data) == eml)
# 3. ingen email_path alls men fil på uppgifts-id
check("find: bara uppgifts-id", ei.find_email_file({"id": "abc12345", "email_subject": "x"}, data) == eml)
# 4. saknas helt
check("find: saknas → None", ei.find_email_file({"id": "zzzzzzzz", "email_path": "/nej/x.eml"}, data) is None)
check("find: utan data_dir och trasig sökväg → None", ei.find_email_file({"id": "abc12345", "email_path": "/nej.eml"}) is None)
check("find: tom uppgift", ei.find_email_file({}, data) is None)
# .msg på id
msg = data / "emails" / "def67890.msg"
msg.write_bytes(b"x")
check("find: .msg på id", ei.find_email_file({"id": "def67890"}, data) == msg)

# 5. open_task_email anropar open_email med rätt fil
calls = []
orig = ei.open_email
ei.open_email = lambda p: calls.append(p) or True
try:
    r = ei.open_task_email({"id": "abc12345", "email_path": "/flyttad/abc12345.eml"}, data)
    check("open_task_email: öppnar den hittade filen", r is True and calls == [str(eml)], str(calls))
    calls.clear()
    r = ei.open_task_email({"id": "zzzzzzzz", "email_path": "/nej.eml"}, data)
    check("open_task_email: ingen fil → False, inget öppnas", r is False and not calls)
finally:
    ei.open_email = orig

# 6. mail-fälten överlever omstart (TaskStore)
from core.store import TaskStore  # noqa: E402
sd = tmp / "store"
s = TaskStore(data_dir_override=sd)
tid = s.add_task(title="Mailuppgift")
for k, v in (("email_from", "Anna <a@x>"), ("email_subject", "Rapport"), ("email_body", "text"),
             ("email_message_id", "<m@x>"), ("email_date", "2026-10-15"), ("email_to", "jag@x"),
             ("email_attachments", "a.pdf")):
    s.set_task_metadata(tid, k, v)
s.save() if hasattr(s, "save") else None
s2 = TaskStore(data_dir_override=sd)
t2 = [t for t in s2.active_tasks() if t["id"] == tid]
check("store: uppgiften laddades om", len(t2) == 1)
if t2:
    for k in ("email_from", "email_subject", "email_body", "email_message_id",
              "email_date", "email_to", "email_attachments"):
        check(f"store: {k} överlever omstart", bool(t2[0].get(k)), str(t2[0].keys()))

# 7. dialogen (riktig Qt)
from _qtenv import qt_env  # noqa: E402
env, why = qt_env(tmp)
if env is None:
    print(f"  (dialogdelen hoppas över: {why})")
else:
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dialog"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("DIALOG ")]
    if line:
        _, n_ok, n_fail = line[-1].split()
        ok += int(n_ok)
        fail += int(n_fail)
        for l in r.stdout.splitlines():
            if l.strip().startswith("✗"):
                print(l)
    else:
        check("dialogprocessen körde klart", False, (r.stdout + r.stderr)[-600:])

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nmail_open_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
