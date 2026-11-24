# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
notes.py — 📝 Anteckningar: egna, fristående anteckningar (inte kopplade till en uppgift). Ren stdlib, ingen Qt.

Allt sparas i ``notes.json`` i appens datamapp (samma mapp som uppgifterna, ``js\\``) — inget skrivs utanför appmappen.
Filen skrivs atomärt (temporärfil → ``os.replace``), så en krasch mitt i en sparning aldrig kan förstöra den.
Är filen skadad flyttas den undan som ``notes.json.skadad-<tid>`` (ingenting raderas) och en tom lista startar.

Anteckning: ``{id, title, body, created, updated, pinned}``. Fästa (📌) ligger överst, därefter senast ändrad först.
``merge_raw`` slår ihop två filer (vid återställning av backup) — ingen anteckning försvinner, nyast ändring vinner.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[NOTES]"

FILENAME = "notes.json"
TITLE_MAX = 200
BODY_MAX = 200_000
NOTES_MAX = 5_000
PREVIEW_MAX = 90


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean(raw: Any) -> Optional[Dict[str, Any]]:
    """En giltig anteckning ur okänd data (eller None). Okända fält släpps."""
    if not isinstance(raw, dict):
        return None
    nid = str(raw.get("id") or "").strip()
    if not nid:
        return None
    created = str(raw.get("created") or "") or _now()
    return {
        "id": nid[:64],
        "title": str(raw.get("title") or "")[:TITLE_MAX],
        "body": str(raw.get("body") or "")[:BODY_MAX],
        "created": created,
        "updated": str(raw.get("updated") or "") or created,
        "pinned": bool(raw.get("pinned", False)),
    }


def parse(raw: bytes) -> List[Dict[str, Any]]:
    """Anteckningslistan ur filinnehåll. Kastar ValueError om formatet är fel."""
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict):
        data = data.get("notes", [])
    if not isinstance(data, list):
        raise ValueError("oväntat format")
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        n = _clean(item)
        if n and n["id"] not in seen:
            seen.add(n["id"])
            out.append(n)
    return out


def dump(notes: List[Dict[str, Any]]) -> bytes:
    return json.dumps({"version": 1, "notes": notes}, ensure_ascii=False, indent=1).encode("utf-8")


def merge_raw(current_raw: Optional[bytes], other_raw: bytes) -> bytes:
    """Union av två filer; vid samma id vinner den senast ändrade. Ingen anteckning tas bort."""
    cur = parse(current_raw) if current_raw else []
    oth = parse(other_raw)
    by_id = {n["id"]: n for n in cur}
    for n in oth:
        c = by_id.get(n["id"])
        if c is None or n["updated"] > c["updated"]:
            by_id[n["id"]] = n
    return dump(list(by_id.values()))


def title_of(note: Dict[str, Any]) -> str:
    """Rubriken — eller första raden i texten om rubrik saknas."""
    t = (note.get("title") or "").strip()
    if t:
        return t
    for line in str(note.get("body") or "").splitlines():
        if line.strip():
            return line.strip()[:TITLE_MAX]
    return "(tom anteckning)"


def preview_of(note: Dict[str, Any]) -> str:
    """Förhandsvisning: texten på en rad (utan rubriken om den är första raden)."""
    body = str(note.get("body") or "")
    if not (note.get("title") or "").strip():
        lines = [x for x in body.splitlines() if x.strip()]
        body = "\n".join(lines[1:])
    one = re.sub(r"\s+", " ", body).strip()
    return one[:PREVIEW_MAX] + ("…" if len(one) > PREVIEW_MAX else "")


class NotesStore:
    """Anteckningar på disk. Alla ändringar sparas direkt (atomärt)."""

    def __init__(self, data_dir: Any) -> None:
        self.path = Path(str(data_dir)) / FILENAME
        self._notes: List[Dict[str, Any]] = []
        self._mtime = 0.0
        self.load()

    # ------------------------------------------------------------ disk
    def load(self) -> None:
        self._notes = []
        try:
            if not self.path.is_file():
                return
            if self.path.stat().st_size == 0:
                return
            self._notes = parse(self.path.read_bytes())
            self._mtime = self.path.stat().st_mtime
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} notes.json är skadad ({e}) — sparas undan, tom lista startar")
            try:
                self.path.replace(self.path.with_name(f"{self.path.name}.skadad-{datetime.now():%Y%m%d-%H%M%S}"))
            except OSError:
                pass
            self._notes = []

    def reload_if_changed(self) -> bool:
        """Läs om filen om den ändrats utifrån (t.ex. efter återställning av backup). True om något lästes om."""
        try:
            mt = self.path.stat().st_mtime if self.path.is_file() else 0.0
        except OSError:
            return False
        if mt != self._mtime:
            self.load()
            self._mtime = mt
            return True
        return False

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as f:
                f.write(dump(self._notes))
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(self.path))
            self._mtime = self.path.stat().st_mtime
            return True
        except OSError as e:
            logger.warning(f"{LOG_PREFIX} kunde inte spara anteckningar: {e}")
            return False

    # ------------------------------------------------------------ läsa
    def count(self) -> int:
        return len(self._notes)

    def get(self, nid: str) -> Optional[Dict[str, Any]]:
        for n in self._notes:
            if n["id"] == nid:
                return dict(n)
        return None

    def notes(self, query: str = "") -> List[Dict[str, Any]]:
        """Fästa först, sedan senast ändrad först. ``query`` söker (utan hänsyn till versaler) i rubrik och text."""
        q = (query or "").strip().casefold()
        items = [n for n in self._notes if not q or q in n["title"].casefold() or q in n["body"].casefold()]
        items.sort(key=lambda n: (n["updated"], n["created"]), reverse=True)
        items.sort(key=lambda n: not n["pinned"])
        return [dict(n) for n in items]

    # ------------------------------------------------------------ ändra
    def add(self, title: str = "", body: str = "") -> Dict[str, Any]:
        self.reload_if_changed()
        if len(self._notes) >= NOTES_MAX:
            raise ValueError(f"Max {NOTES_MAX} anteckningar.")
        now = _now()
        n = {"id": uuid.uuid4().hex[:12], "title": str(title)[:TITLE_MAX], "body": str(body)[:BODY_MAX],
             "created": now, "updated": now, "pinned": False}
        self._notes.append(n)
        self.save()
        return dict(n)

    def update(self, nid: str, title: Optional[str] = None, body: Optional[str] = None,
               pinned: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """Ändra en anteckning. ``updated`` ändras bara om rubrik/text faktiskt ändrats (fästning flyttar den inte)."""
        self.reload_if_changed()
        for n in self._notes:
            if n["id"] != nid:
                continue
            changed = False
            if title is not None and str(title)[:TITLE_MAX] != n["title"]:
                n["title"] = str(title)[:TITLE_MAX]
                changed = True
            if body is not None and str(body)[:BODY_MAX] != n["body"]:
                n["body"] = str(body)[:BODY_MAX]
                changed = True
            if changed:
                n["updated"] = _now()
            if pinned is not None and bool(pinned) != n["pinned"]:
                n["pinned"] = bool(pinned)
                changed = True
            if changed:
                self.save()
            return dict(n)
        return None

    def delete(self, nid: str) -> bool:
        self.reload_if_changed()
        before = len(self._notes)
        self._notes = [n for n in self._notes if n["id"] != nid]
        if len(self._notes) != before:
            self.save()
            return True
        return False
