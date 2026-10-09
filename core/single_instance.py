"""
single_instance.py — TaskBord v7-fix87: instans-meddelandekanal.

UPPGIFT: när en ANDRA instans av TaskBord startar ska den (1) upptäcka
att en redan kör, (2) SIGNALERA den befintliga instansen att visa sitt
fönster, och (3) avsluta sig själv tyst.

Det HÅRDA låset (core/utils.py SingleInstanceLock + main.pyw steg 11)
finns kvar orört och hindrar fortfarande två processer — denna modul
lägger kommunikationen ovanpå:

  Första instansen:  messenger.acquire(nyckel) → lyssnar (QLocalServer)
                     messenger.message_received → visa fönstret
  Andra instansen:   messenger.acquire(nyckel) → False
                     messenger.notify(nyckel, "SHOW") → True = levererat

Teknik: QLocalServer/QLocalSocket (Windows: named pipes — dör med
processen, inga kvarblivna filer; Linux/Unix: domain-socket, städas
med removeServer vid start). Allt på GUI-tråden.

Logg-prefix: [MAIN] (applivscykel)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("SingleInstance")
LOG_PREFIX: str = "[MAIN]"

# Standard-nyckel (per dator + användare — säkert vid snabb användarbyte)
def default_key() -> str:
    """NY v7-fix87: unik nyckel per app + användare."""
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = "användare"
    # endast giltiga tecken i pipe/socket-namn
    safe_user = "".join(c for c in user if c.isalnum() or c in "-_")[:40]
    return f"TaskBord_SingleInstance_{safe_user or 'default'}"


class InstanceMessenger:
    """
    NY v7-fix87: lyssna/meddela mellan TaskBord-instanser.

    Användning (första instansen):
        m = InstanceMessenger()
        if m.acquire(key):
            m.message_received.connect(visa_fönstret)   # Signal(str)
        # behåll m levande; m.close() vid avstängning

    Användning (andra instansen):
        m = InstanceMessenger()
        if not m.acquire(key):
            m.notify(key, "SHOW")   # True = befintlig instans fick det
    """

    def __init__(self) -> None:
        self._server = None
        self._key: Optional[str] = None

    # -- Första instansen ---------------------------------------------------

    def acquire(self, key: str) -> bool:
        """
        Försök bli DEN LYSSNANDE instansen.

        True  = vi är först (servern lyssnar nu — anslut message_received)
        False = en annan instans lyssnar redan (använd notify() sedan)

        FIX (v7-fix87): removeServer får ENBART köras när INGEN lyssnar —
        på Unix raderar den annars den KÖRANDE instansens socket (B kunde
        då lyssna dubbelt och A förlorade sina meddelanden). Därför:
        probea först med QLocalSocket, städa bara döda socket-filer.
        """
        try:
            from PySide6.QtNetwork import QLocalServer, QLocalSocket
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} QLocalServer ej tillgängligt: {e}")
            return False
        try:
            # 1. Finns en LEVANDE lyssnare? (probe — rör inget)
            probe = QLocalSocket()
            probe.connectToServer(key)
            if probe.waitForConnected(300):
                with __import__("contextlib").suppress(Exception):
                    probe.disconnectFromServer()
                logger.info(
                    f"{LOG_PREFIX} instans-kanal '{key}' upptagen — "
                    f"en annan TaskBord körs redan"
                )
                return False
            # 2. Ingen lyssnar — städa eventuell DÖD socket-fil (Unix,
            #    efter krasch) och lyssna
            try:
                QLocalServer.removeServer(key)
            except Exception:
                pass
            server = QLocalServer()
            if not server.listen(key):
                logger.info(
                    f"{LOG_PREFIX} instans-kanal '{key}' kunde ej lyssna — "
                    f"en annan TaskBord körs troligen redan"
                )
                return False
            server.newConnection.connect(self._on_new_connection)
            self._server = server
            self._key = key
            logger.debug(
                f"{LOG_PREFIX} instans-kanal lyssnar: '{key}' (v7-fix87)"
            )
            return True
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} acquire misslyckades: {e}")
            return False

    def _on_new_connection(self) -> None:
        """En annan instans anslöt — läs meddelandet och sänd signalen."""
        try:
            if self._server is None:
                return
            while self._server.hasPendingConnections():
                socket = self._server.nextPendingConnection()
                if socket is None:
                    continue
                msg = ""
                with __import__("contextlib").suppress(Exception):
                    if socket.waitForReadyRead(1500):
                        msg = bytes(socket.readAll()).decode(
                            "utf-8", errors="replace"
                        ).strip()
                with __import__("contextlib").suppress(Exception):
                    socket.disconnectFromServer()
                if not msg:
                    # Tom anslutning = probe (någon kollade bara om vi
                    # lever) — INGEN visning av fönstret
                    logger.debug(
                        f"{LOG_PREFIX} tom anslutning (probe) — ignorerar"
                    )
                    continue
                logger.info(
                    f"{LOG_PREFIX} meddelande från andra instansen: "
                    f"{msg!r} (v7-fix87)"
                )
                self.message_received.emit(msg)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _on_new_connection: {e}")

    # Qt-signal (definieras klass-mässigt nedan via PySide6)
    message_received = None

    def close(self) -> None:
        """Stäng servern (vid avstängning)."""
        try:
            if self._server is not None:
                self._server.close()
                self._server = None
                logger.debug(f"{LOG_PREFIX} instans-kanal stängd")
        except Exception:
            pass

    # -- Andra instansen ----------------------------------------------------

    def notify(self, key: str, message: str = "SHOW") -> bool:
        """
        Signalera den BEFINTLIGA instansen.

        True  = meddelandet levererat (den andra instansen visar sig nu)
        False = ingen lyssnade (kanske kraschad — fortsätt normalt)
        """
        try:
            from PySide6.QtNetwork import QLocalSocket
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} QLocalSocket ej tillgängligt: {e}")
            return False
        try:
            sock = QLocalSocket()
            sock.connectToServer(key)
            if not sock.waitForConnected(1500):
                logger.debug(
                    f"{LOG_PREFIX} ingen instans lyssnar på '{key}'"
                )
                return False
            sock.write(message.encode("utf-8"))
            delivered = sock.waitForBytesWritten(1500)
            with __import__("contextlib").suppress(Exception):
                sock.disconnectFromServer()
            if delivered:
                logger.info(
                    f"{LOG_PREFIX} befintlig instans signalerad "
                    f"({message!r}) — den visar sitt fönster (v7-fix87)"
                )
            return bool(delivered)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} notify misslyckades: {e}")
            return False


# Qt-signalen måste vara en riktig PySide6-Signal — bygg upp klassen
# dynamiskt när Qt finns (samma mönster som övriga moduler i projektet).
try:
    from PySide6.QtCore import QObject, Signal  # noqa: E402

    class _InstanceMessengerQt(QObject, InstanceMessenger):
        """InstanceMessenger med riktig Qt-signal (message_received)."""

        message_received = Signal(str)

    # Exportera Qt-versionen under huvudnamnet
    InstanceMessenger = _InstanceMessengerQt  # type: ignore[misc]

except Exception:  # Qt saknas → fallback utan signal (notify/acquire = False)
    pass
