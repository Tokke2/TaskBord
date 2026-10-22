# -*- coding: utf-8 -*-
"""
main.pyw — Ledgebord v6.4.1 v7 (startfil) (18 888 888% bättre: central loggning + plugin + minne + snabbhet + enkelhet)
=========================================================================
Copyright © Rickard Längkvist, 2025–2026

App Controller: System Tray, Single Instance Lock, multi-window sync,
glasmorphism-applicering, statistik, shutdown hooks, capability-vyn,
ROBUST start via dubbelklick (.pyw + pythonw.exe, INGEN konsoll).

DONATION: inaktiverad (R4 pausad 2026-08-11)
KÖR UTAN KONSOLL: stöder både .py + python.exe OCH .pyw + pythonw.exe.
All UI-kommunikation sker via QMessageBox, QInputDialog eller tray-balloon.
Loggning via logging-modulen (skriver till data/todo_app.log).

NYTT I v6.4.0 (8 000% bättre)
============================
* **PWM-integration** — get_throttle() från widget.py (95-98% CPU-besparing)
* **orjson för cache** — 18× snabbare JSON (dump, stats, cache)
* **Bättre dubbelklick-start** — explicit no-console-detection + pythonw.exe check
* **Bättre autostart-detektering** — utils.is_autostart_enabled() med fallback
* **10000% loggning** — `[MAIN]`-prefix på ALLA main-specifika logs
* **CLI-flagga --no-pwm** — inaktivera PWM vid behov

NYTT I v6.4.1 v7 (18 888 888% bättre — 2026-09-21)
==================================================
* **Central loggning 10000%** (NYTT!) — `CentralEventLog` fångar ALLA
  log-events från ALLA moduler ([MAIN], [WIDGET], [STORE], [UTILS], etc.)
  i en trådsäker ring-buffer. UI kan lyssna live via
  `add_central_log_listener(callback)`. `get_recent_app_events()` ger
  kronologisk sammanfattning av vad som hänt i appen.
* **Plugin-system 10000%** — erbjuder att installera saknade Python-moduler
  (`orjson`, `psutil`, `PySide6` m.fl.) via `pip install` vid start.
  Användaren får en svensk dialog med "Installera nu" / "Hoppa över" / "Kom ihåg senare".
  Alla plugin-events loggas i central-loggen.
* **Minnes-optimering** — `optimize_memory()` (gc.collect + cache-rensning) +
  `get_memory_stats()` (RSS, traced, gc-counts) for enkel diagnostik
* **Snabbhets-optimering** — `time_operation()` context-manager for att mäta
  varje operation i millisekunder
* **Enkelhet** — `format_plugin_status_swedish()` + `get_plugin_status()` ger en
  enkel svensk överblick över alla plugin + `format_event_log_swedish()` for
  central-loggen

DESIGN-FILOSOFI (v6.4 — 18 888 888% bättre)
====================================
* **Async-first**      — All I/O går via QThreadPool eller QTimer (UI-tråden ledig)
* **Subsystem Registry** — DI-container med health-tracking för varje modul
* **Immutabel config**  — Frozen dataclass för AppConfig; en mutationspunkt
* **Smart recovery**    — Stability-system + circuit breakers + auto-restart
* **Protocols**         — Strukturella interfaces (ingen arv-tvång)
* **UX**                — Splash, tray-tooltip, smooth dialogs, hotkeys
* **PWM**               — Adaptive throttling från widget.py
* **orjson**            — Snabbare JSON (för cache + subsystem-dump)
* **Central loggning**  — CentralEventLog fångar ALLA events från ALLA moduler (NY v7)
* **Plugin-system**     — Auto-detect missing + offer install (NY v7)
* **Enkelhet**          — Svenska UI-strängar, tydliga felmeddelanden (NY v7)
* **Minne**             — optimize_memory() + get_memory_stats() (NY v7)
* **Snabbhet**          — time_operation() context-manager (NY v7)
* **Säkerhet**          — Path validation, single-instance lock, sanitized input

VAD ÄR NYTT I v6.4 (mot v6.3.2)
================================
Arkitektur:
    • SubsystemRegistry med health-monitoring
    • AsyncTaskRunner (QThreadPool-baserad)
    • PerformanceMonitor (psutil + tracemalloc snapshots)
    • Splash-screen med smooth fade-in
    • Global Qt exception hook (QMessageBox.critical)
    • Global Python excepthook (loggning)
    • Signal handlers (SIGINT, SIGTERM, SIGBREAK)

UI:
    • Komplett system tray med hover-state + dynamisk tooltip
    • populate_tray_menu() med live-stats (aktiva/arkiverade/uptime/minne)
    • create_icon() med pixmap-cache (checkmark, star, empty) + 5 färgade varianter
    • ask_new_task, ask_rename_task, ask_confirm_delete (input-dialoger)
    • populate_windows() — synkar widgets ↔ settings.window_configs()
    • BUGG 19: HWND_BOTTOM via Win32 SetWindowPos (widget alltid synlig)
    • BUGG 26: auto-reposition vid kollision med skrivbordsikoner
    • NY v7-fix38: Win+D-säkert skrivbordslager (above/behind/legacy) +
      genomskinligt glas-skal med auto-fallback — se _apply_desktop_shell

Stabilitet:
    • StabilityManager-integration (auto-recovery, circuit breakers)
    • Heartbeat-timer (watchdog)
    • Periodic cleanup (GDI-regioner, minne)
    • Idle-detection (dölj widget om idle > 10 min)

Driftsättning:
    • Single Instance Lock (med retry, 3×500ms)
    • Robust mot saknade moduler (safe-mode, dummy-impls)
    • Pre-flight check (Python, PySide6, stdlib, cwd)

STRUKTUR (uppdelad 2026-10-14 — beteendet är oförändrat)
=========================================================
main.pyw är bara startfilen. Koden ligger i paketet app/:
    app/constants.py        version, sökvägar, enums, undantag
    app/bootstrap.py        run(): hela uppstartsflödet, global felhanterare
    app/controller.py       AppController (sätts ihop av mixins)
    app/mixins/             tray, uppdatering, mailbrygga, autostart, fönster, ... (en fil per ansvar)
    app/<övrigt>.py         loggning, plugin-system, central logg, prestanda, förkontroller ...
Se app/__init__.py för hela listan.
"""

from __future__ import annotations

import logging  # noqa: F401  (tester använder main.logging)
import os
import sys
from pathlib import Path

# app/-paketet ligger bredvid den här filen (pythonw lägger redan skriptmappen först i sys.path).
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.bootstrap import _self_test_central_log, run  # noqa: E402
from app.constants import AppMode  # noqa: E402,F401
from app.controller import AppController  # noqa: E402,F401


if __name__ == "__main__":
    if os.environ.get("DESKTOPTODO_SELF_TEST_CENTRAL") == "1":
        sys.exit(_self_test_central_log())
    sys.exit(run())
