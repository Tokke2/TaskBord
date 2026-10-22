#!/usr/bin/env bash
# ============================================================================
#  Ledgebord – första start / start (macOS och Linux)
#
#  Motsvarar FORSTA_START.bat på Windows. Allt hamnar i appmappen (.venv) –
#  inget installeras i systemets Python och inget skrivs utanför mappen.
#
#    ./starta.sh               installerar vid behov och startar Ledgebord i bakgrunden
#    ./starta.sh --forgrund    startar i terminalen (visar fel direkt)
#    ./starta.sh --snabb       hoppar över paketinstallation
#    ./starta.sh --installera  tvingar ominstallation/uppgradering av paketen
#    ./starta.sh --hjalp
#
#  Kräver Python 3.10 eller nyare (python3 med venv-stöd).
# ============================================================================
set -u
cd "$(dirname "$0")" || exit 1
APPDIR="$(pwd)"
VENV="$APPDIR/.venv"
STAMP="$VENV/.taskbord_paket"

FORGRUND=0; SNABB=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --forgrund) FORGRUND=1 ;;
    --snabb) SNABB=1 ;;
    --installera) FORCE=1 ;;
    -h|--hjalp|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Okänt val: $a (se --hjalp)"; exit 2 ;;
  esac
done

[ -f "$APPDIR/main.pyw" ] || { echo "main.pyw saknas i $APPDIR"; exit 1; }

# --- hitta Python 3.10+ ------------------------------------------------------
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 eller nyare hittades inte."
  echo "  macOS:   brew install python   (eller https://www.python.org/downloads/)"
  echo "  Debian/Ubuntu: sudo apt install python3 python3-venv"
  echo "  Fedora:  sudo dnf install python3"
  exit 1
fi

# --- skapa den lokala miljön -------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  echo "Skapar lokal Python-miljö i $VENV ..."
  if ! "$PY" -m venv "$VENV"; then
    rm -rf "$VENV"
    echo "Kunde inte skapa venv. På Debian/Ubuntu: sudo apt install python3-venv"
    exit 1
  fi
  FORCE=1
fi
VPY="$VENV/bin/python"

# --- installera paket när kraven ändrats (eller första gången) --------------
hash_krav() {
  cat "$APPDIR/requirements.txt" "$APPDIR/requirements-optional.txt" 2>/dev/null | "$VPY" -c \
    'import sys,hashlib; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}
if [ "$SNABB" = "0" ] && [ -f "$APPDIR/requirements.txt" ]; then
  NOW="$(hash_krav)"
  if [ "$FORCE" = "1" ] || [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$NOW" ]; then
    echo "Installerar paket (kan ta någon minut första gången) ..."
    "$VPY" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1
    if ! "$VPY" -m pip install --quiet --disable-pip-version-check -r "$APPDIR/requirements.txt"; then
      echo "Paketinstallationen misslyckades. Kontrollera internetanslutningen och kör igen."
      exit 1
    fi
    if [ -f "$APPDIR/requirements-optional.txt" ]; then
      "$VPY" -m pip install --quiet --disable-pip-version-check -r "$APPDIR/requirements-optional.txt" \
        || echo "(Valfria paket kunde inte installeras – PDF/Google/.msg-import kan saknas.)"
    fi
    echo "$NOW" > "$STAMP"
  fi
fi

# --- starta ------------------------------------------------------------------
if [ "$FORGRUND" = "1" ]; then
  exec "$VPY" "$APPDIR/main.pyw"
fi
nohup "$VPY" "$APPDIR/main.pyw" >/dev/null 2>&1 &
echo "Ledgebord startad (PID $!). Loggar finns i $APPDIR/data/. Starta med --forgrund för att se fel."
