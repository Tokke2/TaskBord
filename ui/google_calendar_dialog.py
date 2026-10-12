# -*- coding: utf-8 -*-
"""
google_calendar_dialog.py — NY v8 (2026-10-12): koppla Google Calendar lokalt.

Rickard 2026-10-12: "gör i appen att man lokalt kopplar OAuth".

Dialogen sköter hela kedjan:
  status → koppla upp (OAuth i webbläsaren) → välj kalender → skicka uppgifter.

Två saker att veta om designen:

  1. **Ingenting i den här filen rör nätverket i UI-tråden.** OAuth-inloggning
     och alla anrop till Google körs i en egen tråd (`_JobThread`) och
     resultatet skickas tillbaka som en signal. Annars skulle appen frysa
     medan webbläsaren väntar på att man godkänner — och Windows skulle
     visa "svarar inte".
  2. **All logik ligger i `core/google_calendar.py`** (testad utan Qt).
     Den här filen är bara knappar och meddelanden.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[GCAL-UI]"

try:
    from PySide6.QtCore import Qt, QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
    )
    _QT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - Qt saknas (t.ex. i tester)
    _QT_AVAILABLE = False
    QWidget = Any  # type: ignore[misc,assignment]

from core import google_calendar as gcal  # noqa: E402  (ingen Qt-beroende)


# --------------------------------------------------------------------------
# Hjälpare
# --------------------------------------------------------------------------
def _resolve_data_dir(
    store: Any = None,
    settings: Any = None,
    data_dir: Any = None,
) -> Path:
    """
    Var appens data ligger (där active.json och google/ ska bo).

    Samma princip som e-postbryggan: fråga store/settings, annars
    `<appmapp>/js` (där appen lägger sina JSON-filer).
    """
    if data_dir:
        return Path(str(data_dir))
    if store is not None:
        for attr in ("file_path", "_file_path"):
            med = getattr(store, attr, None)
            if callable(med):
                try:
                    med = med()
                except Exception:
                    med = None
            if med:
                try:
                    return Path(str(med)).resolve().parent
                except Exception:
                    pass
        plats = getattr(store, "_data_dir", None)
        if plats:
            return Path(str(plats))
    if settings is not None:
        try:
            p = getattr(settings, "data_dir", None)
            if callable(p):
                return Path(str(p()))
        except Exception:
            pass
    return Path(__file__).resolve().parent.parent / "js"


def _kalender_id(settings: Any = None, data_dir: Any = None) -> str:
    """Vilken kalender som valts (inställning först, annars kontoinfon)."""
    if settings is not None:
        try:
            cid = getattr(settings, "google_calendar_id", None)
            if callable(cid):
                v = str(cid()).strip()
                if v:
                    return v
        except Exception:
            pass
    konto = (gcal.load_account_info(data_dir) if data_dir else None) or {}
    return str(konto.get("calendar_id") or gcal.DEFAULT_CALENDAR_ID)


def _fargkodning(settings: Any = None) -> bool:
    """Ska händelser färgas efter prioritet?"""
    if settings is not None:
        try:
            f = getattr(settings, "google_calendar_color_by_priority", None)
            if callable(f):
                return bool(f())
        except Exception:
            pass
    return True


def _spara_ansluten(settings: Any, data_dir: Any, ansluten: bool) -> None:
    """Kom ihåg i inställningarna att kontot kopplades (eller kopplades från)."""
    try:
        s = getattr(settings, "set_google_calendar_enabled", None)
        if callable(s):
            s(bool(ansluten))
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte spara anslutningsstatus: {e}")


# --------------------------------------------------------------------------
# Trådar (nätverket får aldrig blockera fönstret)
# --------------------------------------------------------------------------
if _QT_AVAILABLE:

    class _JobThread(QThread):
        """Kör en funktion i bakgrunden och rapporterar tillbaka."""

        logg = Signal(str)
        klart = Signal(object)
        fel = Signal(str, str)   # (användartext, teknisk text)

        def __init__(self, fn: Callable[..., Any], parent: Optional[QWidget] = None):
            super().__init__(parent)
            self._fn = fn
            self._avbruten = False

        def begar_avbrott(self) -> None:
            """Be tråden sluta rapportera (den kan inte avbrytas mitt i ett anrop)."""
            self._avbruten = True

        def run(self) -> None:  # pragma: no cover - kräver Qt
            def logga(text: str) -> None:
                if not self._avbruten:
                    self.logg.emit(str(text))

            try:
                resultat = self._fn(logga)
            except gcal.GoogleCalendarError as e:
                if not self._avbruten:
                    self.fel.emit(e.user_message, e.technical)
            except Exception as e:  # noqa: BLE001 - allt ska bli ett begripligt fel
                logger.error(f"{LOG_PREFIX} jobb misslyckades: {type(e).__name__}: {e}",
                             exc_info=True)
                if not self._avbruten:
                    self.fel.emit(
                        "Något gick fel.\n\nSe loggen i fönstret för detaljer.",
                        f"{type(e).__name__}: {e}",
                    )
            else:
                if not self._avbruten:
                    self.klart.emit(resultat)

    # Håll referenser till pågående trådar — annars kan Python städa bort dem
    # medan de kör (klassiskt Qt-fel: "QThread: Destroyed while thread is running").
    _AKTIVA_TRADAR: set = set()

    class _JobDialog(QDialog):
        """Liten ruta som visar att något händer (och vad som händer)."""

        def __init__(self, titel: str, beskrivning: str, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setWindowTitle(titel)
            self.setModal(True)
            self.setMinimumWidth(460)
            self.setMinimumHeight(220)

            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(9)

            if beskrivning:
                lbl = QLabel(beskrivning, self)
                lbl.setWordWrap(True)
                rot.addWidget(lbl)

            self.bar = QProgressBar(self)
            self.bar.setRange(0, 0)  # snurrande (obestämd tid)
            self.bar.setTextVisible(False)
            rot.addWidget(self.bar)

            self.logg = QPlainTextEdit(self)
            self.logg.setReadOnly(True)
            self.logg.setMaximumBlockCount(300)
            self.logg.setMinimumHeight(90)
            rot.addWidget(self.logg, 1)

            rad = QHBoxLayout()
            rad.addStretch(1)
            self.btn_stang = QPushButton("Dölj", self)
            self.btn_stang.setToolTip(
                "Stänger rutan men jobbet fortsätter i bakgrunden."
            )
            self.btn_stang.clicked.connect(self.reject)
            rad.addWidget(self.btn_stang)
            rot.addLayout(rad)

        def skriv(self, text: str) -> None:
            self.logg.appendPlainText(str(text))


def run_google_job(
    parent: Optional[QWidget],
    titel: str,
    fn: Callable[..., Any],
    beskrivning: str = "",
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    Kör `fn(logga)` i bakgrunden med en väntruta.

    Returnerar True om jobbet startades. Utan Qt körs `fn` direkt, utan fönster.
    """
    if not _QT_AVAILABLE:  # pragma: no cover
        try:
            resultat = fn(lambda _t: None)
        except gcal.GoogleCalendarError as e:
            logger.warning(f"{LOG_PREFIX} jobb utan Qt misslyckades: {e.user_message}")
            if on_error:
                on_error(e.user_message, e.technical)
            return False
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} jobb utan Qt misslyckades: {e}")
            return False
        if on_done:
            on_done(resultat)
        return False

    dlg = _JobDialog(titel, beskrivning, parent)
    trad = _JobThread(fn, parent)
    _AKTIVA_TRADAR.add(trad)

    def _skriv(text: str) -> None:
        dlg.skriv(text)

    def _klart(resultat: Any) -> None:
        try:
            dlg.skriv("✓ Klart.")
            dlg.accept()
        except Exception:
            pass
        if on_done:
            on_done(resultat)

    def _fel(user_text: str, tech: str) -> None:
        try:
            dlg.skriv("✗ " + user_text.splitlines()[0])
            dlg.accept()
        except Exception:
            pass
        if tech:
            logger.warning(f"{LOG_PREFIX} {tech}")
        if on_error:
            on_error(user_text, tech)
        else:
            _visa_fel(parent, user_text, tech)

    def _stada() -> None:
        _AKTIVA_TRADAR.discard(trad)

    trad.logg.connect(_skriv)
    trad.klart.connect(_klart)
    trad.fel.connect(_fel)
    trad.finished.connect(_stada)
    trad.finished.connect(trad.deleteLater)

    trad.start()
    dlg.exec()  # väntrutan är modal medan jobbet kör
    return True


