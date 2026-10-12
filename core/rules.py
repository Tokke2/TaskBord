# -*- coding: utf-8 -*-
"""
rules.py — NY v8 (2026-10-12): regler för uppgifter och inkommande mail.

En regel säger: *om* en uppgift (t.ex. från ett mail) matchar villkoren, *gör*
åtgärderna — sätt prioritet, lägg till taggar, sätt förfallodatum, nåla fast.

    Regler körs på tre sätt (samma regelmotor):
      • ▶ Kör alla regler nu   (knappen i widgeten / tray-menyn)
      • automatiskt 1 gång per timme (`due_for_hourly`)
      • på varje nytt mail som kommer in via Thunderbird-tillägget eller
        inkorgsmappen (`run_for_tasks`)

Reglerna är **idempotenta**: att köra dem igen ändrar bara det som faktiskt
skiljer sig, så en timkörning gör ingenting om allt redan stämmer. Reglerna
körs i listans ordning; för prioritet vinner den sista matchande regeln,
för förfallodatum den första (ett datum som redan finns skrivs aldrig över).

Sparas i `<data>/rules.json` (JSON, atomiskt). Bara stdlib.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TaskBord.rules")
LOG_PREFIX = "[RULES]"

RULES_FILENAME = "rules.json"
HOURLY_INTERVAL_SEC = 3600
MAX_RULES = 200
MAX_VALUE_LEN = 300

FIELDS: Dict[str, str] = {
    "title": "Titel",
    "from": "Avsändare (mail)",
    "subject": "Ämne (mail)",
    "body": "Mailtext",
    "tags": "Taggar",
    "priority": "Prioritet",
    "note": "Anteckning",
}
OPS: Dict[str, str] = {
    "contains": "innehåller",
    "not_contains": "innehåller inte",
    "equals": "är exakt",
    "startswith": "börjar med",
    "endswith": "slutar med",
    "regex": "matchar uttrycket",
}
VALID_PRIORITIES = ("none", "low", "medium", "high")


# --------------------------------------------------------------------------
# Regelns form
# --------------------------------------------------------------------------
def new_rule_id() -> str:
    return uuid.uuid4().hex[:8]


def normalize_rule(raw: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Städa och kontrollera en regel. Returnerar (regel, problem).

    `regel` är None om reglen inte går att använda; `problem` är svenska
    meningar som kan visas för användaren.
    """
    problems: List[str] = []
    if not isinstance(raw, dict):
        return None, ["Regeln har fel format."]

    name = str(raw.get("name") or "").strip()[:80]
    if not name:
        problems.append("Regeln behöver ett namn.")

    mode = str(raw.get("match") or "all").lower()
    if mode not in ("all", "any"):
        mode = "all"

    conds: List[Dict[str, str]] = []
    for c in raw.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        field = str(c.get("field") or "").lower()
        op = str(c.get("op") or "contains").lower()
        value = str(c.get("value") or "").strip()[:MAX_VALUE_LEN]
        if field not in FIELDS:
            problems.append(f"Okänt fält: {field or '(tomt)'}.")
            continue
        if op not in OPS:
            problems.append(f"Okänt villkor: {op}.")
            continue
        if not value:
            problems.append(f"Villkoret för “{FIELDS[field]}” saknar värde.")
            continue
        if op == "regex":
            try:
                re.compile(value)
            except re.error as e:
                problems.append(f"Ogiltigt uttryck “{value}”: {e}")
                continue
        conds.append({"field": field, "op": op, "value": value})
    if not conds:
        problems.append("Regeln behöver minst ett villkor.")

    acts_in = raw.get("actions") if isinstance(raw.get("actions"), dict) else {}
    actions: Dict[str, Any] = {}
    prio = str(acts_in.get("priority") or "").lower()
    if prio:
        if prio in VALID_PRIORITIES:
            actions["priority"] = prio
        else:
            problems.append(f"Okänd prioritet: {prio}.")
    tags_in = acts_in.get("add_tags") or []
    if isinstance(tags_in, str):
        tags_in = [t for t in re.split(r"[,;]", tags_in)]
    tags = []
    for t in tags_in:
        t = str(t).strip().lstrip("#")[:40].lower()
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    if tags:
        actions["add_tags"] = tags[:10]
    if acts_in.get("due_in_days") not in (None, ""):
        try:
            days = int(acts_in["due_in_days"])
            if 0 <= days <= 3650:
                actions["due_in_days"] = days
            else:
                problems.append("Förfallodatum måste vara 0–3650 dagar fram.")
        except (TypeError, ValueError):
            problems.append("Förfallodatum måste anges i hela dagar.")
    if acts_in.get("pin"):
        actions["pin"] = True
    if not actions:
        problems.append("Regeln behöver minst en åtgärd.")

    if problems:
        return None, problems
    return {
        "id": str(raw.get("id") or new_rule_id()),
        "name": name,
        "enabled": bool(raw.get("enabled", True)),
        "match": mode,
        "mail_only": bool(raw.get("mail_only", False)),
        "conditions": conds,
        "actions": actions,
    }, []


