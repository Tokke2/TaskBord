"""Hjälpare för tester som granskar appens källkod: main.pyw + app/-paketet (delat ur main.pyw)."""
from __future__ import annotations

from pathlib import Path


def app_files(root: Path) -> list[Path]:
    return [Path(root) / "main.pyw"] + sorted((Path(root) / "app").rglob("*.py"))


def app_source(root: Path) -> str:
    """All startkod (main.pyw + app/**) som en sträng — för 'finns det här i koden?'-kontroller."""
    return "\n".join(p.read_text(encoding="utf-8") for p in app_files(root))
