# -*- coding: utf-8 -*-
"""Felsäker import av appens egna moduler."""

from __future__ import annotations

import importlib.util
import logging.handlers
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.constants import LOG_PREFIX, SCRIPT_DIR


@dataclass
class ImportStatus:
    """Status för en modul-import."""
    module: str
    ok: bool
    error: Optional[str] = None
    instance: Optional[Any] = None


def safe_import_module(
    module_name: str,
    *,
    from_items: Optional[List[str]] = None,
    required: bool = True,
) -> ImportStatus:
    """Importera en modul säkert med detaljerad felhantering.

    NY v6.4.1: Stöd för sökvägs-baserad import så moduler kan ligga i
    core/ och ui/ underkataloger (tidigare __import__ hittade inte dem).

    NY v6.4.1 v7: Validerar att alla from_items faktiskt är definierade i modulen
    efter import (Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det").
    """
    import_log = logging.getLogger("Main")
    try:
        # NY v6.4.1: Försök hitta modulen relativt main.pyw först
        here = SCRIPT_DIR
        candidate_paths = [
            here / "core" / f"{module_name}.py",
            here / "ui" / f"{module_name}.py",
            here / f"{module_name}.py",
            here / f"{module_name}.pyw",
        ]
        loaded_via_path = False
        module = None
        for p in candidate_paths:
            if p.is_file():
                spec = importlib.util.spec_from_file_location(module_name, p)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    loaded_via_path = True
                    break

        if module is None:
            if from_items:
                module = __import__(module_name, fromlist=from_items)
            else:
                module = __import__(module_name)

        if from_items:
            # NY v7: Validera att alla from_items existerar
            instances: Dict[str, Any] = {}
            missing_items: List[str] = []
            for item in from_items:
                if hasattr(module, item):
                    instances[item] = getattr(module, item)
                else:
                    missing_items.append(item)
                    import_log.error(
                        f"{LOG_PREFIX} safe_import_module: {module_name} "
                        f"saknar '{item}' — tyst krasch risk!"
                    )
            if missing_items:
                import_log.error(
                    f"{LOG_PREFIX} safe_import_module: {module_name} importerad "
                    f"men saknar {len(missing_items)} objekt: {missing_items}"
                )
                return ImportStatus(
                    module=module_name, ok=False,
                    error=f"saknar objekt: {missing_items}",
                    instance=instances,
                )
            return ImportStatus(module=module_name, ok=True, instance=instances)
        # NY v6.4.1 fix: alltid returnera dict (med modulnamn som nyckel)
        # så instance["Settings"] / instance.get("BackupManager") funkar
        # både när from_items angavs och när det inte gjorde det.
        return ImportStatus(
            module=module_name, ok=True, instance={module_name: module}
        )
    except ImportError as e:
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        if required:
            import_log.critical(
                f"{LOG_PREFIX} Kunde inte importera {module_name}: {e}"
            )
        else:
            import_log.warning(
                f"{LOG_PREFIX} Kunde inte importera {module_name}: {e}"
            )
        return status
    except SyntaxError as e:
        # NY v7: SyntaxError är vanligt — logga med tydlig info
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        import_log.critical(
            f"{LOG_PREFIX} SYNTAX-FEL i {module_name}: {e} (rad {e.lineno})",
            exc_info=True,
        )
        return status
    except BaseException as e:
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        import_log.critical(
            f"{LOG_PREFIX} FEL VID IMPORT av {module_name}: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return status


def import_all_dependencies() -> Dict[str, ImportStatus]:
    """Importera ALLA nödvändiga moduler och returnera status."""
    return {
        "PySide6.QtCore": safe_import_module(
            "PySide6.QtCore",
            from_items=["Qt", "QTimer", "Slot", "Signal", "QObject"],
        ),
        "PySide6.QtGui": safe_import_module(
            "PySide6.QtGui",
            from_items=["QAction", "QFont", "QIcon", "QPainter", "QColor", "QPixmap", "QPen", "QBrush"],
        ),
        "PySide6.QtWidgets": safe_import_module(
            "PySide6.QtWidgets",
            from_items=[
                "QApplication", "QSystemTrayIcon", "QMenu", "QMessageBox",
                "QInputDialog", "QWidget", "QDialog", "QDialogButtonBox",
            ],
        ),
        "desktop": safe_import_module("desktop", required=False),
        "settings": safe_import_module(
            "settings", from_items=["Settings"], required=False,
        ),
        "store": safe_import_module(
            "store", from_items=["TaskStore"], required=False,
        ),
        "utils": safe_import_module("utils", required=False),
        "widget": safe_import_module(
            "widget", from_items=["TodoWidget"], required=False,
        ),
        "backup": safe_import_module(
            "backup", from_items=["BackupManager"], required=False,
        ),
        "stability": safe_import_module("stability", required=False),
    }
