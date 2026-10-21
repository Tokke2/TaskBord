"""
updater.py — TaskBord: "🔄 Sök ny version" (uppdatering inifrån appen).

Hämtar GitHub-releasen märkt *Latest* och jämför FILINNEHÅLL (sha256) med den
installerade mappen. Versionsnumret behöver alltså inte ändras — releasen får
heta v1.0.0 även när koden under den uppdateras.

Säkerhet / regler:
  * Hämtar BARA från api.github.com / codeload.github.com över https.
  * Rör ALDRIG ``js/`` (uppgifter, inställningar, Google-koppling) eller ``data/``
    (loggar, backuper). Skriver inget utanför appmappen.
  * Alla .py/.pyw i releasen kompileras FÖRE installation — en trasig release kan
    inte skriva över en fungerande app.
  * Ersatta filer sparas i ``data/backups/app-update/<tid>/`` (kan återställas), och
    om något går fel under skrivningen rullas redan ersatta filer tillbaka.
  * Filer som finns lokalt men inte i releasen tas INTE bort.
  * Källan är alltid den senaste RELEASEN (aldrig main eller git pull) — också i en git-mapp,
    där ``.git`` lämnas orörd (filerna syns då som ändrade i git).

Allt utom ``schedule_restart`` är ren Python utan Qt och testas i
``tester/updater_test.py``.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Updater")
LOG_PREFIX = "[UPDATE]"

GITHUB_REPO = "Tokke2/TaskBord"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ALLOWED_HOSTS = frozenset({"api.github.com", "codeload.github.com", "github.com"})
USER_AGENT = "TaskBord-updater"

MAX_ZIP_BYTES = 40 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
MAX_FILES = 3000

# Översta mappar/filer som ALDRIG uppdateras eller rörs
PROTECTED_TOP = frozenset({"js", "data", ".git", "__pycache__", ".venv", "venv"})
SKIP_SUFFIXES = (".pyc", ".pyo")
RESTART_DELAY_SEC = 6


class UpdateError(Exception):
    """Fel med ett meddelande som kan visas för användaren (svenska)."""


@dataclass
class UpdateInfo:
    tag: str = ""
    name: str = ""
    published_at: str = ""
    html_url: str = ""
    commit: str = ""                       # från zip-kommentaren (om GitHub skickar den)
    files: Dict[str, bytes] = field(default_factory=dict, repr=False)
    changed: List[str] = field(default_factory=list)   # nya + ändrade
    new_files: List[str] = field(default_factory=list)
    requirements_changed: bool = False

    @property
    def up_to_date(self) -> bool:
        return not self.changed


# ---------------------------------------------------------------------------
# Nätverk (endast GitHub, endast https)
# ---------------------------------------------------------------------------

class _HostCheckRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url: str) -> None:
    from urllib.parse import urlparse

    p = urlparse(url)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UpdateError(f"Ogiltig nedladdningsadress ({p.hostname}) — avbryter.")


def _http_get(url: str, max_bytes: int, timeout: float = 20.0,
              accept: str = "*/*",
              progress: Optional[Callable[[int, int], None]] = None) -> bytes:
    _check_url(url)
    opener = urllib.request.build_opener(_HostCheckRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with opener.open(req, timeout=timeout) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            buf = bytearray()
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > max_bytes:
                    break
                if progress is not None:
                    progress(len(buf), total)   # kan kasta UpdateError (avbrutet)
            data = bytes(buf)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Hittade ingen release på GitHub.") from e
        if e.code in (403, 429):
            raise UpdateError("GitHub nekade förfrågan (för många anrop?). Försök igen om en stund.") from e
        raise UpdateError(f"GitHub svarade med fel {e.code}.") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise UpdateError("Kunde inte nå GitHub. Kontrollera internetanslutningen.") from e
    if len(data) > max_bytes:
        raise UpdateError("Nedladdningen var större än väntat — avbryter.")
    return data


def fetch_latest_release(
    http_get: Callable[..., bytes] = _http_get,
) -> Dict[str, str]:
    """Metadata för releasen märkt Latest."""
    raw = http_get(LATEST_API, 2 * 1024 * 1024, accept="application/vnd.github+json")
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
        return {
            "tag": str(d.get("tag_name") or ""),
            "name": str(d.get("name") or ""),
            "published_at": str(d.get("published_at") or ""),
            "html_url": str(d.get("html_url") or ""),
            "zip_url": str(d.get("zipball_url") or ""),
        }
    except Exception as e:
        raise UpdateError("Oväntat svar från GitHub.") from e


# ---------------------------------------------------------------------------
# Zip → filer (säker uppackning i minnet)
# ---------------------------------------------------------------------------

def _safe_rel(name: str) -> Optional[str]:
    """Gör zip-namn till säker relativ sökväg (None = hoppa över)."""
    name = name.replace("\\", "/")
    if name.endswith("/"):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return None
    if any(p == ".." or ":" in p for p in parts):
        raise UpdateError(f"Osäker sökväg i releasen: {name!r} — avbryter.")
    return "/".join(parts)


def read_release_zip(zip_bytes: bytes) -> Tuple[Dict[str, bytes], str]:
    """Returnerar ({relativ sökväg: innehåll}, commit-id ur zip-kommentaren)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise UpdateError("Nedladdningen var inte en giltig zip-fil.") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise UpdateError("Releasen innehåller för många filer — avbryter.")
    if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
        raise UpdateError("Releasen är större än väntat — avbryter.")
    # GitHub lägger allt under EN toppmapp (Tokke2-TaskBord-<sha>/) — ta bort den.
    tops = {(_safe_rel(i.filename) or "").split("/")[0] for i in infos}
    strip = len(tops) == 1 and all("/" in (_safe_rel(i.filename) or "") for i in infos)
    files: Dict[str, bytes] = {}
    for i in infos:
        rel = _safe_rel(i.filename)
        if rel is None:
            continue
        if strip:
            rel = rel.split("/", 1)[1]
        top = rel.split("/")[0]
        if top in PROTECTED_TOP or "__pycache__" in rel.split("/") or rel.endswith(SKIP_SUFFIXES):
            continue
        files[rel] = zf.read(i)
    commit = ""
    try:
        commit = (zf.comment or b"").decode("ascii", "ignore").strip()[:40]
    except Exception:
        pass
    if not files:
        raise UpdateError("Releasen var tom.")
    return files, commit


