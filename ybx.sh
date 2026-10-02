#!/usr/bin/env bash
#
# ybx.sh - install and update yolo-box-editor.
#
# Subcommands:
#   install        download and install (or reinstall) the app
#   upgrade        install a newer version, keeping your files and venv
#   update         alias of upgrade
#   version        print the installed version
#   check-update   compare the installed version with the latest one
#
# Options:
#   --dir DIR       install/user folder (default: ~/.local/share/yolo-box-editor)
#   --home DIR      alias for --dir
#   --version REF   tag/branch/commit to install (default: latest release, then
#                   the newest tag, then the main branch)
#   --from PATH     install from a local clone/folder or a .tar.gz (offline)
#   --link          add yolo-box-editor and ybe to ~/.local/bin (default)
#   --no-link       do not create the launchers
#   --no-start      do not start the app after installing/upgrading
#   --python CMD    python used to build the venv (default: python3)
#   -h, --help      show this help
#
# One-liner (no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | bash -s -- install
#
set -euo pipefail

OWNER="tabebqena"
REPO="yolo-box-editor"
BASE="https://github.com/$OWNER/$REPO"
API="https://api.github.com/repos/$OWNER/$REPO"
RAW="https://raw.githubusercontent.com/$OWNER/$REPO"

DEFAULT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$REPO"
DIR="$DEFAULT_DIR"
REF_ARG=""
FROM=""
LINK=1
START=1
PYTHON_CMD="${PYTHON_CMD:-python3}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
CMD=""

CLEANUP_PATHS=()
cleanup() {
  local p
  for p in "${CLEANUP_PATHS[@]:-}"; do
    if [ -n "$p" ]; then rm -rf "$p"; fi
  done
  return 0
}
trap cleanup EXIT

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
ybx.sh - install and update yolo-box-editor.

Usage:
  ybx.sh install        [options]   install or reinstall the app
  ybx.sh upgrade        [options]   install a newer version (alias: update)
  ybx.sh version        [--dir DIR] print the installed version
  ybx.sh check-update   [--dir DIR] compare installed vs latest

Options:
  --dir DIR       install/user folder (default: ~/.local/share/yolo-box-editor)
  --home DIR      alias for --dir
  --version REF   tag/branch/commit to install (default: latest release, then
                  the newest tag, then the main branch)
  --from PATH     install from a local clone/folder or a .tar.gz (offline)
  --link          add yolo-box-editor and ybe to ~/.local/bin (default)
  --no-link       do not create the launchers
  --no-start      do not start the app after installing/upgrading
  --python CMD    python used to build the venv (default: python3)
  -h, --help      show this help

After installing/upgrading, the app is started in the background (unless
--no-start) so it is ready at http://127.0.0.1:5000.

The app code goes to <dir>/app and is replaced atomically; your files
(actions/ hooks/ filters/ scripts/ shortcuts.txt) and the venv are never touched.
EOF
}

need_curl() {
  command -v curl >/dev/null 2>&1 || die "curl is required (install it and retry)."
}

while [ $# -gt 0 ]; do
  case "$1" in
    install|upgrade|update|version|check-update) CMD="$1" ;;
    --dir|--home) DIR="${2:?$1 needs a value}"; shift ;;
    --version) REF_ARG="${2:?--version needs a value}"; shift ;;
    --from) FROM="${2:?--from needs a value}"; shift ;;
    --link) LINK=1 ;;
    --no-link) LINK=0 ;;
    --no-start) START=0 ;;
    --python) PYTHON_CMD="${2:?--python needs a value}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$DIR" in
  "~") DIR="$HOME" ;;
  "~/"*) DIR="$HOME/${DIR#\~/}" ;;
esac

# --------------------------------------------------------------------------- #
# version resolution
# --------------------------------------------------------------------------- #
resolved_ref=""
resolved_version=""