def _visa_fel(parent: Optional[QWidget], user_text: str, tech: str = "") -> None:
    """Visa ett fel på ett sätt som går att förstå (och stänga)."""
    if not _QT_AVAILABLE:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} {user_text} | {tech}")
        return
    try:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Google Calendar")
        box.setText(user_text)
        if tech:
            box.setDetailedText(tech)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte visa felruta: {e}")


def _visa_info(parent: Optional[QWidget], titel: str, text: str) -> None:
    """Visa ett vanligt informationsmeddelande."""
    if not _QT_AVAILABLE:  # pragma: no cover
        logger.info(f"{LOG_PREFIX} {titel}: {text}")
        return
    try:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(titel)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte visa info-ruta: {e}")


# --------------------------------------------------------------------------
# Huvuddialogen
# --------------------------------------------------------------------------
if _QT_AVAILABLE:

    class GoogleCalendarDialog(QDialog):
        """Koppla Google Calendar till TaskBord — lokalt, utan mellanhänder."""

        def __init__(
            self,
            parent: Optional[QWidget] = None,
            store: Any = None,
            settings: Any = None,
            data_dir: Any = None,
        ) -> None:
            super().__init__(parent)
            self.store = store
            self.settings = settings
            self.data_dir = _resolve_data_dir(store, settings, data_dir)

            self.setWindowTitle("TaskBord — Google Calendar (lokal koppling)")
            self.setModal(True)
            self.setMinimumWidth(560)

            rot = QVBoxLayout(self)
            rot.setContentsMargins(18, 16, 18, 14)
            rot.setSpacing(10)

            rubrik = QLabel("☁️ Google Calendar", self)
            rubrik.setStyleSheet("font-size: 18px; font-weight: 800;")
            rot.addWidget(rubrik)

            forklaring = QLabel(
                "Kopplingen sker <b>helt lokalt</b>: inloggningen öppnas i din "
                "webbläsare och svaret kommer tillbaka till en tillfällig server "
                "på <code>127.0.0.1</code>. TaskBord skickar ingenting till "
                "någon molntjänst och åtkomstbeviset sparas bara i din egen "
                "mapp (<code>google/token.json</code>).",
                self,
            )
            forklaring.setTextFormat(Qt.TextFormat.RichText)
            forklaring.setWordWrap(True)
            rot.addWidget(forklaring)

            self.status = QLabel("…", self)
            self.status.setWordWrap(True)
            self.status.setStyleSheet(
                "font-size: 14px; font-weight: 700; padding: 8px; "
                "border-radius: 6px; background: rgba(127,127,127,0.14);"
            )
            rot.addWidget(self.status)

            self.hjalprad = QLabel("", self)
            self.hjalprad.setWordWrap(True)
            self.hjalprad.setTextFormat(Qt.TextFormat.RichText)
            rot.addWidget(self.hjalprad)

            # --- knappar för anslutningen --------------------------------
            rad1 = QHBoxLayout()
            rad1.setSpacing(8)
            self.btn_koppla = QPushButton("🔑 Koppla Google-konto…", self)
            self.btn_koppla.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_koppla.setToolTip(
                "Öppnar webbläsaren där du loggar in hos Google och godkänner.\n"
                "Inget lösenord skrivs in i TaskBord."
            )
            self.btn_koppla.clicked.connect(self._on_koppla)
            rad1.addWidget(self.btn_koppla)

            self.btn_testa = QPushButton("🔌 Testa anslutning", self)
            self.btn_testa.clicked.connect(self._on_testa)
            rad1.addWidget(self.btn_testa)

            self.btn_koppla_fran = QPushButton("🗑 Koppla från", self)
            self.btn_koppla_fran.setToolTip(
                "Raderar åtkomstbeviset från datorn. Du kan koppla igen när du vill."
            )
            self.btn_koppla_fran.clicked.connect(self._on_koppla_fran)
            rad1.addWidget(self.btn_koppla_fran)
            rot.addLayout(rad1)

            # --- kalenderval ---------------------------------------------
            rad2 = QHBoxLayout()
            rad2.setSpacing(8)
            rad2.addWidget(QLabel("Kalender:", self))
            self.combo_kalender = QComboBox(self)
            self.combo_kalender.setMinimumWidth(260)
            self.combo_kalender.setToolTip(
                "Vilken kalender händelserna ska hamna i."
            )
            self.combo_kalender.activated.connect(lambda _i: self._spara_kalenderval())
            rad2.addWidget(self.combo_kalender, 1)
            self.btn_hamta_kalendrar = QPushButton("🔄 Hämta lista", self)
            self.btn_hamta_kalendrar.clicked.connect(self._on_hamta_kalendrar)
            rad2.addWidget(self.btn_hamta_kalendrar)
            rot.addLayout(rad2)

            self.chef_farg = QCheckBox("Färga händelser efter prioritet "
                                       "(röd/gul/grön)", self)
            try:
                self.chef_farg.setChecked(_fargkodning(settings))
            except Exception:
                self.chef_farg.setChecked(True)
            self.chef_farg.toggled.connect(self._on_farg_andrad)
            rot.addWidget(self.chef_farg)

            # --- skicka uppgifter ----------------------------------------
            rad3 = QHBoxLayout()
            rad3.setSpacing(8)
            self.btn_skicka_alla = QPushButton("☁️ Skicka alla uppgifter med datum", self)
            self.btn_skicka_alla.setToolTip(
                "Skickar alla aktiva uppgifter som har ett förfallodatum.\n"
                "Uppgifter som redan finns uppdateras i stället för att dubbleras."
            )
            self.btn_skicka_alla.clicked.connect(self._on_skicka_alla)
            rad3.addWidget(self.btn_skicka_alla, 1)
            rot.addLayout(rad3)

            # --- logg ----------------------------------------------------
            self.logg = QPlainTextEdit(self)
            self.logg.setReadOnly(True)
            self.logg.setMaximumBlockCount(500)
            self.logg.setMinimumHeight(110)
            self.logg.setToolTip("Vad som händer — användbart vid felsökning.")
            rot.addWidget(self.logg, 1)

            # --- stäng ---------------------------------------------------
            rad4 = QHBoxLayout()
            self.btn_mapp = QPushButton("📂 Öppna mappen", self)
            self.btn_mapp.setToolTip(
                "Öppnar mappen där credentials.json ska ligga och token sparas."
            )
            self.btn_mapp.clicked.connect(self._on_oppna_mapp)
            rad4.addWidget(self.btn_mapp)

            self.btn_guide = QPushButton("📄 Öppna guiden", self)
            self.btn_guide.setToolTip("GOOGLE_CALENDAR.md — steg för steg")
            self.btn_guide.clicked.connect(self._on_oppna_guide)
            rad4.addWidget(self.btn_guide)

            rad4.addStretch(1)
            btn_stang = QPushButton("Stäng", self)
            btn_stang.clicked.connect(self.accept)
            rad4.addWidget(btn_stang)
            rot.addLayout(rad4)

            self._refresh_status()

        # ------------------------------------------------------------------
        # Status och logg
        # ------------------------------------------------------------------
        def _skriv(self, text: str) -> None:
            try:
                self.logg.appendPlainText(str(text))
            except Exception:
                pass

        def _refresh_status(self) -> None:
            """Uppdatera statusraden, hjälptexten och knapparnas läge."""
            try:
                st = gcal.get_status(self.data_dir)
            except Exception as e:
                self.status.setText("⚠ Kunde inte läsa status")
                self._skriv(f"Fel vid statuskontroll: {e}")
                return

            state = st["state"]
            if state == gcal.ConnectionStatus.CONNECTED:
                text = f"✅ {st['label']}"
                if st.get("email"):
                    text += f" — {st['email']}"
                self.status.setStyleSheet(
                    "font-size: 14px; font-weight: 700; padding: 8px; "
                    "border-radius: 6px; background: rgba(34,197,94,0.18);"
                )
            elif state == gcal.ConnectionStatus.NO_LIBRARY:
                text = f"⚠ {st['label']}"
                self.status.setStyleSheet(
                    "font-size: 14px; font-weight: 700; padding: 8px; "
                    "border-radius: 6px; background: rgba(234,179,8,0.20);"
                )
            else:
                text = f"• {st['label']}"
                self.status.setStyleSheet(
                    "font-size: 14px; font-weight: 700; padding: 8px; "
                    "border-radius: 6px; background: rgba(127,127,127,0.14);"
                )
            self.status.setText(text)

            # Hjälprad: vad som saknas, och var filen ska ligga
            rader: List[str] = []
            if state == gcal.ConnectionStatus.NO_LIBRARY:
                rader.append(
                    "Google-paketen saknas. Kör i en kommandotolk:<br>"
                    f"<code>{gcal.install_hint()}</code><br>"
                    "(Första gången via <b>FORSTA_START.bat</b> installeras de "
                    "automatiskt.)"
                )
            elif not st["has_credentials"]:
                rader.append(
                    "<b>Engångssteg hos Google:</b> skapa en OAuth-klient av "
                    "typen <i>Datorapp</i> och lägg den nedladdade filen här:<br>"
                    f"<code>{gcal.credentials_path(self.data_dir)}</code><br>"
                    "Klicka <b>📄 Öppna guiden</b> för stegen i Google Cloud."
                )
            elif state == gcal.ConnectionStatus.DISCONNECTED:
                rader.append(
                    "Filen <code>credentials.json</code> hittades ✓ — klicka på "
                    "<b>🔑 Koppla Google-konto</b> för att logga in."
                )
            elif state == gcal.ConnectionStatus.CONNECTED:
                rader.append(
                    f"Åtkomstbevis: <code>{Path(st['token_file']).name}</code> "
                    f"(sparas bara lokalt, rättigheter 0600)."
                )
            if st.get("email"):
                rader.append(f"Konto: <b>{st['email']}</b>")
            self.hjalprad.setText("<br>".join(rader))

            ansluten = state == gcal.ConnectionStatus.CONNECTED
            self.btn_testa.setEnabled(ansluten)
            self.btn_koppla_fran.setEnabled(ansluten)
            self.btn_skicka_alla.setEnabled(ansluten)
            self.btn_hamta_kalendrar.setEnabled(ansluten)
            self.btn_koppla.setEnabled(
                state in (gcal.ConnectionStatus.DISCONNECTED,
                          gcal.ConnectionStatus.CONNECTED)
            )

            # Visa vald kalender i rutan (utan att skriva över användarens val)
            if self.combo_kalender.count() == 0:
                cid = _kalender_id(self.settings, self.data_dir)
                self.combo_kalender.addItem(cid, cid)
                if cid != gcal.DEFAULT_CALENDAR_ID:
                    self.combo_kalender.addItem(gcal.DEFAULT_CALENDAR_ID,
                                                gcal.DEFAULT_CALENDAR_ID)

            self._skriv(f"Status: {st['label']}"
                        + (f" ({st['email']})" if st.get("email") else ""))
            self._skriv(f"Mapp: {self.data_dir}")
            if st.get("credentials_file"):
                self._skriv(f"credentials: {st['credentials_file']}")
            if st.get("token_file"):
                self._skriv(f"token: {Path(st['token_file']).name}")

        # ------------------------------------------------------------------
        # Åtgärder
        # ------------------------------------------------------------------
        def _on_koppla(self) -> None:
            """Starta OAuth-inloggningen (i bakgrunden)."""
            data = self.data_dir

            def jobb(logga):
                logga("Öppnar webbläsaren för inloggning hos Google…")
                logga("Logga in och godkänn åtkomsten. Fönstret väntar i upp "
                      "till 5 minuter.")
                svar = gcal.authenticate_google_calendar(
                    data, open_browser=True, on_url=lambda _u: None
                )
                return svar

            def klart(svar: Dict[str, Any]) -> None:
                _spara_ansluten(self.settings, data, True)
                try:
                    if self.settings is not None:
                        konto = gcal.load_account_info(data) or {}
                        cid = konto.get("calendar_id")
                        if cid:
                            self.settings.set_google_calendar_id(str(cid))
                except Exception:
                    pass
                self.combo_kalender.clear()
                self._refresh_status()
                email = (svar or {}).get("email") or ""
                _visa_info(
                    self,
                    "☁️ Google Calendar",
                    "Klart! TaskBord är nu kopplat till Google Calendar"
                    + (f" som {email}." if email else ".")
                    + "\n\nNu kan du skicka uppgifter med ☁️ i uppgiftsmenyn, "
                      "eller via knappen ovan.",
                )

            run_google_job(
                self,
                "Kopplar till Google Calendar",
                jobb,
                beskrivning=(
                    "Ett fönster för inloggning öppnas i din webbläsare.\n"
                    "Godkänn åtkomsten där — den här rutan stängs sedan av sig själv."
                ),
                on_done=klart,
            )

        def _on_testa(self) -> None:
            """Pinga Google och visa vilket konto/kalender som svarar."""
            data = self.data_dir
            cid = _kalender_id(self.settings, data)

            def jobb(logga):
                logga(f"Testar anslutningen mot kalendern “{cid}”…")
                service = gcal.build_calendar_service(data)
                svar = gcal.test_connection(service, cid)
                logga(f"Svar: {svar.get('id') or svar.get('summary')}")
                return svar

            def klart(svar: Dict[str, Any]) -> None:
                self._skriv("✓ Anslutningen fungerar.")
                _visa_info(
                    self,
                    "🔌 Anslutningen fungerar",
                    f"Konto: {svar.get('id', '?')}\n"
                    f"Kalender: {svar.get('summary') or cid}\n"
                    f"Tidszon: {svar.get('timezone') or '?'}",
                )

            run_google_job(self, "Testar anslutningen", jobb, on_done=klart)

        def _on_koppla_fran(self) -> None:
            """Radera token lokalt (efter att ha frågat)."""
            svar = QMessageBox.question(
                self,
                "Koppla från Google Calendar",
                "Vill du koppla från?\n\n"
                "Åtkomstbeviset raderas från datorn. Händelserna som redan "
                "skickats ligger kvar i Google Calendar och dina uppgifter "
                "påverkas inte.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if svar != QMessageBox.StandardButton.Yes:
                return
            ok = gcal.disconnect(self.data_dir)
            _spara_ansluten(self.settings, self.data_dir, False)
            self.combo_kalender.clear()
            self._refresh_status()
            self._skriv("Kopplad från — åtkomstbeviset är raderat."
                        if ok else "Kunde inte radera filen (se loggen).")

        def _on_hamta_kalendrar(self) -> None:
            """Hämta kalenderlistan från Google och fyll rutan."""
            data = self.data_dir

            def jobb(logga):
                logga("Hämtar kalenderlistan…")
                service = gcal.build_calendar_service(data)
                lista = gcal.list_calendars(service)
                logga(f"Hittade {len(lista)} kalender/kalendrar.")
                return lista

            def klart(lista: List[Dict[str, Any]]) -> None:
                self.combo_kalender.clear()
                for kal in lista or []:
                    namn = kal.get("summary") or kal.get("id", "")
                    if kal.get("primary"):
                        namn = f"{namn} (huvudkalender)"
                    self.combo_kalender.addItem(namn, kal.get("id"))
                vald = _kalender_id(self.settings, data)
                idx = self.combo_kalender.findData(vald)
                if idx < 0:  # sparat "primary" = huvudkalendern
                    for i, kal in enumerate(lista or []):
                        if kal.get("primary") and vald == gcal.DEFAULT_CALENDAR_ID:
                            idx = i
                            break
                if idx >= 0:
                    self.combo_kalender.setCurrentIndex(idx)
                self._skriv(f"Kalenderlista uppdaterad ({self.combo_kalender.count()} st).")

            run_google_job(self, "Hämtar kalenderlistan", jobb, on_done=klart)

        def _spara_kalenderval(self) -> None:
            """Spara vald kalender i inställningarna (när användaren väljer)."""
            try:
                cid = self.combo_kalender.currentData() or self.combo_kalender.currentText()
                if self.settings is not None and cid:
                    self.settings.set_google_calendar_id(str(cid))
                    self._skriv(f"Kalender vald: {cid}")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara kalenderval: {e}")

        def _on_farg_andrad(self, val: bool) -> None:
            """Spara valet om färgkodning."""
            try:
                if self.settings is not None:
                    self.settings.set_google_calendar_color_by_priority(bool(val))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara färgval: {e}")

        def _on_skicka_alla(self) -> None:
            """Skicka alla aktiva uppgifter som har ett förfallodatum."""
            uppgifter = _aktiva_uppgifter(self.store)
            data = self.data_dir
            # Det som står i rutan gäller (även om användaren inte tryckt Hämta lista)
            cid = str(self.combo_kalender.currentData() or "").strip() \
                or _kalender_id(self.settings, data)
            farg = self.chef_farg.isChecked()
            if not uppgifter:
                _visa_info(self, "Inga uppgifter", "Det finns inga aktiva uppgifter.")
                return

            def jobb(logga):
                logga(f"Skickar upp till {len(uppgifter)} uppgifter till “{cid}”…")
                service = gcal.build_calendar_service(data)
                em = gcal.load_event_map(data)
                res = gcal.push_tasks(service, cid, uppgifter, em,
                                      color_by_priority=farg)
                for r in res["results"][:40]:
                    markering = "✓" if r["ok"] else ("•" if r["action"] == "hoppad" else "✗")
                    logga(f"  {markering} {r['title'][:50]} — {r['action']}"
                          + (f" ({r['message']})" if not r["ok"] else ""))
                return res

            def klart(res: Dict[str, Any]) -> None:
                self._refresh_status()
                text = gcal.summarize(res)
                detaljer = [
                    f"✓ {r['title'][:60]} — {r['action']}"
                    for r in res.get("results", []) if r["ok"]
                ][:12]
                misslyckade = [
                    f"✗ {r['title'][:60]} — {r['message']}"
                    for r in res.get("results", []) if not r["ok"] and r["action"] != "hoppad"
                ][:8]
                box = QMessageBox(self)
                box.setWindowTitle("☁️ Skickat till Google Calendar")
                box.setIcon(QMessageBox.Icon.Information)
                box.setText(text)
                box.setInformativeText(
                    "Uppgifter som redan skickats uppdateras i stället för att "
                    "dubbleras."
                )
                detaljtext = "\n".join(detaljer + misslyckade)
                if detaljtext:
                    box.setDetailedText(detaljtext)
                box.exec()

            run_google_job(
                self,
                "Skickar till Google Calendar",
                jobb,
                beskrivning=f"{len(uppgifter)} aktiva uppgifter skickas till “{cid}”.",
                on_done=klart,
            )

        def _on_oppna_mapp(self) -> None:
            """Öppna mappen där credentials/token ligger."""
            try:
                Path(self.data_dir).mkdir(parents=True, exist_ok=True)
                gcal.google_dir(self.data_dir).mkdir(parents=True, exist_ok=True)
                ok = QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(gcal.google_dir(self.data_dir)))
                )
                if not ok:
                    _visa_info(self, "Mappen", str(gcal.google_dir(self.data_dir)))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte öppna mappen: {e}")

        def _on_oppna_guide(self) -> None:
            """Öppna GOOGLE_CALENDAR.md i standardprogrammet."""
            try:
                guide = Path(__file__).resolve().parent.parent / "GOOGLE_CALENDAR.md"
                if guide.is_file():
                    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide))):
                        _visa_info(self, "Guiden ligger här", str(guide))
                else:
                    QDesktopServices.openUrl(QUrl(gcal.GOOGLE_CONSOLE_CREDENTIALS_URL))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte öppna guiden: {e}")