# ---------------------------------------------------------------------------
# Jämförelse, validering, installation
# ---------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare(app_dir: Path, files: Dict[str, bytes]) -> Tuple[List[str], List[str]]:
    """(ändrade+nya, bara nya). Radslut (CRLF/LF) räknas inte som ändring."""
    changed: List[str] = []
    new: List[str] = []
    for rel in sorted(files):
        target = Path(app_dir, *rel.split("/"))
        if not target.is_file():
            changed.append(rel)
            new.append(rel)
            continue
        try:
            local = target.read_bytes()
        except OSError:
            changed.append(rel)
            continue
        if _sha(local) == _sha(files[rel]):
            continue
        if rel.endswith((".py", ".pyw", ".md", ".txt", ".bat", ".ps1", ".json", ".js", ".html")):
            if local.replace(b"\r\n", b"\n") == files[rel].replace(b"\r\n", b"\n"):
                continue
        changed.append(rel)
    return changed, new


def validate(files: Dict[str, bytes], changed: List[str]) -> List[str]:
    """Kompilera alla nya/ändrade Python-filer. Returnerar felmeddelanden (tom = OK)."""
    errors: List[str] = []
    for rel in changed:
        if rel.endswith((".py", ".pyw")):
            try:
                compile(files[rel], rel, "exec")
            except SyntaxError as e:
                errors.append(f"{rel}: rad {e.lineno}: {e.msg}")
            except Exception as e:  # pragma: no cover
                errors.append(f"{rel}: {e}")
    return errors


