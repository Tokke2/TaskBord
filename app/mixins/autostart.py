# -*- coding: utf-8 -*-
"""Starta med datorn (registret + Startup-.bat) och minimerad start."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Dict

from app.constants import APP_NAME, LOG_PREFIX, SCRIPT_DIR
from app.platform_utils import _is_windows


class AutostartMixin:
    """Starta med datorn (registret + Startup-.bat) och minimerad start."""

    def _is_autostart_active(self) -> bool:
        """
        Kontrollera om autostart är aktivt (Windows registry ELLER settings.set_autostart).

        Använder samma källa som resten av appen (utils.is_autostart_enabled
        om tillgängligt, annars settings.set_autostart/get_autostart_command).
        Returnerar True om appen startar automatiskt vid Windows-inloggning.
        """
        try:
            # 0. NY v7-fix12: desktop.is_autostart_enabled — multi-OS
            #    (Windows registry/startup/schtask, macOS launchd, Linux XDG)
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                d_is = getattr(
                    self._desktop_mod(desktop_status), "is_autostart_enabled", None
                )
                if callable(d_is):
                    with suppress(Exception):
                        return bool(d_is())
            # 1. Försök via utils.is_autostart_enabled (snabbast, live registry-check)
            utils_status = self._imports.get("utils")
            if utils_status and utils_status.ok:
                is_fn = getattr(utils_status.instance, "is_autostart_enabled", None)
                if callable(is_fn):
                    with suppress(Exception):
                        return bool(is_fn())
            # 2. Fallback: settings.set_autostart (settings-driven)
            if hasattr(self.settings, "is_autostart_enabled"):
                with suppress(Exception):
                    return bool(self.settings.is_autostart_enabled())
            if hasattr(self.settings, "get_autostart_command"):
                with suppress(Exception):
                    cmd = self.settings.get_autostart_command()
                    return bool(cmd and cmd.strip())
            # 3. Sista fallback: direktregistry-check (Windows)
            if _is_windows():
                try:
                    import winreg
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_READ,
                    ) as key:
                        try:
                            winreg.QueryValueEx(key, APP_NAME)
                            return True
                        except FileNotFoundError:
                            return False
                except Exception:
                    pass
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _is_autostart_active misslyckades: {e}")
        return False

    def _autostart_build_command(self) -> str:
        """NY v7-fix37: Bygg korrekt autostart-kommando (pythonw + main.pyw)."""
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            pythonw = Path(exe).parent / "pythonw.exe"
            if pythonw.is_file():
                exe = str(pythonw)
        script = SCRIPT_DIR / "main.pyw"
        if not script.is_file():
            script = SCRIPT_DIR / "main.py"
        cmd = f'"{exe}" "{script}"'
        self._log.debug(f"{LOG_PREFIX} autostart-kommando: {cmd}")
        return cmd

    @staticmethod
    def _autostart_bat_text(cmd: str) -> str:
        """FIX v8: korrekt Startup-.bat. `cmd` är redan '"exe" "skript"' med citat runt var del.

        Tidigare skrevs tre citattecken (start \"\"\") eller så citerades hela kommandot som
        EN fil → "Det går inte att hitta filen …pythonw.exe …main.pyw" vid inloggning.
        """
        return f'@echo off\r\nrem Ledgebord (v8)\r\nchcp 65001 >nul\r\nstart "" {cmd}\r\n'

    def _autostart_repair_startup_bat(self) -> None:
        """FIX v8: reparerar en gammal, trasig Startup-.bat (skriver bara om om den redan finns)."""
        if sys.platform != "win32":
            return
        try:
            bat = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup", f"{APP_NAME}.bat")
            if not bat.is_file():
                return
            want = self._autostart_bat_text(self._autostart_build_command())
            if bat.read_bytes().decode("utf-8", "replace") != want:
                bat.write_bytes(want.encode("utf-8"))
                self._log.warning(f"{LOG_PREFIX} ★ AUTOSTART: reparerade Startup-.bat ({bat})")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _autostart_repair_startup_bat: {e}")

    def _autostart_enable_robust(self) -> Dict[str, bool]:
        """NY v7-fix37: Aktivera autostart via multipla metoder + verifiering."""
        results: Dict[str, bool] = {}
        cmd = self._autostart_build_command()
        if sys.platform != "win32":
            try:
                import desktop as _desk
                results["desktop-motor"] = bool(_desk.enable_autostart())
            except Exception:
                results["desktop-motor"] = False
            return results
        # Metod 1: Registry
        try:
            import winreg
            kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_READ) as k:
                v, _ = winreg.QueryValueEx(k, APP_NAME)
                results["registry"] = bool(v)
        except FileNotFoundError:
            results["registry"] = True
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} autostart registry: {e}")
            results["registry"] = False
        # Metod 2: Startup-mapp
        try:
            sd = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                      "Start Menu", "Programs", "Startup")
            sd.mkdir(parents=True, exist_ok=True)
            bat = sd / f"{APP_NAME}.bat"
            bat.write_bytes(self._autostart_bat_text(cmd).encode("utf-8"))
            results["startup-mapp"] = bat.is_file()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} autostart startup: {e}")
            results["startup-mapp"] = False
        # Metod 3: schtasks (endast om andra misslyckades)
        if not any(results.values()):
            try:
                import subprocess as _sp
                _sp.run(["schtasks", "/create", "/tn", "Ledgebord_Auto",
                         "/tr", cmd, "/sc", "onlogon", "/f"],
                        capture_output=True, timeout=15)
                chk = _sp.run(["schtasks", "/query", "/tn", "Ledgebord_Auto"],
                              capture_output=True, timeout=10)
                results["schtasks"] = chk.returncode == 0
            except Exception:
                results["schtasks"] = False
        return results

    def _autostart_disable_all(self) -> int:
        """NY v7-fix37: Ta bort autostart från ALLA platser."""
        removed = 0
        if sys.platform != "win32":
            try:
                import desktop as _desk
                if _desk.disable_autostart():
                    removed += 1
            except Exception:
                pass
            with suppress(Exception):
                removed += self._autostart_remove_legacy()
            return removed
        try:
            import winreg
            kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, APP_NAME)
            removed += 1
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            sd = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                      "Start Menu", "Programs", "Startup")
            bat = sd / f"{APP_NAME}.bat"
            if bat.is_file():
                bat.unlink()
                removed += 1
        except Exception:
            pass
        try:
            import subprocess as _sp
            _sp.run(["schtasks", "/delete", "/tn", "Ledgebord_Auto", "/f"],
                    capture_output=True, timeout=10)
        except Exception:
            pass
        with suppress(Exception):
            removed += self._autostart_remove_legacy()
        return removed

    # Namn appen hade innan den hette Ledgebord — gamla autostart-poster städas bort (se nedan)
    _LEGACY_AUTOSTART_NAMES = ("TaskBord",)

    @staticmethod
    def _startup_dir() -> Path:
        return Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

    def _autostart_legacy_present(self) -> bool:
        """Finns en autostart-post under det gamla namnet (registret / Startup-mappen / XDG / launchd)?"""
        try:
            if sys.platform == "win32":
                import winreg
                kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
                for name in self._LEGACY_AUTOSTART_NAMES:
                    with suppress(OSError):
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_READ) as k:
                            winreg.QueryValueEx(k, name)
                            return True
                    for ext in (".bat", ".lnk", ".cmd", ".vbs"):
                        if (self._startup_dir() / f"{name}{ext}").is_file():
                            return True
                return False
            if sys.platform == "darwin":
                return any(
                    (Path.home() / "Library" / "LaunchAgents" / f"com.{n.lower()}.plist").is_file()
                    for n in self._LEGACY_AUTOSTART_NAMES)
            cfg = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            return any((cfg / "autostart" / f"{n}.desktop").is_file() for n in self._LEGACY_AUTOSTART_NAMES)
        except Exception:
            return False

    def _autostart_remove_legacy(self) -> int:
        """Tar bort autostart-poster under det gamla namnet. Returnerar hur många som togs bort."""
        removed = 0
        for name in self._LEGACY_AUTOSTART_NAMES:
            try:
                if sys.platform == "win32":
                    import winreg
                    kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
                    with suppress(OSError):
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.DeleteValue(k, name)
                            removed += 1
                    for ext in (".bat", ".lnk", ".cmd", ".vbs"):
                        f = self._startup_dir() / f"{name}{ext}"
                        if f.is_file():
                            f.unlink()
                            removed += 1
                    import subprocess as _sp
                    for tn in (f"{name}_Auto", name):
                        with suppress(Exception):
                            _sp.run(["schtasks", "/delete", "/tn", tn, "/f"], capture_output=True, timeout=10)
                elif sys.platform == "darwin":
                    f = Path.home() / "Library" / "LaunchAgents" / f"com.{name.lower()}.plist"
                    if f.is_file():
                        import subprocess as _sp
                        with suppress(Exception):
                            _sp.run(["launchctl", "unload", str(f)], capture_output=True, timeout=5)
                        f.unlink()
                        removed += 1
                else:
                    cfg = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                    f = cfg / "autostart" / f"{name}.desktop"
                    if f.is_file():
                        f.unlink()
                        removed += 1
            except Exception as e:
                self._log.debug(f"{LOG_PREFIX} _autostart_remove_legacy({name}): {e}")
        return removed

    def _autostart_migrate_legacy(self) -> None:
        """Namnbyte TaskBord → Ledgebord: skapa autostart under det nya namnet FÖRST, städa sedan det gamla.

        Så startar appen med datorn som förut (aldrig två poster, aldrig ingen)."""
        if not self._autostart_legacy_present():
            return
        results = self._autostart_enable_robust()
        if any(results.values()):
            n = self._autostart_remove_legacy()
            self._log.info(f"{LOG_PREFIX} ★ AUTOSTART: flyttade till nya namnet ({', '.join(k for k, v in results.items() if v)}), "
                           f"{n} gammal(a) post(er) borttagna")
        else:
            self._log.warning(f"{LOG_PREFIX} ★ AUTOSTART: kunde inte skapa ny post — behåller den gamla")

    def _autostart_health_check(self) -> None:
        """NY v7-fix37: Självreparation — om autostart borde vara på men inte är → fixa."""
        try:
            settings_on = bool(
                getattr(self.settings, "is_autostart_enabled", lambda: False)()
            )
            if not settings_on:
                return
            with suppress(Exception):
                self._autostart_migrate_legacy()
            self._autostart_repair_startup_bat()
            if sys.platform == "win32":
                import winreg
                kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
                # NY v7-fix67: städa gamla DesktopTodoPy-autostart
                # (namnbyte → Ledgebord) så den inte startar en död kopia
                with suppress(Exception):
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, kp, 0,
                        winreg.KEY_SET_VALUE,
                    ) as _k_old:
                        winreg.DeleteValue(_k_old, "DesktopTodoPy")
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_READ) as k:
                        _val, _ = winreg.QueryValueEx(k, APP_NAME)
                        # NY v7-fix58: PORTABILITET — om appen flyttats
                        # (USB, annan mapp) pekar registry på en DÖD
                        # sökväg → skriv om med aktuell plats.
                        _want = self._autostart_build_command() or ""
                        if str(_val).strip().lower() != str(_want).strip().lower():
                            self._log.warning(
                                f"{LOG_PREFIX} ★ AUTOSTART SJÄLVREPARATION: "
                                f"sökväg föråldrad (app flyttad?) → skriver "
                                f"om till aktuell plats"
                            )
                            self._autostart_enable_robust()
                        return  # Finns (och är aktuell) — OK
                except FileNotFoundError:
                    pass
                self._log.warning(
                    f"{LOG_PREFIX} ★ AUTOSTART SJÄLVREPARATION: "
                    f"settings=PÅ, registry=SAKNAS → återaktiverar"
                )
                results = self._autostart_enable_robust()
                ok = [k for k, v in results.items() if v]
                if ok:
                    self._log.info(
                        f"{LOG_PREFIX} ✓ självreparation: {', '.join(ok)}"
                    )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} autostart health: {e}")

    def _toggle_autostart(self, checked: bool) -> None:
        """
        NY v7-fix37: 10000% bättre autostart — robust + verifierad.

        Förbättringar jämfört med v6.4.1:
          1. Bygger korrekt kommando direkt (pythonw.exe + main.pyw)
          2. Sätter via MULTIPLA metoder (registry + startup-mapp)
          3. VERIFIERAR att det faktiskt funkar efteråt
          4. Ren disable: tar bort från ALLA platser
          5. Detaljerad feedback i tray + logg
        """
        self._log.info(
            f"{LOG_PREFIX} _toggle_autostart: requested={checked}"
        )
        try:
            if checked:
                # === AKTIVERA: multi-metod + verifiering ===
                results = self._autostart_enable_robust()
                ok_methods = [k for k, v in results.items() if v]
                if ok_methods:
                    msg = (
                        f"✅ Autostart aktiverat via: "
                        f"{', '.join(ok_methods)}"
                    )
                    self._log.info(f"{LOG_PREFIX} {msg}")
                    if self._tray is not None:
                        with suppress(Exception):
                            self._tray.showMessage(
                                APP_NAME, msg,
                                self._QSystemTrayIcon.MessageIcon.Information,
                                3000,
                            )
                    # Spara i settings
                    with suppress(Exception):
                        if hasattr(self.settings, "set_autostart"):
                            self.settings.set_autostart(True)
                else:
                    msg = "⚠️ Autostart kunde inte aktiveras — se logg"
                    self._log.warning(f"{LOG_PREFIX} {msg}")
                    if self._tray is not None:
                        with suppress(Exception):
                            self._tray.showMessage(
                                APP_NAME, msg,
                                self._QSystemTrayIcon.MessageIcon.Warning,
                                4000,
                            )
                    self._restore_autostart_checkbox()
            else:
                # === INAKTIVERA: ta bort från ALLA platser ===
                removed = self._autostart_disable_all()
                msg = f"⛔ Autostart inaktiverat ({removed} platser rensade)"
                self._log.info(f"{LOG_PREFIX} {msg}")
                if self._tray is not None:
                    with suppress(Exception):
                        self._tray.showMessage(
                            APP_NAME, msg,
                            self._QSystemTrayIcon.MessageIcon.Information,
                            2500,
                        )
                with suppress(Exception):
                    if hasattr(self.settings, "set_autostart"):
                        self.settings.set_autostart(False)
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_autostart misslyckades: {e}",
                exc_info=True,
            )
            self._show_simple_error(
                "Autostart-fel",
                f"Fel: {e}\n\nAutostart-status återställd till oförändrad.",
            )
            self._restore_autostart_checkbox()

    def _restore_autostart_checkbox(self) -> None:
        """Återställ autostart-checkbox till faktisk status (vid fel)."""
        try:
            if hasattr(self, "_autostart_action_ref") and self._autostart_action_ref is not None:
                actual = self._is_autostart_active()
                self._autostart_action_ref.blockSignals(True)
                self._autostart_action_ref.setChecked(actual)
                self._autostart_action_ref.setText(
                    f"{'✅' if actual else '⚪'}  Starta med Windows"
                )
                self._autostart_action_ref.blockSignals(False)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _restore_autostart_checkbox: {e}")

    def _toggle_start_minimized(self, checked: bool) -> None:
        """
        NY v6.4.1: Toggla 'starta minimerad i tray' via UI.

        Anropar settings.set_start_minimized(True/False).
        """
        self._log.info(
            f"{LOG_PREFIX} _toggle_start_minimized: requested={checked}"
        )
        if not hasattr(self.settings, "set_start_minimized"):
            self._log.warning(
                f"{LOG_PREFIX} settings.set_start_minimized saknas"
            )
            self._show_simple_error(
                "Starta minimerad ej tillgängligt",
                "Settings-modulen saknar set_start_minimized-metoden.",
            )
            if hasattr(self, "_minimized_action_ref") and self._minimized_action_ref is not None:
                self._minimized_action_ref.blockSignals(True)
                self._minimized_action_ref.setChecked(
                    self.settings.start_minimized()
                    if hasattr(self.settings, "start_minimized")
                    else False
                )
                self._minimized_action_ref.blockSignals(False)
            return
        try:
            ok = self.settings.set_start_minimized(checked)
            if ok:
                if checked:
                    msg = "🚀 Nästa start: appen startar gömd i systemfältet."
                else:
                    msg = "👁 Nästa start: appen visas direkt på skrivbordet."
                self._log.info(f"{LOG_PREFIX} {msg}")
                if self._tray is not None:
                    with suppress(Exception):
                        self._tray.showMessage(
                            APP_NAME,
                            msg,
                            self._QSystemTrayIcon.MessageIcon.Information,
                            2500,
                        )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} set_start_minimized({checked}) → False"
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_start_minimized misslyckades: {e}",
                exc_info=True,
            )
            self._show_simple_error(
                "Starta minimerad-fel", f"Fel: {e}"
            )