resolve_target() {
  if [ -n "$REF_ARG" ]; then
    resolved_ref="$REF_ARG"
    resolved_version="${REF_ARG#v}"
    return 0
  fi
  need_curl
  # Latest release + every tag; the highest version wins (a newer tag must not
  # be hidden by an older release). `resolved_ref` keeps the real tag (incl. a
  # leading `v`) so it can be downloaded; `resolved_version` drops the `v`.
  local release tags names name ver best="" bestver="" tag v
  release=$(curl -fsSL "$API/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1 || true)
  tags=$(curl -fsSL "$API/tags" 2>/dev/null \
    | grep -o '"name":[[:space:]]*"[^"]*"' \
    | sed 's/.*"name":[[:space:]]*"//; s/"$//' || true)
  names=$(printf '%s\n%s\n' "$release" "$tags")
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    ver="${name#v}"
    case "$ver" in [0-9]*) ;; *) continue ;; esac
    if [ -z "$bestver" ] \
      || { [ "$ver" != "$bestver" ] \
           && [ "$(printf '%s\n%s\n' "$bestver" "$ver" | sort -V | tail -n1)" = "$ver" ]; }; then
      best="$name"; bestver="$ver"
    fi
  done <<EOF
$names
EOF
  if [ -n "$best" ]; then
    resolved_ref="$best"; resolved_version="$bestver"; return 0
  fi
  if command -v git >/dev/null 2>&1; then
    tag=$(git ls-remote --tags --refs "$BASE.git" 2>/dev/null \
      | sed 's#.*refs/tags/##' | sort -V | tail -n1 || true)
    if [ -n "$tag" ]; then
      resolved_ref="$tag"; resolved_version="${tag#v}"; return 0
    fi
  fi
  resolved_ref="main"
  v=$(curl -fsSL "$RAW/main/app/VERSION" 2>/dev/null | head -n1 || true)
  resolved_version="${v:-}"
}