ProgressCb = Callable[[str, int, int], None]   # (fas, klart, totalt)


def phase_text(phase: str, done: int = 0, total: int = 0) -> str:
    """Svensk text för en förloppsfas (visas i förloppsfönstret)."""
    if phase == "release":
        return "Kontaktar GitHub…"
    if phase == "download":
        mb = done / (1024 * 1024)
        if total > 0:
            return f"Hämtar uppdateringen… {mb:.1f} av {total / (1024 * 1024):.1f} MB"
        return f"Hämtar uppdateringen… {mb:.1f} MB"
    if phase == "compare":
        return "Jämför filer med din installation…"
    if phase == "validate":
        return "Kontrollerar att koden är hel…"
    if phase == "save":
        return "Sparar dina uppgifter först…"
    if phase == "install":
        return f"Installerar filer… {done} av {total}"
    if phase == "done":
        return "Klart!"
    return "Arbetar…"


def fingerprint(info: "UpdateInfo") -> str:
    """Kort ID för just den här uppsättningen ändringar (för att inte tjata om samma uppdatering)."""
    h = hashlib.sha256()
    for rel in sorted(info.changed):
        h.update(rel.encode("utf-8"))
        h.update(_sha(info.files.get(rel, b"")).encode("ascii"))
    return h.hexdigest()[:16]


def check_due(last_check: float, now: Optional[float] = None,
              interval_sec: float = 24 * 3600) -> bool:
    """Har det gått minst ``interval_sec`` sedan senaste lyckade kollen? (klockhopp bakåt räknas som 'dags')."""
    now = time.time() if now is None else now
    if last_check <= 0 or last_check > now:
        return True
    return (now - last_check) >= interval_sec


def check_for_update(
    app_dir: Path,
    http_get: Callable[..., bytes] = _http_get,
    progress: Optional[ProgressCb] = None,
) -> UpdateInfo:
    """Hämta senaste releasen och räkna ut vad som skiljer. Skriver inget till disk."""
    app_dir = Path(app_dir)
    # Uppdateringen hämtas ALLTID från den senaste GitHub-releasen (aldrig från main/git pull) —
    # även i en git-mapp. .git rörs inte (PROTECTED_TOP).
    _p: ProgressCb = progress or (lambda *_a: None)
    _p("release", 0, 0)
    meta = fetch_latest_release(http_get)
    if not meta["zip_url"]:
        raise UpdateError("Releasen saknar nedladdningsbar källkod.")
    _p("download", 0, 0)
    if progress is not None:
        zip_bytes = http_get(
            meta["zip_url"], MAX_ZIP_BYTES, timeout=60.0,
            progress=lambda d, t: _p("download", d, t),
        )
    else:
        zip_bytes = http_get(meta["zip_url"], MAX_ZIP_BYTES, timeout=60.0)
    _p("compare", 0, 0)
    files, commit = read_release_zip(zip_bytes)
    changed, new = compare(app_dir, files)
    _p("validate", 0, 0)
    errors = validate(files, changed)
    if errors:
        raise UpdateError(
            "Releasen innehåller Python-fel och installeras inte:\n  " + "\n  ".join(errors[:5])
        )
    return UpdateInfo(
        tag=meta["tag"], name=meta["name"], published_at=meta["published_at"],
        html_url=meta["html_url"], commit=commit, files=files, changed=changed,
        new_files=new,
        requirements_changed=any(r.startswith("requirements") for r in changed),
    )


def _watchdog():
    """core/update_watchdog.py (heter ``core.update_watchdog`` eller ``update_watchdog`` beroende på sys.path)."""
    try:
        from core import update_watchdog as w
    except ImportError:
        import update_watchdog as w  # type: ignore[no-redef]
    return w


