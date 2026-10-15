"""
mail_reply_test.py — "Svara på mejlet": mottagare (Reply-To vinner), Re:-ämne, citat, mailto-länk
(procent-kodning, längdgräns), och att kortet har knapp + menyval.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core", "ui"):
    sys.path.insert(0, str(ROOT / sub))

from core import mail_reply as mr  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


tmp = Path(tempfile.mkdtemp())

# --- ämne ---
check("Re: läggs till", mr.reply_subject("Offert") == "Re: Offert")
check("Re: dubbleras inte", mr.reply_subject("Re: Offert") == "Re: Offert")
check("Sv: dubbleras inte", mr.reply_subject("SV: Offert") == "SV: Offert")
check("tomt ämne", mr.reply_subject("") == "Re:")
check("radbrytning i ämne plattas", "\n" not in mr.reply_subject("A\r\nB"))

# --- adress ---
check("namn + adress", mr._first_address("Anna Å <anna@example.com>") == "anna@example.com")
check("bara adress", mr._first_address("a@b.se") == "a@b.se")
check("ingen adress", mr._first_address("Anna") == "")
check("första av flera", mr._first_address("x <x@a.se>, y <y@a.se>") == "x@a.se")

# --- .eml med Reply-To ---
eml = tmp / "a.eml"
eml.write_bytes(
    ("From: Anna <anna@example.com>\r\nReply-To: Support <support@example.com>\r\n"
     "Subject: =?utf-8?q?Fr=C3=A5ga_om_rapport?=\r\nDate: Mon, 12 Oct 2026 10:00:00 +0200\r\n"
     "Content-Type: text/plain; charset=utf-8\r\n\r\nHej!\r\n\r\nKan du skicka rapporten?\r\nMvh Anna\r\n").encode())
task = {"id": "t1", "title": "Svara Anna", "email_from": "Anna <anna@example.com>"}
info = mr.reply_info(task, eml)
check("Reply-To vinner över From", info and info["to"] == "support@example.com", info)
check("kodat ämne avkodas + Re:", info and info["subject"] == "Re: Fråga om rapport", info)
check("citat har rubrik", info and "skrev Anna <anna@example.com>:" in info["body"], info)
check("citatrader börjar med > ", info and "> Kan du skicka rapporten?" in info["body"], info)
check("tomrad i citat blir bara >", info and "\n>\n" in info["body"], info)

# --- .eml utan Reply-To ---
eml2 = tmp / "b.eml"
eml2.write_bytes(b"From: Bosse <bosse@example.com>\r\nSubject: Re: Hej\r\n\r\nText\r\n")
i2 = mr.reply_info({"id": "t2"}, eml2)
check("From används utan Reply-To", i2 and i2["to"] == "bosse@example.com", i2)
check("Re: dubbleras inte i svar", i2 and i2["subject"] == "Re: Hej", i2)

# --- ingen fil: fall tillbaka på uppgiftens sparade fält ---
i3 = mr.reply_info({"id": "t3", "email_from": "Cissi <cissi@example.com>", "email_subject": "Möte",
                    "email_body": "Ses vi?", "email_date": "2026-10-13"}, None)
check("sparade fält räcker", i3 and i3["to"] == "cissi@example.com" and i3["subject"] == "Re: Möte", i3)
check("sparad text citeras", i3 and "> Ses vi?" in i3["body"] and "Den 2026-10-13 skrev" in i3["body"], i3)
check("trasig fil → sparade fält", mr.reply_info(
    {"id": "t4", "email_from": "d@example.com"}, tmp / "finns_inte.eml")["to"] == "d@example.com")
check("ingen adress alls → None", mr.reply_info({"id": "t5", "email_from": "Okänd"}, None) is None)
check("helt tom uppgift → None", mr.reply_info({}, None) is None)

# --- citatlängd ---
long_q = mr.quote_text("rad\n" * 2000, "A", "D")
check("citat kortas", long_q.count("rad") <= 301 and long_q.rstrip().endswith("[…]"), len(long_q))

# --- mailto ---
url = mr.build_mailto({"to": "a@example.com", "subject": "Re: Fråga & svar", "body": "\n\nHej åäö\n> citat"})
sp = urlsplit(url)
q = parse_qs(sp.query)
check("schema mailto", url.startswith("mailto:a@example.com?"), url[:40])
check("ämne kodas korrekt", q["subject"] == ["Re: Fråga & svar"], q)
check("& i ämnet förstör inte parametrarna", "body" in q, q)
check("brödtext med CRLF", q["body"][0] == "\r\n\r\nHej åäö\r\n> citat", q["body"])
check("inga råa mellanslag/radbrytningar i länken", " " not in url and "\n" not in url)
check("ingen '+' för mellanslag (Thunderbird tolkar den bokstavligt)", "+" not in url)
big = mr.build_mailto({"to": "a@example.com", "subject": "Re: X", "body": "\n\n" + "> " + "ord " * 3000})
check("jättelång mailto kortas under gränsen", len(big) <= mr.MAILTO_MAX_CHARS, len(big))
check("kortad länk har kvar mottagare och ämne", big.startswith("mailto:a@example.com?subject=Re%3A%20X"))
huge_subject = mr.build_mailto({"to": "a@example.com", "subject": "x" * 5000, "body": "hej"})
check("jättelångt ämne kraschar inte", huge_subject.startswith("mailto:"))

# --- öppna: kör rätt kommando, svälj fel ---
calls = []
orig_popen = mr.subprocess.Popen
mr.subprocess.Popen = lambda cmd, *a, **k: calls.append(cmd)
check("open_mailto (linux) anropar xdg-open", mr.open_mailto("mailto:a@b.se") and calls and calls[0][0] == "xdg-open", calls)
def boom(*a, **k):
    raise OSError("nej")
mr.subprocess.Popen = boom
mr.webbrowser.open = lambda u: False
check("open_mailto returnerar False vid fel", mr.open_mailto("mailto:a@b.se") is False)
mr.subprocess.Popen = orig_popen

# --- kortet har knapp + menyval (källkontroll) ---
w = (ROOT / "ui" / "widget.py").read_text(encoding="utf-8")
check("↩-knapp på kortet", 'QPushButton("↩", container)' in w)
check("menyval 'Svara på mejlet'", "↩️ Svara på mejlet" in w)
check("widget har _reply_to_task_email", "def _reply_to_task_email" in w)
check("INSTALLERA.bat kopierar core\\*.py (mail_reply.py följer med)",
      "core\\*.py" in (ROOT / "INSTALLERA.bat").read_text(encoding="utf-8", errors="replace"))

print(f"\nmail_reply: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