# --------------------------------------------------------------------------- #
# download / extract / swap
# --------------------------------------------------------------------------- #
download_ref() {
  local ref="$1" out="$2" url
  for url in \
    "$BASE/archive/refs/tags/$ref.tar.gz" \
    "$BASE/archive/refs/heads/$ref.tar.gz" \
    "$BASE/archive/$ref.tar.gz"; do
    if curl -fsSL -o "$out" "$url" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

# Echo the app directory inside `root` (the one holding app.py + VERSION).
find_app_dir() {
  local root="$1" hit
  if [ -f "$root/app.py" ] && [ -f "$root/VERSION" ]; then
    printf '%s\n' "$root"; return 0
  fi
  hit=$(find "$root" -maxdepth 4 -type f -path '*/app/app.py' -print -quit 2>/dev/null || true)
  [ -n "$hit" ] && printf '%s\n' "$(dirname "$hit")"
}

# Atomically replace <dir>/app with `src` (a directory). User files/venv are safe.
place_app() {
  local src="$1" dest="$2"
  local staging="$dest/.app.staging.$$" old="$dest/.app.old.$$"
  [ -f "$src/app.py" ] || die "staged app is missing app.py"
  [ -f "$src/VERSION" ] || die "staged app is missing VERSION"
  CLEANUP_PATHS+=("$staging")
  rm -rf "$staging" "$old"
  cp -a "$src" "$staging"
  if [ -e "$dest/app" ]; then
    mv "$dest/app" "$old"
  fi
  if ! mv "$staging" "$dest/app"; then
    [ -e "$old" ] && mv "$old" "$dest/app"
    die "could not install app/ (rolled back)"
  fi
  rm -rf "$old"
}

# Echo the app dir from a local folder or .tar.gz given with --from.
prepare_from_source() {
  local tmp="$1" app_src
  if [ -d "$FROM" ]; then
    app_src=$(find_app_dir "$FROM")
    [ -n "$app_src" ] || die "no app/app.py found under $FROM"
    printf '%s\n' "$app_src"
    return 0
  fi
  [ -f "$FROM" ] || die "--from path not found: $FROM"
  tar -tzf "$FROM" >/dev/null 2>&1 || die "not a valid .tar.gz: $FROM"
  tar -xzf "$FROM" -C "$tmp"
  app_src=$(find_app_dir "$tmp")
  [ -n "$app_src" ] || die "$FROM does not contain app/app.py"
  printf '%s\n' "$app_src"
}

# Download the resolved ref and echo the app dir inside it.
prepare_remote_source() {
  local tmp="$1" tarball app_src
  need_curl
  tarball="$tmp/src.tar.gz"
  download_ref "$resolved_ref" "$tarball" \
    || die "could not download '${resolved_ref}' (check the name / your network)"
  tar -tzf "$tarball" >/dev/null 2>&1 || die "downloaded file is not a valid .tar.gz"
  tar -xzf "$tarball" -C "$tmp"
  app_src=$(find_app_dir "$tmp")
  [ -n "$app_src" ] || die "the archive does not contain app/app.py"
  printf '%s\n' "$app_src"
}

setup_venv() {
  local venv="$DIR/.venv"
  command -v "$PYTHON_CMD" >/dev/null 2>&1 \
    || die "$PYTHON_CMD not found. Install Python 3.8+ (e.g. 'sudo apt install python3 python3-venv')."
  if [ ! -x "$venv/bin/python" ]; then
    say "Creating virtual environment: $venv"
    "$PYTHON_CMD" -m venv "$venv" \
      || die "could not create the venv (on Debian/Ubuntu: sudo apt install python3-venv)"
  else
    say "Reusing virtual environment: $venv"
  fi
  "$venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$venv/bin/python" -m pip install -r "$DIR/app/requirements.txt"
}

same_file() {
  [ "$1" = "$2" ] && return 0
  local a b
  a=$(cd "$(dirname -- "$1")" 2>/dev/null && pwd)/$(basename -- "$1")
  b=$(cd "$(dirname -- "$2")" 2>/dev/null && pwd)/$(basename -- "$2")
  [ "$a" = "$b" ]
}

install_self() {
  local ref="$1" target="$DIR/ybx.sh"
  if [ -f "$0" ] && [ "$(basename -- "$0")" = "ybx.sh" ]; then
    same_file "$0" "$target" || cp "$0" "$target"
  elif [ -n "$FROM" ] && [ -f "$FROM/ybx.sh" ]; then
    cp "$FROM/ybx.sh" "$target"
  else
    need_curl
    curl -fsSL "$RAW/${ref:-main}/ybx.sh" -o "$target" 2>/dev/null \
      || warn "could not save a local copy of ybx.sh"
  fi
  chmod +x "$target" 2>/dev/null || true
}

make_launcher() {
  [ "$LINK" -eq 1 ] || return 0
  local launcher="$BIN_DIR/yolo-box-editor" venv="$DIR/.venv"
  local template="$DIR/app/launcher.sh.in" line
  mkdir -p "$BIN_DIR"
  if [ -f "$template" ]; then
    # Bake the install dir + venv into the shipped launcher template.
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line//@DIR@/$DIR}"
      line="${line//@VENV@/$venv}"
      printf '%s\n' "$line"
    done < "$template" > "$launcher"
  else
    cat > "$launcher" <<EOF
#!/usr/bin/env bash
exec "$venv/bin/python" "$DIR/app/app.py" --home "$DIR" "\$@"
EOF
  fi
  chmod +x "$launcher"
  ln -sf yolo-box-editor "$BIN_DIR/ybe"
  say "Launchers: $launcher (and ybe)"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH; add it or use the full path." ;;
  esac
}

do_install() {
  local app_src tmp
  tmp=$(mktemp -d); CLEANUP_PATHS+=("$tmp")
  if [ -n "$FROM" ]; then
    app_src=$(prepare_from_source "$tmp")
  else
    resolve_target
    [ -n "$resolved_ref" ] || die "could not determine a version to install"
    app_src=$(prepare_remote_source "$tmp")
  fi
  [ -n "$app_src" ] || die "could not prepare the app files"
  [ -n "$resolved_version" ] || resolved_version=$(cat "$app_src/VERSION" 2>/dev/null || echo unknown)

  say "Installing yolo-box-editor ${resolved_version} into $DIR"
  mkdir -p "$DIR"
  place_app "$app_src" "$DIR"

  mkdir -p "$DIR/actions" "$DIR/hooks" "$DIR/filters" "$DIR/scripts"
  setup_venv
  install_self "$resolved_ref"
  make_launcher

  printf '\n'
  say "Done: yolo-box-editor $(cat "$DIR/app/VERSION")"
  echo "User folder: $DIR"
  maybe_start
}

print_run_hint() {
  if [ "$LINK" -eq 1 ]; then
    echo "Run:         yolo-box-editor start --data /path/to/data.yaml   (or: ybe start …)"
  else
    echo "Run:         \"$DIR/.venv/bin/python\" \"$DIR/app/app.py\" --data /path/to/data.yaml"
  fi
}

# Start the app after installing/upgrading (unless --no-start), so it is ready
# to use. Uses the launcher when available; restarts it if it was already up.
maybe_start() {
  [ "$START" -eq 1 ] || { print_run_hint; return 0; }
  local launcher="$BIN_DIR/yolo-box-editor"
  if [ "$LINK" -ne 1 ] || [ ! -x "$launcher" ]; then
    warn "no launcher (--no-link); start it manually:"
    print_run_hint
    return 0
  fi
  say "Starting yolo-box-editor…"
  local pid="" out=""
  if [ -f "$DIR/ybe.pid" ]; then
    pid=$(cat "$DIR/ybe.pid" 2>/dev/null || true)
  fi
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    out=$("$launcher" restart 2>&1) || {
      printf '%s\n' "$out" >&2
      warn "could not restart; run 'ybe start' manually."
      return 0
    }
  else
    out=$("$launcher" start 2>&1) || {
      printf '%s\n' "$out" >&2
      warn "could not start; run 'ybe start' manually."
      return 0
    }
  fi
  echo "Open:        http://127.0.0.1:5000"
  echo "Stop:        ybe stop        (logs: ybe logs -f)"
}

cmd_install() {
  do_install
}

cmd_upgrade() {
  [ -f "$DIR/app/VERSION" ] || die "not installed in $DIR; run 'ybx.sh install' first."
  local current
  current=$(cat "$DIR/app/VERSION")
  if [ -z "$FROM" ] && [ -z "$REF_ARG" ]; then
    resolve_target
    if [ -z "$resolved_version" ]; then
      say "Could not determine the latest version; nothing to do."
      return 0
    fi
    if ! is_newer "$resolved_version" "$current"; then
      say "Already at $current (latest: $resolved_version); nothing to do."
      return 0
    fi
  fi
  local target="${resolved_version:-${REF_ARG:-}}"
  if [ -z "$target" ] && [ -n "$FROM" ] && [ -f "$FROM/app/VERSION" ]; then
    target=$(cat "$FROM/app/VERSION")
  fi
  if [ -n "$target" ]; then
    [ -n "$resolved_ref" ] || resolved_ref="$target"
  fi
  say "Upgrading $current -> ${resolved_version:-${REF_ARG:-${target:-local}}}"
  do_install
}

cmd_version() {
  if [ -f "$DIR/app/VERSION" ]; then
    echo "yolo-box-editor $(cat "$DIR/app/VERSION")"
  else
    echo "yolo-box-editor: not installed in $DIR"
    exit 1
  fi
}

is_newer() {
  local a="$1" b="$2" highest
  [ -z "$a" ] && return 1
  [ -z "$b" ] && return 0
  [ "$a" = "$b" ] && return 1
  case "$a" in
    [0-9]*) ;;
    *) return 0 ;;
  esac
  highest=$(printf '%s\n%s\n' "$a" "$b" | sort -V | tail -n1)
  [ "$highest" = "$a" ]
}

cmd_check_update() {
  local current latest rc
  current=$(cat "$DIR/app/VERSION" 2>/dev/null || true)
  resolve_target
  latest="$resolved_version"
  if [ -z "$latest" ]; then
    printf 'exit code: 2\ncurrent_version: %s\nlatest_version: unknown\n' "$current"
    exit 2
  fi
  if is_newer "$latest" "$current"; then rc=0; else rc=1; fi
  printf 'exit code: %s\ncurrent_version: %s\nlatest_version: %s\n' "$rc" "$current" "$latest"
  exit "$rc"
}

case "$CMD" in
  install) cmd_install ;;
  upgrade|update) cmd_upgrade ;;
  version) cmd_version ;;
  check-update) cmd_check_update ;;
  *) usage; exit 0 ;;
esac
