"""Test: uppgifter som importeras från mail (annan tråd) ska aldrig 'försvinna' ur listan."""
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _src import app_files, app_source, widget_source  # noqa: E402
sys.path.insert(0, str(ROOT / "core"))

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


from core.store import TaskStore, _LRUCache  # noqa: E402

# 1) cache-token
c = _LRUCache()
t = c.token()
c.clear()
c.set("k", 1, t)
check("inaktuell token cachas inte", c.get("k")[0] is False)
c.set("k", 2, c.token())
check("aktuell token cachas", c.get("k") == (True, 2))
c.set("k2", 3)
check("utan token som förut", c.get("k2") == (True, 3))

with tempfile.TemporaryDirectory() as d:
    s = TaskStore(data_dir_override=d)
    s.add_task("första")

    # 2) deterministisk race: en uppgift läggs till mellan ögonblicksbild och cache-set
    real = s._filter_cache
    state = {"done": False}

    class _Racing:
        def __getattr__(self, n):
            return getattr(real, n)

        def set(self, key, value, token=None):
            if not state["done"] and key and key[0] == "filter":
                state["done"] = True
                s.add_task("från mail")  # "annan tråd" hinner före set()
            return real.set(key, value, token)

    s._filter_cache = _Racing()
    s.active_tasks_filtered(sort_by="pinned_first")
    s._filter_cache = real
    titles = [t["title"] for t in s.active_tasks_filtered(sort_by="pinned_first")]
    check("uppgift som lades till under beräkningen syns", "från mail" in titles)

    # 3) stress: bryggtråd importerar medan GUI-tråden ritar om hela tiden
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            s.active_tasks_filtered(sort_by="pinned_first")

    th = threading.Thread(target=reader)
    th.start()
    from core import mail_bridge as mb
    n = 40
    for i in range(n):
        mb.create_task_from_payload(
            s, Path(d),
            {"subject": f"Mail {i}", "from": f"a{i}@x.se", "body": "hej", "message_id": f"<m{i}@x>"},
            save=False,
        )
    stop.set()
    th.join()
    visible = s.active_tasks_filtered(sort_by="pinned_first")
    mails = [t for t in visible if str(t["title"]).startswith("Mail ")]
    check(f"alla {n} mail-uppgifter syns i filtrerade listan", len(mails) == n)
    check("filtrerad lista == alla aktiva", len(visible) == len(s.active_tasks()))

# 4) main.pyw / widget: trådsäkra handlers + samma renderare
main = app_source(ROOT)
check("store.changed från annan tråd köas", "_store_changed_in_thread = True" in main)
check("refresh använder _rebuild_task_list", 'hasattr(w, "_rebuild_task_list")' in main)
wid = widget_source(ROOT)
check("flash återapplieras efter ombyggnad", "self._reapply_flash()" in wid)

print(f"\nmail_race_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
