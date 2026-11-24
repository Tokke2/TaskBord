"""Hjälpare för tester som granskar appens källkod: main.pyw + app/-paketet (delat ur main.pyw)."""
from __future__ import annotations

from pathlib import Path


def app_files(root: Path) -> list[Path]:
    return [Path(root) / "main.pyw"] + sorted((Path(root) / "app").rglob("*.py"))


def app_source(root: Path) -> str:
    """All startkod (main.pyw + app/**) som en sträng — för 'finns det här i koden?'-kontroller."""
    return "\n".join(p.read_text(encoding="utf-8") for p in app_files(root))


def widget_files(root: Path) -> list[Path]:
    """ui/widget.py (fasad) + de delar den delats upp i (widget_base, widget_atoms, widget_parts/**)."""
    ui = Path(root) / "ui"
    files = [ui / "widget.py"]
    for name in ("widget_base.py", "widget_atoms.py"):
        if (ui / name).exists():
            files.append(ui / name)
    if (ui / "widget_parts").is_dir():
        files += sorted((ui / "widget_parts").glob("*.py"))
    return files


def widget_source(root: Path) -> str:
    """All kod för TodoWidget-fönstret som en sträng — för 'finns det här i koden?'-kontroller."""
    return "\n".join(p.read_text(encoding="utf-8") for p in widget_files(root))
