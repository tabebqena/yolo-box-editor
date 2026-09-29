#!/usr/bin/env bash
#
# install.sh - install yolo-box-editor on Linux.
#
# Creates a local virtual environment (.venv), installs the Python
# requirements, and optionally adds a "yolo-box-editor" command to your PATH.
#
# Usage:
#   bash install.sh              # install into ./.venv
#   bash install.sh --link       # also create ~/.local/bin/yolo-box-editor
#   bash install.sh --python python3.11
#   bash install.sh --venv /path/to/venv
#
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
PYTHON_CMD="${PYTHON_CMD:-python3}"
LINK=0
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

usage() {
  sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --link) LINK=1 ;;
    --python) PYTHON_CMD="${2:?--python needs a value}"; shift ;;
    --venv) VENV_DIR="${2:?--venv needs a value}"; shift ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "$(uname -s)" != "Linux" ]; then
  warn "This installer targets Linux (detected: $(uname -s)); continuing anyway."
fi

command -v "$PYTHON_CMD" >/dev/null 2>&1 \
  || die "$PYTHON_CMD not found. Install Python 3.8+ (e.g. 'sudo apt install python3 python3-venv')."

if ! "$PYTHON_CMD" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
  die "$PYTHON_CMD is $("$PYTHON_CMD" --version 2>&1); Python 3.8 or newer is required."
fi

say "Using $("$PYTHON_CMD" --version 2>&1) at $(command -v "$PYTHON_CMD")"

if [ -d "$VENV_DIR" ]; then
  say "Reusing existing virtual environment: $VENV_DIR"
else
  say "Creating virtual environment: $VENV_DIR"
  if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
    die "Could not create the venv. On Debian/Ubuntu run: sudo apt install python3-venv"
  fi
fi

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || die "Virtual environment looks broken (no $VENV_PY); delete $VENV_DIR and retry."

say "Installing dependencies from requirements.txt"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r "$APP_DIR/requirements.txt"

chmod +x "$APP_DIR/app.py" 2>/dev/null || true

if [ "$LINK" -eq 1 ]; then
  mkdir -p "$BIN_DIR"
  LAUNCHER="$BIN_DIR/yolo-box-editor"
  say "Creating launcher: $LAUNCHER"
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV_PY" "$APP_DIR/app.py" "\$@"
EOF
  chmod +x "$LAUNCHER"
fi

printf '\n'
say "Done."
echo "Start the app with:"
if [ "$LINK" -eq 1 ]; then
  echo "    yolo-box-editor --data /path/to/data.yaml"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH; add it or use the full path." ;;
  esac
else
  echo "    \"$VENV_PY\" \"$APP_DIR/app.py\" --data /path/to/data.yaml"
  echo "    (re-run 'bash install.sh --link' to add a 'yolo-box-editor' command)"
fi
echo "Then open http://127.0.0.1:5000"
