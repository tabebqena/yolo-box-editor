#!/usr/bin/env bash
#
# ybx.sh - thin bootstrap for the Python installer (ybx.py).
#
# All install / update / uninstall logic lives in ybx.py; this shim only finds a
# Python 3 interpreter and hands the arguments over. When it runs from a
# checkout it executes the sibling ybx.py; fetched on its own (the one-line
# installer) it downloads ybx.py with Python's urllib (no curl) and runs it.
#
# One-liner (no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | bash -s -- install
#
set -euo pipefail

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  printf 'ybx: Python 3 is required (install it and retry).\n' >&2
  exit 1
fi

self_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$self_dir/ybx.py" ]; then
  exec "$PY" "$self_dir/ybx.py" "$@"
fi

exec "$PY" - "$@" <<'PYEOF'
import os
import runpy
import sys
import tempfile
import urllib.request

URL = "https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.py"
try:
    request = urllib.request.Request(URL, headers={"User-Agent": "yolo-box-editor-installer"})
    data = urllib.request.urlopen(request, timeout=30).read()
except Exception as exc:  # noqa: BLE001 - report and stop
    sys.stderr.write("ybx: could not download ybx.py: %s\n" % exc)
    raise SystemExit(1)

fd, path = tempfile.mkstemp(prefix="ybx-", suffix=".py")
try:
    os.write(fd, data)
finally:
    os.close(fd)
sys.argv = ["ybx.py"] + sys.argv[1:]
try:
    runpy.run_path(path, run_name="__main__")
finally:
    os.unlink(path)
PYEOF
