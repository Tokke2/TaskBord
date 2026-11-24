#!/usr/bin/env python3
"""
links_attach_test.py — core/links.py, core/attachments.py och store-delen av länkar/bilagor.

Kör:  python tester/links_attach_test.py
Titelhämtning testas mot en lokal http.server (inget riktigt nätverk). Ingen Qt behövs.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import attachments as att  # noqa: E402
from core import links  # noqa: E402
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name} {extra}")


PAGES = {
    "/plain": ("text/html; charset=utf-8", "<html><head><title>  Hej &amp; välkommen\n till sidan </title></head></html>".encode()),
    "/latin": ("text/html; charset=iso-8859-1", "<title>Blåbär</title>".encode("latin-1")),
    "/og": ("text/html", b'<head><meta property="og:title" content="Delad titel"></head>'),
    "/notitle": ("text/html", b"<html><body>inget</body></html>"),
    "/pdf": ("application/pdf", b"%PDF-1.4 <title>fel</title>"),
    "/metacs": ("text/html", b'<meta charset="windows-1252"><title>Caf\xe9</title>'),
    "/big": ("text/html", b"<title>Stor sida</title>" + b"x" * 600_000),
}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/plain")
            self.end_headers()
            return
        if self.path == "/redir-ftp":
            self.send_response(302)
            self.send_header("Location", "ftp://example.com/x")
            self.end_headers()
            return
        if self.path == "/slow":
            import time
            time.sleep(3)
        ct, body = PAGES.get(self.path, ("text/html", b""))
        if self.path == "/404":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    # ---- URL-hjälp ----------------------------------------------------------
    check("extract: https + www + skiljetecken",
          links.extract_urls("se https://a.se/x(1).html, och www.b.com/p?q=1. samt (https://c.org/z)")
          == ["https://a.se/x(1).html", "https://www.b.com/p?q=1", "https://c.org/z"])
    check("extract: dubbletter tas bort", links.extract_urls("https://a.se https://a.se") == ["https://a.se"])
    check("extract: ingen URL", links.extract_urls("köp mjölk 15/3") == [])
    check("extract: ftp/javascript/file avvisas", links.extract_urls("ftp://x.se javascript:alert(1) file:///c:/x") == [])
    check("normalize: värd utan punkt avvisas", links.normalize("http://intranet") is None)
    check("normalize: localhost tillåts", links.normalize("http://localhost:8080/x") == "http://localhost:8080/x")
    check("normalize: för lång URL avvisas", links.normalize("https://a.se/" + "x" * 2100) is None)
    check("strip_urls", links.strip_urls("köp mjölk https://a.se/x och www.b.com") == "köp mjölk och")
    check("strip_urls: bara URL → tomt", links.strip_urls("https://a.se/x") == "")
    check("display_title: värdnamn utan www", links.display_title("https://www.Exempel.se/a/b") == "exempel.se")

    # ---- titel ur HTML ------------------------------------------------------------
    check("parse_title: unescape + whitespace", links.parse_title(PAGES["/plain"][1], "text/html; charset=utf-8") == "Hej & välkommen till sidan")
    check("parse_title: og:title som reserv", links.parse_title(PAGES["/og"][1]) == "Delad titel")
    check("parse_title: latin-1 via header", links.parse_title(PAGES["/latin"][1], "text/html; charset=iso-8859-1") == "Blåbär")
    check("parse_title: charset via meta", links.parse_title(PAGES["/metacs"][1]) == "Café")
    check("parse_title: titel saknas", links.parse_title(PAGES["/notitle"][1]) == "")
    check("parse_title: titeln kortas", len(links.parse_title(b"<title>" + b"a" * 500 + b"</title>")) == links.MAX_TITLE_LEN)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        check("fetch_title: vanlig sida", links.fetch_title(base + "/plain") == "Hej & välkommen till sidan")
        check("fetch_title: följer redirect", links.fetch_title(base + "/redir") == "Hej & välkommen till sidan")
        check("fetch_title: redirect till ftp avvisas", links.fetch_title(base + "/redir-ftp") == "")
        check("fetch_title: inte HTML → tom", links.fetch_title(base + "/pdf") == "")
        check("fetch_title: 404 → tom (kastar inte)", links.fetch_title(base + "/404") == "")
        check("fetch_title: stor sida läses bara delvis men titeln hittas", links.fetch_title(base + "/big") == "Stor sida")
        check("fetch_title: timeout → tom", links.fetch_title(base + "/slow", timeout=0.5) == "")
        check("fetch_title: ogiltig URL → tom", links.fetch_title("javascript:alert(1)") == "")
    finally:
        srv.shutdown()
    check("fetch_title: ingen server → tom (kastar inte)", links.fetch_title(f"http://127.0.0.1:{port}/x", timeout=1) == "")

    # ---- attachments -------------------------------------------------------------------
    check("safe_name: sökvägsdelar bort", att.safe_name("../../etc/pa:ss?.txt") == "pa_ss_.txt")
    check("safe_name: reserverat Windows-namn", att.safe_name("CON.txt") == "_CON.txt")
    check("safe_name: tomt → fil", att.safe_name("   ") == "fil")
    check("safe_name: ändelsen behålls vid långt namn", att.safe_name("a" * 300 + ".pdf").endswith(".pdf") and len(att.safe_name("a" * 300 + ".pdf")) <= 120)
    check("is_dangerous", att.is_dangerous("x.EXE") and att.is_dangerous("a.ps1") and not att.is_dangerous("a.pdf"))

    tmp = Path(tempfile.mkdtemp(prefix="tb_att_"))
    try:
        data = tmp / "data"
        src = tmp / "källa" / "Rapport åäö.txt"
        src.parent.mkdir()
        src.write_text("hej", encoding="utf-8")
        m = att.copy_in(data, "abc12345", src)
        check("copy_in: metadata", m["name"] == "Rapport åäö.txt" and m["file"] == "attachments/abc12345/Rapport åäö.txt" and m["size"] == 3)
        check("copy_in: filen ligger i datamappen", (data / m["file"]).read_text(encoding="utf-8") == "hej")
        check("copy_in: originalet orört", src.exists())
        m2 = att.copy_in(data, "abc12345", src)
        check("copy_in: samma namn → (2)", m2["file"].endswith("Rapport åäö (2).txt") and (data / m2["file"]).is_file())
        check("exists/resolve", att.exists(data, m["file"]) and att.resolve(data, "attachments/abc12345/../../../x") is None)
        check("resolve: absolut sökväg utanför avvisas", att.resolve(data, str(tmp / "källa" / "Rapport åäö.txt")) is None)
        for bad_id in ("../x", "a/b", "", "a" * 70):
            try:
                att.copy_in(data, bad_id, src)
                check(f"copy_in: ogiltigt id {bad_id!r} avvisas", False)
            except att.AttachmentError:
                check(f"copy_in: ogiltigt id {bad_id!r} avvisas", True)
        try:
            att.copy_in(data, "abc12345", tmp / "finns-inte.txt")
            check("copy_in: saknad fil → AttachmentError", False)
        except att.AttachmentError:
            check("copy_in: saknad fil → AttachmentError", True)
        old = att.MAX_ATTACH_BYTES
        att.MAX_ATTACH_BYTES = 2
        try:
            att.copy_in(data, "abc12345", src)
            check("copy_in: för stor fil avvisas", False)
        except att.AttachmentError as e:
            check("copy_in: för stor fil avvisas", "för stor" in str(e))
        att.MAX_ATTACH_BYTES = old
        check("delete_file", att.delete_file(data, m2["file"]) and not (data / m2["file"]).exists())
        check("delete_file: utanför bilagemappen nekas", not att.delete_file(data, "../källa/Rapport åäö.txt") and src.exists())
        check("delete_task_files", att.delete_task_files(data, "abc12345") and not (data / "attachments" / "abc12345").exists())
        check("delete_task_files: ogiltigt id → False, inget rörs", not att.delete_task_files(data, "..") and (data).exists())

        # ---- store: länkar -----------------------------------------------------------
        sd = tmp / "store"
        s = TaskStore(data_dir_override=str(sd))
        t = s.add_task("Uppgift")
        check("add_link", s.add_link(t, "https://a.se/x", "Titel"))
        check("add_link: dubblett nekas", not s.add_link(t, "https://a.se/x", "Annan"))
        check("add_link: ftp nekas", not s.add_link(t, "ftp://a.se/x", ""))
        check("add_link: okänd uppgift nekas", not s.add_link("finns-inte", "https://a.se", ""))
        check("set_link_title", s.set_link_title(t, "https://a.se/x", "Ny titel") and s.find_task(t)["links"][0]["title"] == "Ny titel")
        check("set_link_title: tom titel ignoreras", not s.set_link_title(t, "https://a.se/x", "  "))
        for i in range(30):
            s.add_link(t, f"https://b.se/{i}", "")
        check("max antal länkar", len(s.find_task(t)["links"]) == 20)

        # ---- store: bilagor ---------------------------------------------------------------
        t2 = s.add_task("Med fil")
        meta = att.copy_in(s.data_dir, t2, src)
        check("add_attachment", s.add_attachment(t2, meta["name"], meta["file"], meta["size"], meta["added"]))
        check("add_attachment: dubblett nekas", not s.add_attachment(t2, meta["name"], meta["file"], meta["size"]))
        check("add_attachment: sökväg utanför attachments/ nekas", not s.add_attachment(t2, "x", "../../x.txt", 1))
        check("add_attachment: absolut sökväg nekas", not s.add_attachment(t2, "x", "/etc/passwd", 1))
        s.save()

        s2 = TaskStore(data_dir_override=str(sd))
        s2.load() if hasattr(s2, "load") else None
        f1, f2 = s2.find_task(t), s2.find_task(t2)
        check("länkar överlever omstart", f1 and len(f1.get("links", [])) == 20 and f1["links"][0] == {"url": "https://a.se/x", "title": "Ny titel"})
        check("bilagor överlever omstart", f2 and f2["attachments"][0]["file"] == meta["file"] and f2["attachments"][0]["size"] == 3)

        # trasig data i filen filtreras bort
        raw = json.loads((sd / "active.json").read_text(encoding="utf-8"))
        for tk in raw["tasks"]:
            if tk["id"] == t2:
                tk["links"] = ["x", {"url": "javascript:1"}, {"url": "https://ok.se"}, 5]
                tk["attachments"] = [{"file": "../evil"}, {"file": "attachments/q/ok.txt", "size": "stor"}, None]
        (sd / "active.json").write_text(json.dumps(raw), encoding="utf-8")
        s3 = TaskStore(data_dir_override=str(sd))
        g = s3.find_task(t2)
        check("trasiga länkar filtreras vid inläsning", g.get("links") == [{"url": "https://ok.se", "title": ""}])
        check("trasiga bilagor filtreras vid inläsning", g.get("attachments") and len(g["attachments"]) == 1 and g["attachments"][0]["size"] == 0)

        # ---- ta bort -----------------------------------------------------------------------
        s2.add_link(t2, "https://c.se", "")
        check("remove_link", s2.remove_link(t, "https://b.se/3") and all(x["url"] != "https://b.se/3" for x in s2.find_task(t)["links"]))
        check("remove_attachment tar bort filen", s2.remove_attachment(t2, meta["file"]) and not att.exists(s2.data_dir, meta["file"]))
        check("…och nyckeln när listan blir tom", "attachments" not in s2.find_task(t2))

        # ta bort aktiv uppgift städar bilagorna
        t3 = s2.add_task("Raderas")
        m3 = att.copy_in(s2.data_dir, t3, src)
        s2.add_attachment(t3, m3["name"], m3["file"], m3["size"])
        check("bilagan finns före borttagning", att.exists(s2.data_dir, m3["file"]))
        check("remove_task på aktiv uppgift fungerar", s2.remove_task(t3))
        check("…och raderar bilagorna", not (Path(s2.data_dir) / "attachments" / t3).exists())

        # arkiverad uppgift: länkar/bilagor kan läggas till men inte tas bort
        t4 = s2.add_task("Klar snart")
        m4 = att.copy_in(s2.data_dir, t4, src)
        s2.add_attachment(t4, m4["name"], m4["file"], m4["size"])
        s2.add_link(t4, "https://hist.se", "Hist")
        s2.archive_task(t4)
        check("arkiverad: lägga till länk går", s2.add_link(t4, "https://nyare.se", ""))
        check("arkiverad: ta bort länk nekas", not s2.remove_link(t4, "https://hist.se"))
        check("arkiverad: ta bort bilaga nekas, filen finns kvar", not s2.remove_attachment(t4, m4["file"]) and att.exists(s2.data_dir, m4["file"]))
        check("arkiverad: remove_task nekas, bilagan finns kvar", not s2.remove_task(t4) and att.exists(s2.data_dir, m4["file"]))

        # återkommande: nästa förekomst får länkar men INTE bilagor (filerna hör till den arkiverade)
        t5 = s2.add_task("Veckostäd", due_date="2026-10-20", recurring={"interval": "weekly"})
        m5 = att.copy_in(s2.data_dir, t5, src)
        s2.add_attachment(t5, m5["name"], m5["file"], m5["size"])
        s2.add_link(t5, "https://rec.se", "")
        before = {x["id"] for x in s2.active_tasks()}
        s2.toggle_task(t5) if hasattr(s2, "toggle_task") else None
        nxt = [x for x in s2.active_tasks() if x["id"] not in before]
        check("återkommande: ny förekomst skapades", len(nxt) == 1)
        if nxt:
            check("återkommande: länkar följer med", nxt[0].get("links") and nxt[0]["links"][0]["url"] == "https://rec.se")
            check("återkommande: bilagor följer INTE med", "attachments" not in nxt[0])
            s2.remove_task(nxt[0]["id"])
            check("återkommande: att radera nya förekomsten rör inte den arkiverades fil", att.exists(s2.data_dir, m5["file"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nlinks_attach_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    # PySide6 6.12 på Python 3.11 kan avbryta vid nedstängning ("bool_dealloc") — miljöbuggen ska inte
    # ändra testets resultat, så avsluta direkt.
    os._exit(_rc)