def describe_rule(rule: Dict[str, Any]) -> str:
    """Läsbar svensk beskrivning, t.ex. “Om Avsändare innehåller ‘faktura’ → prioritet hög”."""
    delar = [f"{FIELDS.get(c['field'], c['field'])} {OPS.get(c['op'], c['op'])} “{c['value']}”"
             for c in rule.get("conditions", [])]
    sep = " och " if rule.get("match", "all") == "all" else " eller "
    a = rule.get("actions", {})
    ut = []
    if a.get("priority"):
        ut.append(f"prioritet {a['priority']}")
    if a.get("add_tags"):
        ut.append("taggar " + ", ".join(a["add_tags"]))
    if a.get("due_in_days") is not None:
        ut.append(f"förfaller om {a['due_in_days']} dagar")
    if a.get("pin"):
        ut.append("nåla fast")
    return f"Om {sep.join(delar)} → {', '.join(ut)}"


# --------------------------------------------------------------------------
# Matchning
# --------------------------------------------------------------------------
def _field_values(task: Dict[str, Any], field: str) -> List[str]:
    """Textvärden för ett fält (taggar blir flera värden)."""
    if field == "tags":
        return [str(t) for t in (task.get("tags") or [])]
    key = {"from": "email_from", "subject": "email_subject", "body": "email_body",
           "title": "title", "priority": "priority", "note": "note"}[field]
    return [str(task.get(key) or "")]


def _cond_matches(task: Dict[str, Any], cond: Dict[str, str]) -> bool:
    op, needle = cond["op"], cond["value"]
    vals = _field_values(task, cond["field"])
    n = needle.lower()

    def one(v: str) -> bool:
        h = v.lower()
        if op == "contains":
            return n in h
        if op == "equals":
            return h == n
        if op == "startswith":
            return h.startswith(n)
        if op == "endswith":
            return h.endswith(n)
        if op == "regex":
            try:
                return re.search(needle, v, re.IGNORECASE) is not None
            except re.error:
                return False
        return False

    if op == "not_contains":  # ingen av värdena får innehålla texten
        return not any(n in v.lower() for v in vals)
    return any(one(v) for v in vals)


def is_mail_task(task: Dict[str, Any]) -> bool:
    return bool(task.get("email_from") or task.get("email_subject")
                or task.get("email_path") or task.get("email_message_id"))


def task_matches(rule: Dict[str, Any], task: Dict[str, Any]) -> bool:
    """Matchar uppgiften regelns villkor (och mail-begränsningen)?"""
    if rule.get("mail_only") and not is_mail_task(task):
        return False
    conds = rule.get("conditions") or []
    if not conds:
        return False
    results = (_cond_matches(task, c) for c in conds)
    return all(results) if rule.get("match", "all") == "all" else any(results)


# --------------------------------------------------------------------------
# Lagring
# --------------------------------------------------------------------------
def _now_iso() -> str:
    return _datetime.now(_timezone.utc).isoformat()


def rules_path(data_dir: Any) -> Path:
    return Path(str(data_dir)) / RULES_FILENAME


