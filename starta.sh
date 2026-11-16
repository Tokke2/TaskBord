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
#  Kräver Python 3.10 eller nyare (python3 med venv-stöd). Saknas Python erbjuder skriptet att installera den (frågar
#  då en gång); finns Python frågar det aldrig. Svar utan terminal: LEDGEBORD_SVAR=j.
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
# Systemets egen Python (python3 / python i PATH) används om den duger; först om den är för gammal letar vi efter
# versionsnamn. Python uppdateras aldrig härifrån.
hitta_python() {
  PY=""
  for c in ${LEDGEBORD_PY_KANDIDATER:-python3 python python3.14 python3.13 python3.12 python3.11 python3.10}; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$(command -v "$c")"; return 0
    fi
  done
  return 1
}

# Saknas Python: FRÅGA om den ska installeras (bara då — finns Python frågas det aldrig).
# Svar utan terminal: LEDGEBORD_SVAR=j (installera) eller n.
erbjud_python() {
  local OS cmd="" pre="" svar="" mgr=""
  OS="$(uname -s)"
  [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && pre="sudo "
  if [ "$OS" = "Darwin" ]; then
    command -v brew >/dev/null 2>&1 && { cmd="brew install python"; mgr="Homebrew"; pre=""; }
  elif command -v apt-get >/dev/null 2>&1; then cmd="${pre}apt-get install -y python3 python3-venv python3-pip"; mgr="apt"
  elif command -v dnf >/dev/null 2>&1; then cmd="${pre}dnf install -y python3 python3-pip"; mgr="dnf"
  elif command -v pacman >/dev/null 2>&1; then cmd="${pre}pacman -S --noconfirm python python-pip"; mgr="pacman"
  elif command -v zypper >/dev/null 2>&1; then cmd="${pre}zypper install -y python3 python3-pip"; mgr="zypper"
  elif command -v apk >/dev/null 2>&1; then cmd="${pre}apk add python3 py3-pip"; mgr="apk"
  fi
  echo "Python 3.10 eller nyare hittades inte på den här datorn."
  if [ -z "$cmd" ]; then
    echo "  Installera Python själv: https://www.python.org/downloads/  och kör sedan ./starta.sh igen."
    return 1
  fi
  echo "  Ledgebord kan installera den åt dig med $mgr:  $cmd"
  echo "  (Har datorn redan Python frågar skriptet aldrig om detta.)"
  svar="${LEDGEBORD_SVAR:-}"
  if [ -z "$svar" ]; then
    if [ -t 0 ]; then read -r -p "  Installera Python nu? [j/N] " svar; else svar="n"; fi
  fi
  case "$svar" in
    j|J|ja|Ja|JA|y|Y|yes) ;;
    *) echo "  Okej — ingen Python installeras. Installera den själv och kör ./starta.sh igen."; return 1 ;;
  esac
  echo "Installerar Python …"
  if ! eval "$cmd"; then echo "Installationen misslyckades. Installera Python själv: https://www.python.org/downloads/"; return 1; fi
  hitta_python
}

if ! hitta_python; then
  erbjud_python || exit 1
  [ -n "$PY" ] || { echo "Python hittades fortfarande inte efter installationen. Öppna en ny terminal och kör ./starta.sh igen."; exit 1; }
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
