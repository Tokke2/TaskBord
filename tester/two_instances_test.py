"""Test: två processer mot samma uppgiftsfiler får inte skriva över varandras uppgifter."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _src import app_files, app_source  # noqa: E402
sys.path.insert(0, str(ROOT / "core"))

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


from core.store import TaskStore  # noqa: E402
from core.single_instance import DataDirLock  # noqa: E402


def titles(st):
    return sorted(t["title"] for t in st.active_tasks())


with tempfile.TemporaryDirectory() as d:
    seed = TaskStore(data_dir_override=d)
    seed.add_task("gammal")
    seed.add_task("tas bort")
    seed.save()

    a = TaskStore(data_dir_override=d)   # "fönster A"
    b = TaskStore(data_dir_override=d)   # "fönster B" (andra processen)
    check("båda läste samma start", titles(a) == titles(b) == ["gammal", "tas bort"])

    # B får en mail-uppgift och sparar; A sparar sedan sin egen ändring
    b.add_task("mail från B")
    b.save()
    a.add_task("skapad i A")
    a.save()
    on_disk = titles(TaskStore(data_dir_override=d))
    check("A skrev INTE över B:s uppgift", "mail från B" in on_disk)
    check("A:s egen uppgift finns", "skapad i A" in on_disk)
    check("A såg B:s uppgift i minnet", "mail från B" in titles(a))

    # sync_external hämtar in det som A sparade, utan att B själv sparar
    n = b.sync_external()
    check("B hämtar in A:s uppgift via sync_external", n == 1 and "skapad i A" in titles(b))
    check("ingen dubblett vid andra sync", b.sync_external() == 0)

    # A tar bort en uppgift; B:s senare save återskapar INTE A:s borttagning i A
    tid = next(t["id"] for t in a.active_tasks() if t["title"] == "tas bort")
    a.remove_task(tid)
    b.add_task("mer från B")
    b.save()           # B har fortfarande 'tas bort' i minnet → filen innehåller den
    a.save()           # A: 'tas bort' är känd + borttagen → ska inte komma tillbaka hos A
    check("A:s borttagning återskapas inte i A:s minne", "tas bort" not in titles(a))
    check("B:s nya uppgift hämtades till A", "mer från B" in titles(a))

# Arkiv: arkiverad uppgift får inte dubbleras av merge
with tempfile.TemporaryDirectory() as d:
    s1 = TaskStore(data_dir_override=d)
    t1 = s1.add_task("klar sak")
    s1.save()
    s2 = TaskStore(data_dir_override=d)
    s2.add_task("ny")
    s2.save()
    s1.toggle_task(t1) if hasattr(s1, "toggle_task") else None
    s1.save()
    allids = [t["id"] for t in s1.active_tasks()] + [t["id"] for t in s1.archive_tasks()]
    check("inga dubbletter av id efter merge", len(allids) == len(set(allids)))

# Datamapps-lås
with tempfile.TemporaryDirectory() as d:
    l1 = DataDirLock(d)
    check("första låset tas", l1.acquire())
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from core.single_instance import DataDirLock\n"
        "sys.exit(0 if DataDirLock(%r).acquire() else 3)\n" % (str(ROOT), d)
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True)
    check("andra processen nekas", r.returncode == 3)
    l1.release()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True)
    check("efter release går det att ta låset", r.returncode == 0)

main = app_source(ROOT)
check("main.pyw tar datamapps-lås", "DataDirLock(JS_DIR)" in main)
check("main.pyw synkar externa ändringar", "self._sync_external_store" in main)

print(f"\ntwo_instances_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