class RuleSet:
    """Reglerna på disk (`rules.json`) + tidpunkt/resultat för senaste körning."""

    def __init__(self, path: Any) -> None:
        self.path = Path(str(path))
        self._lock = threading.RLock()
        self._rules: List[Dict[str, Any]] = []
        self._meta: Dict[str, Any] = {}
        self.load()

    # -- disk ---------------------------------------------------------------
    def load(self) -> int:
        with self._lock:
            self._rules, self._meta = [], {}
            try:
                if self.path.is_file() and self.path.stat().st_size > 0:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
                        for raw in data.get("rules") or []:
                            rule, _p = normalize_rule(raw)
                            if rule:
                                self._rules.append(rule)
                            else:
                                logger.warning(f"{LOG_PREFIX} hoppar över ogiltig regel i filen")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte läsa {self.path.name}: {type(e).__name__}")
            return len(self._rules)

    def save(self) -> bool:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
                payload = {"_meta": dict(self._meta, version=1), "rules": self._rules}
                tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(str(tmp), str(self.path))
                return True
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara regler: {e}")
                return False

    # -- regler ---------------------------------------------------------------
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [json.loads(json.dumps(r)) for r in self._rules]

    def enabled(self) -> List[Dict[str, Any]]:
        return [r for r in self.all() if r.get("enabled")]

    def get(self, rule_id: str) -> Optional[Dict[str, Any]]:
        return next((r for r in self.all() if r["id"] == rule_id), None)

    def upsert(self, raw: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """Lägg till eller ersätt en regel (på id). Returnerar (regel, problem)."""
        rule, problems = normalize_rule(raw)
        if rule is None:
            return None, problems
        with self._lock:
            for i, r in enumerate(self._rules):
                if r["id"] == rule["id"]:
                    self._rules[i] = rule
                    break
            else:
                if len(self._rules) >= MAX_RULES:
                    return None, [f"Max {MAX_RULES} regler."]
                self._rules.append(rule)
            self.save()
        return rule, []

    def remove(self, rule_id: str) -> bool:
        with self._lock:
            n = len(self._rules)
            self._rules = [r for r in self._rules if r["id"] != rule_id]
            if len(self._rules) != n:
                self.save()
                return True
            return False

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        with self._lock:
            for r in self._rules:
                if r["id"] == rule_id:
                    r["enabled"] = bool(enabled)
                    self.save()
                    return True
            return False

    def move(self, rule_id: str, delta: int) -> bool:
        """Flytta en regel i ordningen (ordningen avgör vilken regel som vinner)."""
        with self._lock:
            idx = next((i for i, r in enumerate(self._rules) if r["id"] == rule_id), -1)
            ny = idx + delta
            if idx < 0 or not (0 <= ny < len(self._rules)):
                return False
            self._rules[idx], self._rules[ny] = self._rules[ny], self._rules[idx]
            self.save()
            return True

    # -- körningar --------------------------------------------------------------
    def last_run(self) -> Optional[_datetime]:
        with self._lock:
            try:
                t = _datetime.fromisoformat(str(self._meta.get("last_run") or ""))
                return t if t.tzinfo else t.replace(tzinfo=_timezone.utc)
            except Exception:
                return None

    def last_result(self) -> Dict[str, Any]:
        with self._lock:
            r = self._meta.get("last_result")
            return dict(r) if isinstance(r, dict) else {}

    def record_run(self, result: Dict[str, Any], when: Optional[_datetime] = None) -> None:
        with self._lock:
            self.load()  # ändra bara metadata — aldrig skriv över regler som redigerats under tiden
            self._meta["last_run"] = (when or _datetime.now(_timezone.utc)).isoformat()
            self._meta["last_result"] = {
                k: result.get(k) for k in ("trigger", "rules", "checked", "changed")
            }
            self.save()


def load_rules(data_dir: Any) -> RuleSet:
    return RuleSet(rules_path(data_dir))


def due_for_hourly(
    ruleset: RuleSet,
    now: Optional[_datetime] = None,
    interval_sec: int = HOURLY_INTERVAL_SEC,
) -> bool:
    """
    Är det dags för timkörningen?

    Utgår från sparad tid för senaste körning, så en omstart av appen varken
    kör för ofta eller hoppar över en timme.
    """
    nu = now or _datetime.now(_timezone.utc)
    last = ruleset.last_run()
    return last is None or (nu - last).total_seconds() >= interval_sec


# --------------------------------------------------------------------------
# Körning
# --------------------------------------------------------------------------
def _apply_rule(store: Any, task: Dict[str, Any], rule: Dict[str, Any],
                today: _date) -> List[str]:
    """Utför en regels åtgärder på en uppgift. `task` uppdateras lokalt. Returnerar ändringar."""
    tid = str(task["id"])
    a = rule["actions"]
    ändringar: List[str] = []

    prio = a.get("priority")
    if prio and str(task.get("priority") or "none") != prio:
        if store.set_priority(tid, prio):
            task["priority"] = prio
            ändringar.append(f"prioritet → {prio}")

    for tag in a.get("add_tags") or []:
        have = [str(t).lower() for t in (task.get("tags") or [])]
        if tag.lower() not in have:
            if store.add_tag(tid, tag):
                task["tags"] = list(task.get("tags") or []) + [tag]
                ändringar.append(f"tagg “{tag}”")

    if a.get("due_in_days") is not None and not str(task.get("due_date") or "").strip():
        d = (today + _timedelta(days=int(a["due_in_days"]))).isoformat()
        if store.set_due_date(tid, d):
            task["due_date"] = d
            ändringar.append(f"förfaller {d}")

    if a.get("pin") and not task.get("pinned"):
        if store.toggle_pinned(tid):
            task["pinned"] = True
            ändringar.append("nålad")
    return ändringar


def run_rules(
    store: Any,
    ruleset: RuleSet,
    task_ids: Optional[List[str]] = None,
    trigger: str = "manual",
    today: Optional[_date] = None,
    now: Optional[_datetime] = None,
) -> Dict[str, Any]:
    """
    Kör alla aktiva regler på uppgifterna (alla aktiva, eller bara `task_ids`).

    Returnerar {"trigger", "rules", "checked", "changed", "changes"} där
    `changes` är [{"task_id", "title", "rule", "what": [...]}]. Timkörningar
    och manuella körningar noteras som "senast körd" (mailkörningar inte, så
    de inte skjuter upp timkörningen).
    """
    ruleset.load()  # alltid färska regler (kan ha redigerats i dialogen)
    regler = ruleset.enabled()
    idag = today or _date.today()
    resultat: Dict[str, Any] = {
        "trigger": trigger, "rules": len(regler), "checked": 0, "changed": 0, "changes": [],
    }
    if regler:
        try:
            tasks = list(store.active_tasks())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte läsa uppgifter: {e}")
            tasks = []
        if task_ids is not None:
            valda = {str(i) for i in task_ids}
            tasks = [t for t in tasks if str(t.get("id")) in valda]
        for task in tasks:
            if not isinstance(task, dict) or not task.get("id") or task.get("done"):
                continue
            resultat["checked"] += 1
            ändrad = False
            for rule in regler:
                try:
                    if not task_matches(rule, task):
                        continue
                    vad = _apply_rule(store, task, rule, idag)
                except Exception as e:  # en trasig regel får inte stoppa resten
                    logger.warning(f"{LOG_PREFIX} regel “{rule.get('name')}” misslyckades: "
                                   f"{type(e).__name__}: {e}")
                    continue
                if vad:
                    ändrad = True
                    resultat["changes"].append({
                        "task_id": str(task["id"]), "title": str(task.get("title") or ""),
                        "rule": rule["name"], "what": vad,
                    })
            if ändrad:
                resultat["changed"] += 1
        if resultat["changed"]:
            try:
                store.save()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara uppgifterna: {e}")
    if trigger in ("manual", "hourly"):
        ruleset.record_run(resultat, when=now)
    logger.info(
        f"{LOG_PREFIX} körning ({trigger}): {resultat['rules']} regler, "
        f"{resultat['checked']} uppgifter kontrollerade, {resultat['changed']} ändrade"
    )
    return resultat


def run_for_tasks(store: Any, ruleset: RuleSet, task_ids: List[str]) -> Dict[str, Any]:
    """Kör reglerna på nyinkomna uppgifter (t.ex. mail som precis importerats)."""
    return run_rules(store, ruleset, task_ids=task_ids, trigger="mail")


def summarize(resultat: Dict[str, Any]) -> str:
    """Kort svensk sammanfattning av en körning."""
    if not resultat.get("rules"):
        return "Det finns inga aktiva regler."
    return (f"{resultat['rules']} regler kördes på {resultat['checked']} uppgifter — "
            f"{resultat['changed']} ändrades.")


# --------------------------------------------------------------------------
# Självtest (python core/rules.py)
# --------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import sys
    import tempfile
    r, p = normalize_rule({"name": "Fakturor", "conditions": [
        {"field": "subject", "op": "contains", "value": "faktura"}],
        "actions": {"priority": "high", "add_tags": "ekonomi"}})
    print(describe_rule(r) if r else p)
    with tempfile.TemporaryDirectory() as d:
        rs = load_rules(d)
        rs.upsert(r)
        print("sparad:", len(load_rules(d).all()), "regel(er)")
    sys.exit(0 if r else 1)
