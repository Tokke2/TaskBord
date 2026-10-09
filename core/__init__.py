# -*- coding: utf-8 -*-
"""
core — UI-oberoende kärnlogik för TaskBord v6.4.1.

Innehåller:
  - settings.py   (app-inställningar, schema v8+)
  - store.py      (task-data, index-cache, O(1) lookup)
  - utils.py      (OS-hjälpare, mutex, registry, paletter)
  - desktop.py    (Win32/DWM-brygga, mica/acrylic)
  - backup.py     (backup-rotation, atomic)
  - stability.py  (ErrorBoundary, CircuitBreaker, Recovery)
  - logger_setup.py (central loggning)

Alla moduler importeras via safe_import_module() i main.pyw
för att undvika hårdkopplade paths (se §20.8).
"""

__version__ = "6.4.1"
