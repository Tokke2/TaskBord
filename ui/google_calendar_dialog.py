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
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[GCAL-UI]"

try:
    from PySide6.QtCore import QDate, QTimer, Qt, QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout, QLabel, QLineEdit,
        QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
        QFileDialog, QHeaderView, QTableWidget, QTableWidgetItem, QAbstractItemView, QProgressBar, QPushButton, QVBoxLayout, QWidget,
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


def _done_style(settings: Any = None) -> str:
    """Hur klara uppgifter ska se ut i kalendern (grey | strike | off)."""
    if settings is not None:
        try:
            f = getattr(settings, "google_calendar_done_style", None)
            if callable(f):
                v = str(f())
                if v in gcal.DONE_STYLES:
                    return v
        except Exception:
            pass
    return gcal.DEFAULT_DONE_STYLE


def _open_url(url: str) -> bool:
    """Öppna en adress i webbläsaren (Qt först, annars webbbrowser)."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        logger.warning(f"{LOG_PREFIX} ogiltig adress, öppnas inte: {url!r}")
        return False
    if _QT_AVAILABLE:
        try:
            if QDesktopServices.openUrl(QUrl(url)):
                return True
        except Exception:
            pass
    try:
        import webbrowser
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    try:
        if hasattr(os, "startfile"):
            os.startfile(url)  # type: ignore[attr-defined]  # Windows
            return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte öppna {url}: {e}")
    return False


def _fraga_datum(parent: Optional[QWidget], titel: str) -> Optional[str]:
    """Fråga efter ett datum (kalenderväljare). Returnerar "ÅÅÅÅ-MM-DD" eller None vid Avbryt."""
    if not _QT_AVAILABLE:  # pragma: no cover
        return None
    try:
        dlg = QDialog(parent)
        dlg.setWindowTitle("📅 Välj datum")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        txt = QLabel(f"“{titel}” saknar datum.\nVälj vilken dag uppgiften ska ligga på i kalendern:", dlg)
        txt.setWordWrap(True)
        lay.addWidget(txt)
        de = QDateEdit(QDate.currentDate(), dlg)
        de.setCalendarPopup(True)
        de.setDisplayFormat("yyyy-MM-dd")
        de.setMinimumHeight(30)
        lay.addWidget(de)
        rad = QHBoxLayout()
        rad.addStretch(1)
        avbryt = QPushButton("Avbryt", dlg)
        ok = QPushButton("Använd datum och skicka", dlg)
        ok.setDefault(True)
        avbryt.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        rad.addWidget(avbryt)
        rad.addWidget(ok)
        lay.addLayout(rad)
        dlg.setMinimumWidth(380)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return de.date().toString("yyyy-MM-dd")
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} datumdialogen misslyckades: {e}")
        return None


def _efter_koppling(settings: Any, data_dir: Any) -> None:
    """Kom ihåg kopplingen och vald kalender i inställningarna (efter lyckad inloggning)."""
    _spara_ansluten(settings, data_dir, True)
    try:
        if settings is not None:
            konto = gcal.load_account_info(data_dir) or {}
            cid = konto.get("calendar_id")
            if cid:
                settings.set_google_calendar_id(str(cid))
    except Exception:
        pass


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

    class TaskPickerDialog(QDialog):
        """
        Användaren väljer själv vilka uppgifter som skickas till kalendern.

        Inget är förkryssat från start. Uppgifter utan förfallodatum/startdatum visas
        men går inte att välja; redan skickade märks med ☁️ (de uppdateras
        i stället för att dubbleras).
        """

        def __init__(self, rader: List[Dict[str, Any]], parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.setWindowTitle("Välj uppgifter att skicka")
            self.setModal(True)
            self.setMinimumSize(520, 440)
            self._rader = rader

            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)
            rot.addWidget(QLabel(
                "Kryssa i de uppgifter som ska skickas till din kalender. "
                "Inget skickas som du inte valt.", self))

            self.filter = QLineEdit(self)
            self.filter.setPlaceholderText("🔍 Filtrera på titel…")
            self.filter.textChanged.connect(self._filtrera)
            rot.addWidget(self.filter)

            self.lista = QListWidget(self)
            ikon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            for r in rader:
                text = f"{ikon.get(r['priority'], '⚪')} {r['title']}"
                text += f"   — {r.get('span') or r['due']}" if r["due"] else f"   — ({r['reason']})"
                if r.get("done"):
                    text += "   ✔ klar — händelsen markeras som klar"
                if r["sent"]:
                    text += "   ☁️ redan skickad"
                it = QListWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, r["id"])
                if r["sendable"]:
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(Qt.CheckState.Unchecked)
                else:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled
                                & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.lista.addItem(it)
            self.lista.itemChanged.connect(lambda _i: self._uppdatera_antal())
            rot.addWidget(self.lista, 1)

            rad = QHBoxLayout()
            for namn, fn in (("Markera alla synliga", lambda: self._satt(True, False)),
                             ("Bara osända", lambda: self._satt(True, True)),
                             ("Avmarkera alla", lambda: self._satt(False, False))):
                b = QPushButton(namn, self)
                b.clicked.connect(fn)
                rad.addWidget(b)
            rad.addStretch(1)
            rot.addLayout(rad)

            nederst = QHBoxLayout()
            self.antal = QLabel("", self)
            nederst.addWidget(self.antal, 1)
            avbryt = QPushButton("Avbryt", self)
            avbryt.clicked.connect(self.reject)
            nederst.addWidget(avbryt)
            self.btn_skicka = QPushButton("☁️ Skicka valda", self)
            self.btn_skicka.setDefault(True)
            self.btn_skicka.clicked.connect(self.accept)
            nederst.addWidget(self.btn_skicka)
            rot.addLayout(nederst)
            self._uppdatera_antal()

        def _filtrera(self, text: str) -> None:
            q = text.strip().lower()
            for i in range(self.lista.count()):
                it = self.lista.item(i)
                it.setHidden(bool(q) and q not in it.text().lower())

        def _satt(self, markerad: bool, bara_osanda: bool) -> None:
            sent = {r["id"]: r["sent"] for r in self._rader}
            self.lista.blockSignals(True)
            for i in range(self.lista.count()):
                it = self.lista.item(i)
                if it.isHidden() or not (it.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                if bara_osanda and sent.get(it.data(Qt.ItemDataRole.UserRole)):
                    continue
                it.setCheckState(Qt.CheckState.Checked if markerad
                                 else Qt.CheckState.Unchecked)
            self.lista.blockSignals(False)
            self._uppdatera_antal()

        def valda_ids(self) -> List[str]:
            ut: List[str] = []
            for i in range(self.lista.count()):
                it = self.lista.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    ut.append(str(it.data(Qt.ItemDataRole.UserRole)))
            return ut

        def _uppdatera_antal(self) -> None:
            n = len(self.valda_ids())
            self.antal.setText(f"{n} valda")
            self.btn_skicka.setEnabled(n > 0)

    class GoogleSetupWizard(QDialog):
        """
        Guidad första koppling: steg för steg från noll till inloggad.

        Appen kontrollerar själv det den kan (paket, credentials.json,
        inloggning). Engångsstegen hos Google kan bara du bekräfta.
        Nästa-knappen på filsteget är låst tills credentials.json klarar
        kontrollen — så inloggningen aldrig startar med en trasig fil.
        """

        def __init__(self, data_dir: Any, parent: Optional[QWidget] = None,
                     start_key: Optional[str] = None) -> None:
            super().__init__(parent)
            self.data_dir = Path(str(data_dir))
            self.vill_koppla = False
            self._manual: Dict[str, bool] = {}
            self._steg = gcal.setup_steps(self.data_dir)
            self.setWindowTitle("🧭 Guidad installation — Google Calendar")
            self.setModal(True)
            self.setMinimumSize(540, 420)

            rot = QVBoxLayout(self)
            rot.setContentsMargins(18, 16, 18, 14)
            rot.setSpacing(10)
            self.oversikt = QLabel("", self)
            self.oversikt.setStyleSheet("font-size: 15px;")
            rot.addWidget(self.oversikt)
            self.rubrik = QLabel("", self)
            self.rubrik.setStyleSheet("font-size: 17px; font-weight: 800;")
            rot.addWidget(self.rubrik)
            self.text = QLabel("", self)
            self.text.setWordWrap(True)
            self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            rot.addWidget(self.text, 1)

            self.rad_atgarder = QHBoxLayout()
            self.rad_atgarder.setSpacing(8)
            rot.addLayout(self.rad_atgarder)
            self.chk_klart = QCheckBox("Jag har gjort det här steget", self)
            self.chk_klart.toggled.connect(self._on_manuell)
            rot.addWidget(self.chk_klart)

            nav = QHBoxLayout()
            self.btn_bak = QPushButton("◀ Tillbaka", self)
            self.btn_bak.clicked.connect(lambda: self._gar(-1))
            nav.addWidget(self.btn_bak)
            nav.addStretch(1)
            self.btn_fram = QPushButton("Nästa ▶", self)
            self.btn_fram.setDefault(True)
            self.btn_fram.clicked.connect(lambda: self._gar(1))
            nav.addWidget(self.btn_fram)
            stang = QPushButton("Stäng", self)
            stang.clicked.connect(self.reject)
            nav.addWidget(stang)
            rot.addLayout(nav)

            self.index = 0
            if start_key:
                self.index = next((i for i, s_ in enumerate(self._steg)
                                   if s_["key"] == start_key), 0)
            else:  # börja vid första steget appen vet är ogjort
                self.index = next((i for i, s_ in enumerate(self._steg)
                                   if s_["done"] is False), 0)
            self._visa()

        def _on_manuell(self, val: bool) -> None:
            self._manual[self._steg[self.index]["key"]] = bool(val)
            self._visa(rebuild=False)

        def _gar(self, d: int) -> None:
            self.index = max(0, min(len(self._steg) - 1, self.index + d))
            self._visa()

        def _klart(self, steg: Dict[str, Any]) -> bool:
            if steg["done"] is None:
                return bool(self._manual.get(steg["key"]))
            return bool(steg["done"])

        def _knapp(self, text: str, fn: Callable[[], None]) -> None:
            b = QPushButton(text, self)
            # clicked(bool) skickar "checked" som första argument — det får aldrig skriva över
            # en lambdas standardvärde (då blev adressen False och länken öppnades aldrig).
            b.clicked.connect(lambda _checked=False, _f=fn: _f())
            self.rad_atgarder.addWidget(b)

        def _visa(self, rebuild: bool = True) -> None:
            if rebuild:
                self._steg = gcal.setup_steps(self.data_dir)
            st = self._steg[self.index]
            n = len(self._steg)
            symboler = []
            for i, s_ in enumerate(self._steg):
                if i == self.index:
                    symboler.append("➡️")
                else:
                    symboler.append("✅" if self._klart(s_) else "⬜")
            self.oversikt.setText(" ".join(symboler))
            self.rubrik.setText(f"Steg {self.index + 1} av {n} — {st['title']}")
            self.text.setText(st["text"])

            while self.rad_atgarder.count():
                it = self.rad_atgarder.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.deleteLater()
            if st.get("url"):
                url = st["url"]
                self._knapp("🌐 Öppna sidan hos Google", lambda u=url: _open_url(u))
            if st["key"] == "file":
                self._knapp("📂 Öppna mappen", self._oppna_mapp)
                self._knapp("📥 Välj fil…", self._valj_fil)
                self._knapp("🔍 Leta i Hämtade filer", self._leta)
                self._knapp("🔄 Kontrollera igen", lambda: self._visa())
            if st["key"] == "login":
                self._knapp("🔑 Koppla Google-konto…", self._koppla)
            self.rad_atgarder.addStretch(1)

            self.chk_klart.blockSignals(True)
            self.chk_klart.setVisible(st["done"] is None)
            self.chk_klart.setChecked(bool(self._manual.get(st["key"])))
            self.chk_klart.blockSignals(False)

            self.btn_bak.setEnabled(self.index > 0)
            sista = self.index == n - 1
            self.btn_fram.setVisible(not sista)
            # Låst tills filen klarar kontrollen
            self.btn_fram.setEnabled(not (st["key"] == "file" and st["done"] is False))

        def _oppna_mapp(self) -> None:
            try:
                gcal.google_dir(self.data_dir).mkdir(parents=True, exist_ok=True)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(gcal.google_dir(self.data_dir))))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte öppna mappen: {e}")

        def _installera(self, fil: Any) -> None:
            res = gcal.install_credentials_file(fil, self.data_dir)
            if res.get("installed"):
                _visa_info(self, "✅ Filen är kopierad",
                           "credentials.json ser rätt ut och ligger nu på rätt plats.")
            else:
                _visa_fel(self, "Filen kan inte användas:\n\n• "
                          + "\n• ".join(res.get("problems") or ["okänt fel"]))
            self._visa()

        def _valj_fil(self) -> None:
            start = str(Path.home() / "Downloads")
            fil, _ = QFileDialog.getOpenFileName(
                self, "Välj nedladdad JSON-fil från Google", start,
                "JSON-filer (*.json);;Alla filer (*.*)")
            if fil:
                self._installera(fil)

        def _leta(self) -> None:
            hittad = gcal.find_downloaded_credentials()
            if hittad is None:
                _visa_info(self, "Hittade ingen fil",
                           "Ingen giltig client_secret*.json låg i Hämtade filer.\n"
                           "Använd “Välj fil…” om du sparade den någon annanstans.")
                return
            self._installera(hittad)

        def _koppla(self) -> None:
            self.vill_koppla = True
            self.accept()

    class HistoryDialog(QDialog):
        """Vad som skickats till kalendern: när, vilken uppgift och resultat."""

        def __init__(self, data_dir: Any, parent: Optional[QWidget] = None,
                     task_id: Optional[str] = None, task_title: str = "") -> None:
            super().__init__(parent)
            self.data_dir = Path(str(data_dir))
            self.task_id = task_id
            self.setWindowTitle("🕘 Sändningshistorik" + (f" — {task_title}" if task_title else ""))
            self.setModal(True)
            self.setMinimumSize(640, 380)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)

            self.tabell = QTableWidget(0, 4, self)
            self.tabell.setHorizontalHeaderLabels(["Tid", "Uppgift", "Resultat", "Kalender"])
            self.tabell.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.tabell.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.tabell.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.tabell.verticalHeader().setVisible(False)
            hdr = self.tabell.horizontalHeader()
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.tabell.itemSelectionChanged.connect(self._uppdatera_knappar)
            self.tabell.cellDoubleClicked.connect(lambda _r, _c: self._oppna())
            rot.addWidget(self.tabell, 1)

            self.tom = QLabel("", self)
            rot.addWidget(self.tom)

            rad = QHBoxLayout()
            self.btn_oppna = QPushButton("🔗 Öppna i Google Calendar", self)
            self.btn_oppna.clicked.connect(self._oppna)
            rad.addWidget(self.btn_oppna)
            self.btn_rensa = QPushButton("🗑 Rensa historiken", self)
            self.btn_rensa.setVisible(task_id is None)
            self.btn_rensa.clicked.connect(self._rensa)
            rad.addWidget(self.btn_rensa)
            rad.addStretch(1)
            stang = QPushButton("Stäng", self)
            stang.clicked.connect(self.accept)
            rad.addWidget(stang)
            rot.addLayout(rad)
            self._fyll()

        def _fyll(self) -> None:
            hist = gcal.load_history(self.data_dir)
            poster = hist.for_task(self.task_id) if self.task_id else hist.all()
            self._poster = poster
            self.tabell.setRowCount(len(poster))
            for r, e in enumerate(poster):
                rader = [gcal.history_time_text(e), str(e.get("title") or ""),
                         gcal.history_result_text(e), str(e.get("calendar_id") or "")]
                for c, txt in enumerate(rader):
                    it = QTableWidgetItem(txt)
                    it.setToolTip(str(e.get("message") or ""))
                    self.tabell.setItem(r, c, it)
            self.tom.setText("" if poster else "Ingenting har skickats till kalendern ännu.")
            self._uppdatera_knappar()

        def _vald(self) -> Optional[Dict[str, Any]]:
            rader = self.tabell.selectionModel().selectedRows()
            if not rader:
                return None
            i = rader[0].row()
            return self._poster[i] if 0 <= i < len(self._poster) else None

        def _uppdatera_knappar(self) -> None:
            e = self._vald()
            self.btn_oppna.setEnabled(bool(e and e.get("ok")))
            self.btn_rensa.setEnabled(bool(self._poster))

        def _oppna(self) -> None:
            e = self._vald()
            if e and e.get("ok"):
                _open_url(gcal.calendar_open_url(e))

        def _rensa(self) -> None:
            svar = QMessageBox.question(
                self, "Rensa historiken",
                "Vill du rensa historiken? Händelserna i Google Calendar "
                "påverkas inte.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if svar == QMessageBox.StandardButton.Yes:
                gcal.load_history(self.data_dir).clear()
                self._fyll()

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

            rad_klar = QHBoxLayout()
            rad_klar.addWidget(QLabel("Klara uppgifter i kalendern:", self))
            self.combo_klar = QComboBox(self)
            self.combo_klar.addItem("✅ Grå + bock framför titeln", "grey")
            self.combo_klar.addItem("Överstruken titel + grå", "strike")
            self.combo_klar.addItem("Ingen särskild markering", "off")
            self.combo_klar.setToolTip(
                "Google Calendar kan inte stryka över en heldagshändelse, så en\n"
                "klar uppgift markeras med grå färg och bock (eller överstruken text).\n"
                "Skicka uppgiften igen för att uppdatera händelsen."
            )
            idx_klar = self.combo_klar.findData(_done_style(settings))
            self.combo_klar.setCurrentIndex(max(0, idx_klar))
            self.combo_klar.activated.connect(lambda _i: self._on_klar_andrad())
            rad_klar.addWidget(self.combo_klar, 1)
            rot.addLayout(rad_klar)

            # --- skicka uppgifter ----------------------------------------
            rad3 = QHBoxLayout()
            rad3.setSpacing(8)
            self.btn_skicka_alla = QPushButton("☁️ Välj uppgifter att skicka…", self)
            self.btn_skicka_alla.setToolTip(
                "Du väljer själv vilka uppgifter som skickas.\n"
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

            self.btn_wizard = QPushButton("🧭 Guidad installation", self)
            self.btn_wizard.setToolTip("Steg för steg från noll till inloggad")
            self.btn_wizard.clicked.connect(lambda: self._oppna_wizard())
            rad4.addWidget(self.btn_wizard)

            self.btn_historik = QPushButton("🕘 Historik", self)
            self.btn_historik.setToolTip("Vad som skickats till kalendern, när och med vilket resultat")
            self.btn_historik.clicked.connect(self._on_historik)
            rad4.addWidget(self.btn_historik)

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

            # Första gången (ingen credentials.json): starta guiden automatiskt
            try:
                st0 = gcal.get_status(self.data_dir)
                if st0["state"] in (gcal.ConnectionStatus.NOT_CONFIGURED,):
                    QTimer.singleShot(0, lambda: self._oppna_wizard())
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Guide och historik
        # ------------------------------------------------------------------
        def _oppna_wizard(self, start_key: Optional[str] = None) -> None:
            """Öppna den guidade installationen; kopplar direkt om användaren vill."""
            w = GoogleSetupWizard(self.data_dir, self, start_key=start_key)
            w.exec()
            self._refresh_status()
            if w.vill_koppla:
                self._on_koppla()

        def _on_historik(self) -> None:
            HistoryDialog(self.data_dir, self).exec()

        def _on_klar_andrad(self) -> None:
            try:
                if self.settings is not None:
                    self.settings.set_google_calendar_done_style(
                        str(self.combo_klar.currentData()))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara klar-stil: {e}")

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
                    + ("(krypterat — kan bara läsas av ditt Windows-konto på den här datorn)."
                       if gcal.is_token_protected(st["token_file"])
                       else "(sparas bara lokalt, rättigheter 0600).")
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

            # Kontrollera credentials.json INNAN webbläsaren öppnas
            cred = gcal.discover_credentials_file(data)
            kontroll = gcal.validate_credentials_file(cred) if cred else None
            if not kontroll or not kontroll["ok"]:
                _visa_info(
                    self, "🧭 credentials.json behöver åtgärdas",
                    ("Filen saknas." if not kontroll else
                     "Filen går inte att använda:\n\n• " + "\n• ".join(kontroll["problems"]))
                    + "\n\nGuiden öppnas så att du kan åtgärda det.")
                self._oppna_wizard("file")
                return

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
            """Låt användaren välja uppgifter och skicka bara dem."""
            data = self.data_dir
            alla = _uppgifter_for_valjaren(self.store, gcal.load_event_map(data))
            if not alla:
                _visa_info(self, "Inga uppgifter", "Det finns inga aktiva uppgifter.")
                return
            rader = gcal.describe_tasks_for_picker(alla, gcal.load_event_map(data))
            val = TaskPickerDialog(rader, self)
            if val.exec() != QDialog.DialogCode.Accepted:
                return
            uppgifter = gcal.select_tasks_by_ids(alla, val.valda_ids())
            # Det som står i rutan gäller (även om användaren inte tryckt Hämta lista)
            cid = str(self.combo_kalender.currentData() or "").strip() \
                or _kalender_id(self.settings, data)
            farg = self.chef_farg.isChecked()
            klar_stil = str(self.combo_klar.currentData() or gcal.DEFAULT_DONE_STYLE)
            if not uppgifter:
                return

            def jobb(logga):
                logga(f"Skickar {len(uppgifter)} valda uppgifter till {len(uppgifter)} uppgifter till “{cid}”…")
                service = gcal.build_calendar_service(data)
                em = gcal.load_event_map(data)
                res = gcal.push_tasks(service, cid, uppgifter, em,
                                      color_by_priority=farg, done_style=klar_stil,
                                      history=gcal.load_history(data))
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
                beskrivning=f"{len(uppgifter)} valda uppgifter skickas till “{cid}”.",
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


def _uppgifter_for_valjaren(store: Any, event_map: Any = None) -> List[Dict[str, Any]]:
    """
    Aktiva uppgifter + arkiverade (klara) uppgifter som redan skickats.

    De senare behövs för att en uppgift som blivit klar — och därför
    flyttats till arkivet — ska kunna uppdatera sin händelse till "klar".
    """
    uppgifter = _aktiva_uppgifter(store)
    try:
        arkiv = getattr(store, "archive_tasks", None)
        if callable(arkiv) and event_map is not None:
            har = {str(t.get("id")) for t in uppgifter}
            for t in arkiv():
                tid = str(t.get("id") or "")
                if (isinstance(t, dict) and tid and tid not in har
                        and event_map.get(tid) and str(t.get("title", "")).strip()):
                    uppgifter.append(t)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte läsa arkivet: {e}")
    return uppgifter


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

    if gcal.resolve_task_date(task) is None:
        # Datum saknas → fråga i stället för att avvisa. Datumet sparas som uppgiftens förfallodatum.
        valt = _fraga_datum(parent, str(task.get("title", ""))[:70])
        if not valt:
            return False
        task = dict(task)
        task["due_date"] = valt
        try:
            tid = str(task.get("id", ""))
            if store is not None and tid and hasattr(store, "set_due_date"):
                store.set_due_date(tid, valt)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte spara datumet på uppgiften: {e}")

    # Enkel koppling: är kontot inte kopplat öppnas Googles inloggningssida direkt härifrån
    # (logga in + godkänn), och uppgiften skickas sedan automatiskt.
    behover_koppling = not gcal.is_connected(data)
    if behover_koppling:
        cred = gcal.discover_credentials_file(data)
        kontroll = gcal.validate_credentials_file(cred) if cred else None
        if not kontroll or not kontroll["ok"]:
            # Ingen klient finns (varken medföljande eller egen) → guiden hjälper till.
            _visa_info(
                parent,
                "☁️ Google Calendar",
                "Kopplingen till Google är inte färdig att använda ännu.\n\n"
                "Guiden öppnas så att du kan slutföra den.",
            )
            try:
                w = GoogleSetupWizard(data, parent)
                w.exec()
                if w.vill_koppla:
                    return push_task_with_dialog(parent, task, store, settings, data_dir)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} guiden kunde inte öppnas: {e}")
            return False

    cid = _kalender_id(settings, data)
    farg = _fargkodning(settings)
    klar_stil = _done_style(settings)
    titel = str(task.get("title", ""))[:70]

    def jobb(logga):
        nyss_kopplad = False
        if behover_koppling:
            logga("Öppnar Googles inloggningssida i webbläsaren…")
            logga("Logga in och godkänn åtkomsten till din kalender. "
                  "Det här fönstret väntar i upp till 5 minuter.")
            gcal.authenticate_google_calendar(data, open_browser=True, on_url=lambda _u: None)
            nyss_kopplad = True
            logga("✓ Kopplat.")
        logga(f"Skickar “{titel}” till “{cid}”…")
        service = gcal.build_calendar_service(data)
        em = gcal.load_event_map(data)
        r = gcal.push_task(service, cid, task, em, color_by_priority=farg,
                           done_style=klar_stil, history=gcal.load_history(data))
        r = dict(r)
        r["_nyss_kopplad"] = nyss_kopplad
        logga(f"{r['action']}: {r['message']}")
        return r

    def klart(r: Dict[str, Any]) -> None:
        if r.get("_nyss_kopplad"):
            _efter_koppling(settings, data)
        if r.get("ok"):
            try:
                box = QMessageBox(parent)
                box.setIcon(QMessageBox.Icon.Information)
                box.setWindowTitle("☁️ Skickat till Google Calendar")
                box.setText(f"“{titel}” — {r.get('message', 'klart')}")
                knapp = box.addButton("🔗 Öppna i Google Calendar",
                                      QMessageBox.ButtonRole.ActionRole)
                box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
                box.exec()
                if box.clickedButton() is knapp:
                    dag = gcal.resolve_task_date(task)
                    _open_url(gcal.calendar_open_url({
                        "html_link": r.get("html_link", ""),
                        "due": dag.isoformat() if dag else "",
                    }))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} resultatruta misslyckades: {e}")
        else:
            _visa_info(parent, "☁️ Kunde inte skicka", str(r.get("message") or "Okänt fel"))

    run_google_job(parent, "Skickar till Google Calendar", jobb, on_done=klart)
    return True


def open_history_dialog(
    parent: Optional[QWidget] = None,
    task: Optional[Dict[str, Any]] = None,
    store: Any = None,
    settings: Any = None,
    data_dir: Any = None,
) -> bool:
    """
    Visa sändningshistoriken (för en uppgift om `task` ges, annars alla).
    """
    if not _QT_AVAILABLE:  # pragma: no cover
        return False
    try:
        data = _resolve_data_dir(store, settings, data_dir)
        tid = str((task or {}).get("id") or "") or None
        HistoryDialog(data, parent, task_id=tid,
                      task_title=str((task or {}).get("title") or "")[:50]).exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.error(f"{LOG_PREFIX} historikdialogen misslyckades: {e}", exc_info=True)
        return False