def _aktiva_uppgifter(store: Any) -> List[Dict[str, Any]]:
    """Hämta aktiva uppgifter ur store på det sätt som finns."""
    if store is None:
        return []
    for namn in ("active_tasks_filtered", "active_tasks"):
        metod = getattr(store, namn, None)
        if callable(metod):
            try:
                if namn == "active_tasks_filtered":
                    uppgifter = metod(sort_by="pinned_first")
                else:
                    uppgifter = metod()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} {namn} misslyckades: {e}")
                continue
            if isinstance(uppgifter, list):
                return [t for t in uppgifter if isinstance(t, dict)
                        and str(t.get("title", "")).strip()]
    return []


# --------------------------------------------------------------------------
# Ingångar (anropas från widgeten och tray-menyn)
# --------------------------------------------------------------------------
def open_google_calendar_dialog(
    parent: Optional[QWidget] = None,
    store: Any = None,
    settings: Any = None,
    data_dir: Any = None,
) -> bool:
    """Visa Google Calendar-dialogen. False om Qt saknas."""
    if not _QT_AVAILABLE:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} Qt saknas — kan inte visa dialogen")
        return False
    try:
        dlg = GoogleCalendarDialog(parent, store=store, settings=settings,
                                   data_dir=data_dir)
        dlg.exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.error(f"{LOG_PREFIX} dialogen misslyckades: {e}", exc_info=True)
        _visa_fel(parent, "Kunde inte öppna Google Calendar-dialogen.",
                  f"{type(e).__name__}: {e}")
        return False