def apply_update(app_dir: Path, info: UpdateInfo,
                 progress: Optional[ProgressCb] = None) -> Path:
    """
    Installera ``info.changed``. Returnerar backupmappen med de ersatta filerna.
    Vid fel rullas allt tillbaka och UpdateError kastas.
    """
    app_dir = Path(app_dir)
    if not info.changed:
        raise UpdateError("Inget att uppdatera.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = app_dir / "data" / "backups" / "app-update" / stamp
    written: List[Tuple[Path, bool]] = []   # (sökväg, fanns innan)
    _p: ProgressCb = progress or (lambda *_a: None)
    total = len(info.changed)
    # Väktaren (self-healing): en kopia av den NUVARANDE, fungerande koden läggs i backupen INNAN
    # något byts, så att den inte påverkas om den nya koden är trasig.
    guard_ok = False
    try:
        guard_ok = _watchdog().copy_self_to(backup_root)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte lägga väktaren i backupen: {e}")
    try:
        for i, rel in enumerate(info.changed, 1):
            _p("install", i - 1, total)
            target = Path(app_dir, *rel.split("/"))
            existed = target.is_file()
            if existed:
                bk = Path(backup_root, *rel.split("/"))
                bk.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, bk)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".update.tmp")
            tmp.write_bytes(info.files[rel])
            os.replace(tmp, target)
            written.append((target, existed))
    except Exception as e:
        logger.error(f"{LOG_PREFIX} installation misslyckades: {e} — rullar tillbaka")
        rollback(app_dir, backup_root, written)
        raise UpdateError(f"Installationen misslyckades och återställdes: {e}") from e
    (backup_root).mkdir(parents=True, exist_ok=True)
    if guard_ok:
        try:
            _watchdog().write_manifest(backup_root, {
                "tag": info.tag, "commit": info.commit, "fingerprint": fingerprint(info),
                "stamp": stamp,
                "replaced": [t.relative_to(app_dir).as_posix() for t, existed in written if existed],
                "new": [t.relative_to(app_dir).as_posix() for t, existed in written if not existed],
            })
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte skriva manifest: {e}")
            guard_ok = False
    _p("done", total, total)
    try:
        (backup_root / "UPPDATERING.txt").write_text(
            f"Release {info.tag} ({info.commit})\n"
            f"Ändrade/nya filer: {len(info.changed)}\n" + "\n".join(info.changed) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    logger.info(f"{LOG_PREFIX} uppdaterade {len(info.changed)} filer (backup: {backup_root})")
    return backup_root


def rollback(app_dir: Path, backup_root: Path, written: List[Tuple[Path, bool]]) -> None:
    for target, existed in reversed(written):
        try:
            if existed:
                rel = target.relative_to(app_dir)
                shutil.copy2(Path(backup_root, *rel.parts), target)
            elif target.exists():
                target.unlink()
        except Exception as e:  # pragma: no cover
            logger.error(f"{LOG_PREFIX} återställning av {target} misslyckades: {e}")


def restore_backup(app_dir: Path, backup_dir: Path) -> int:
    """Lägg tillbaka filerna från en backupmapp (manuell ångra). Returnerar antal."""
    n = 0
    backup_dir = Path(backup_dir)
    for p in backup_dir.rglob("*"):
        if p.is_file() and p.name not in ("UPPDATERING.txt", "manifest.json", "watchdog.py"):
            rel = p.relative_to(backup_dir)
            dst = Path(app_dir, *rel.parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            n += 1
    return n


# ---------------------------------------------------------------------------
# Omstart
# ---------------------------------------------------------------------------

_RESTART_PROGRAM = (
    "import sys, time, subprocess\n"
    "time.sleep(float(sys.argv[1]))\n"
    "kw = {'cwd': sys.argv[3], 'close_fds': True}\n"
    "if sys.platform == 'win32':\n"
    "    kw['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000\n"
    "else:\n"
    "    kw['start_new_session'] = True\n"
    "subprocess.Popen([sys.executable, sys.argv[2]], **kw)\n"
)


def restart_command(app_dir: Path, delay_sec: int = RESTART_DELAY_SEC) -> List[str]:
    """
    Kommando som väntar ``delay_sec`` s och sedan startar appen (pythonw på Windows).

    Hjälparen är ett litet Python-program (``python -c``), INTE ``cmd /c "… start "" …"``:
    Python citerar de inre citattecknen som ``\\"`` och cmd.exe förstår inte det — ``start`` fick då
    en bakstreck som program och Windows svarade "Det går inte att hitta '\\'" (appen startade
    aldrig om efter en uppdatering). Inga citattecken-trick, inga beroenden av cmd.
    """
    exe = _pythonw(sys.executable)
    script = Path(app_dir) / "main.pyw"
    if not script.is_file():
        script = Path(app_dir) / "main.py"
    return [exe, "-c", _RESTART_PROGRAM, str(int(delay_sec)), str(script), str(app_dir)]


def _pythonw(exe: str) -> str:
    if exe.lower().endswith("python.exe"):
        pw = Path(exe).with_name("pythonw.exe")
        if pw.is_file():
            return str(pw)
    return exe


def schedule_restart(app_dir: Path, delay_sec: int = RESTART_DELAY_SEC,
                     backup_root: Optional[Path] = None) -> bool:
    """
    Starta en frikopplad hjälpare som startar om appen när den här har avslutats.

    Med ``backup_root`` (från ``apply_update``) är hjälparen VÄKTAREN: den startar den uppdaterade
    appen och återställer filerna från backupen om appen inte kommit igång inom 60 s
    (se core/update_watchdog.py). Utan backup används den enkla omstartaren.
    """
    try:
        kwargs: Dict[str, object] = {"cwd": str(app_dir), "close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        else:
            kwargs["start_new_session"] = True
        cmd: Optional[List[str]] = None
        if backup_root is not None:
            try:
                w = _watchdog()
                bk = Path(backup_root)
                if (bk / w.WATCHDOG_COPY_NAME).is_file() and (bk / w.MANIFEST_NAME).is_file():
                    script = Path(app_dir) / "main.pyw"
                    if not script.is_file():
                        script = Path(app_dir) / "main.py"
                    meta = json.loads((bk / w.MANIFEST_NAME).read_text(encoding="utf-8"))
                    if w.write_pending(Path(app_dir), {
                        "backup": str(bk), "tag": meta.get("tag", ""), "commit": meta.get("commit", ""),
                        "fingerprint": meta.get("fingerprint", ""),
                    }):
                        cmd = w.guard_command(Path(app_dir), bk, _pythonw(sys.executable), script, delay_sec)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} väktaren kunde inte förberedas ({e}) — vanlig omstart")
        if cmd is None:
            cmd = restart_command(app_dir, delay_sec)
        else:
            logger.info(f"{LOG_PREFIX} omstart med väktare (återställer vid uteblivet start, backup {backup_root})")
        subprocess.Popen(cmd, **kwargs)  # type: ignore[arg-type]
        return True
    except Exception as e:
        logger.error(f"{LOG_PREFIX} kunde inte schemalägga omstart: {e}")
        return False


def describe(info: UpdateInfo, max_files: int = 12) -> str:
    """Kort svensk sammanfattning för dialogen."""
    pub = info.published_at[:10] if info.published_at else "?"
    lines = [
        f"Release {info.tag or '?'} (publicerad {pub}"
        + (f", commit {info.commit[:7]}" if info.commit else "") + ")",
        f"{len(info.changed)} fil(er) skiljer sig från din installation"
        + (f", varav {len(info.new_files)} nya." if info.new_files else "."),
        "",
    ]
    lines += [f"  • {r}" for r in info.changed[:max_files]]
    if len(info.changed) > max_files:
        lines.append(f"  … och {len(info.changed) - max_files} till")
    return "\n".join(lines)