def push_task_with_dialog(
    parent: Optional[QWidget] = None,
    task: Optional[Dict[str, Any]] = None,
    store: Any = None,
    settings: Any = None,
    data_dir: Any = None,
) -> bool:
    """
    Skicka EN uppgift till Google Calendar (från uppgiftsmenyn).

    Är kontot inte kopplat visas en förklaring med väg till dialogen.
    """
    if not task or not str(task.get("title", "")).strip():
        return False
    data = _resolve_data_dir(store, settings, data_dir)

    if not gcal.is_google_library_available():
        _visa_info(
            parent,
            "☁️ Google Calendar",
            "Google-paketen är inte installerade.\n\n"
            f"Kör i en kommandotolk:\n{gcal.install_hint()}\n\n"
            "Sedan kan du koppla kontot under ☁️ Google Calendar.",
        )
        return False

    if not gcal.is_connected(data):
        _visa_info(
            parent,
            "☁️ Google Calendar",
            "Inget Google-konto är kopplat ännu.\n\n"
            "Öppna ☁️ Google Calendar och klicka på “Koppla Google-konto…”.",
        )
        return False

    if gcal.resolve_task_date(task) is None:
        _visa_info(
            parent,
            "📅 Datum saknas",
            "Uppgiften behöver ett förfallodatum för att bli en "
            "kalenderhändelse.",
        )
        return False

    cid = _kalender_id(settings, data)
    farg = _fargkodning(settings)
    titel = str(task.get("title", ""))[:70]

    def jobb(logga):
        logga(f"Skickar “{titel}” till “{cid}”…")
        service = gcal.build_calendar_service(data)
        em = gcal.load_event_map(data)
        r = gcal.push_task(service, cid, task, em, color_by_priority=farg)
        logga(f"{r['action']}: {r['message']}")
        return r

    def klart(r: Dict[str, Any]) -> None:
        if r.get("ok"):
            _visa_info(
                parent,
                "☁️ Skickat till Google Calendar",
                f"“{titel}” — {r.get('message', 'klart')}\n\n"
                "Öppna kalendern för att se händelsen.",
            )
        else:
            _visa_info(parent, "☁️ Kunde inte skicka", str(r.get("message") or "Okänt fel"))

    run_google_job(parent, "Skickar till Google Calendar", jobb, on_done=klart)
    return True
