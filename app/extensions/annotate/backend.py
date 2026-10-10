"""Annotate extension backend (example).

Serves the model's boxes from a **separate** output folder, remembers that
folder per dataset (keyed by the dataset path, stored in the user home so the
dataset is never touched), and runs the model **asynchronously** so the panel
can poll progress instead of waiting on one long request.

The panel reads boxes through the `annotate.*` capabilities; the same data is
available over HTTP at `/api/extension/annotate/labels` and
`/api/extension/annotate/dir`.

Unlike the dataset's own labels, these files are never read or written by the
core app — only this extension knows about them.
"""

import json
import os
import subprocess
import sys

from ybe import config, envs, state
from ybe.dataset import _split_by_name
from ybe.pipes import _subprocess_env

OVERRIDE_FILE = ".annotate_extension.json"
SETTINGS_FILE = ".annotate_settings.json"
PROGRESS_FILE = ".annotate_progress.json"
LOG_FILE = ".annotate_run.log"
CLASSES_FILE = ".annotate_model_classes.json"

# The single in-flight (or last finished) run. The panel allows one at a time.
_JOB = {"proc": None, "output_dir": None}


# --- small JSON helpers ---------------------------------------------------- #
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass


def _home_path(name):
    return os.path.join(config.YBX_HOME, name)


# --- per-dataset output-folder override ----------------------------------- #
def _load_overrides():
    data = _read_json(_home_path(OVERRIDE_FILE))
    return data if isinstance(data, dict) else {}


def get_output_dir(data_yaml=None):
    """The remembered output folder for a dataset, or None."""
    key = os.path.abspath(data_yaml or state.STATE["data_yaml"] or "")
    if not key:
        return None
    return _load_overrides().get(key)


def set_output_dir(folder):
    """Remember (or clear) the output folder for the current dataset."""
    key = os.path.abspath(state.STATE["data_yaml"] or "")
    if not key:
        return None
    data = _load_overrides()
    if folder:
        data[key] = folder
    else:
        data.pop(key, None)
    _write_json(_home_path(OVERRIDE_FILE), data)
    return folder


# --- panel settings (model + confidence + class names), stored globally --- #
def get_settings():
    """The panel's persisted settings plus the current dataset's output folder."""
    data = _read_json(_home_path(SETTINGS_FILE))
    if not isinstance(data, dict):
        data = {}
    return {
        "model": data.get("model") or "",
        "conf": data.get("conf") or "0.25",
        "classes": data.get("classes") or "",
        "output_dir": get_output_dir() or "",
    }


def save_settings(model, conf, classes=None):
    """Persist the panel's model path, confidence and model class names."""
    data = _read_json(_home_path(SETTINGS_FILE))
    if not isinstance(data, dict):
        data = {}
    data["model"] = (model or "").strip()
    data["conf"] = (conf or "0.25").strip() or "0.25"
    data["classes"] = (classes or "").strip()
    _write_json(_home_path(SETTINGS_FILE), data)
    return get_settings()


def auto_classes():
    """The model's own class names, as written by the last run (or [])."""
    data = _read_json(_home_path(CLASSES_FILE))
    if isinstance(data, dict):
        try:
            return [str(data[key]) for key in sorted(data, key=lambda k: int(k))]
        except (TypeError, ValueError):
            return []
    if isinstance(data, list):
        return [str(name) for name in data]
    return []


def class_names():
    """The class names to label overlays with: the panel setting, else the
    names the model reported on its last run, else [] (the editor then falls
    back to the dataset's own classes)."""
    setting = get_settings().get("classes") or ""
    names = [name.strip() for name in setting.split(",") if name.strip()]
    return names or auto_classes()


# --- reads ----------------------------------------------------------------- #
def label_path(entry):
    """The extension label file for an image (`<out>/<split>/<stem>.txt`)."""
    split = _split_by_name(entry["split"])
    base = get_output_dir()
    if split is None or not base:
        return None
    stem = os.path.splitext(entry["name"])[0]
    return os.path.join(base, split["name"], stem + ".txt")


def read_boxes(entry):
    """Parse the extension label file into `[{class,cx,cy,w,h}]` (empty if none)."""
    path = label_path(entry)
    if not path or not os.path.isfile(path):
        return []
    boxes = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    cls = int(float(parts[0]))
                    cx, cy, w, h = (float(v) for v in parts[1:5])
                except ValueError:
                    continue
                boxes.append({"class": cls, "cx": cx, "cy": cy, "w": w, "h": h})
    except OSError:
        return []
    return boxes


def _entry_for_key(key):
    if not key or "/" not in key:
        return None
    split, name = key.split("/", 1)
    for entry in state.STATE["images"]:
        if entry["split"] == split and entry["name"] == name:
            return entry
    return None


def _require_writable():
    if state.STATE["readonly"]:
        raise PermissionError("read-only mode")


# --- the async run --------------------------------------------------------- #
def _job_running():
    """True while the model script is still running."""
    proc = _JOB.get("proc")
    return proc is not None and proc.poll() is None


def _tail_log(lines=20):
    """The last lines of the run log, for a failed run's message."""
    try:
        with open(_home_path(LOG_FILE), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:]).strip()


def _start(opts):
    """Start the model script as a background process; return the initial status."""
    _require_writable()
    opts = opts if isinstance(opts, dict) else {}
    data_yaml = state.STATE["data_yaml"]
    if not data_yaml:
        raise ValueError("load a dataset first")
    if _job_running():
        return {"ok": False, "running": True,
                "error": "an annotate run is already in progress"}

    model = (opts.get("model") or "").strip()
    out = (opts.get("output_dir") or "").strip()
    conf = (opts.get("conf") or "0.25").strip() or "0.25"
    classes = (opts.get("classes") or "").strip()
    if not model:
        raise ValueError("set the model path first")
    model_path = os.path.abspath(os.path.expanduser(model))
    if not os.path.isfile(model_path):
        raise ValueError("model file not found: %s" % model_path)
    if not out:
        raise ValueError("set an output folder first")
    out_path = os.path.abspath(os.path.expanduser(out))
    os.makedirs(out_path, exist_ok=True)

    pkg = envs.find("annotate") or {}
    ext_dir = pkg.get("path") or os.path.join(config.BASE_DIR, "extensions", "annotate")
    script = os.path.join(ext_dir, "scripts", "annotate_all.py")
    info = envs.resolve_id("annotate") or {}
    python = info.get("python") or sys.executable

    progress_path = _home_path(PROGRESS_FILE)
    _write_json(progress_path, {"done": 0, "total": 0, "phase": "starting"})
    command = [
        python, script,
        "--data", data_yaml,
        "--out", out_path,
        "--model", model_path,
        "--conf", str(conf),
        "--progress", progress_path,
        "--classes", _home_path(CLASSES_FILE),
    ]
    log_path = _home_path(LOG_FILE)
    try:
        handle = open(log_path, "w", encoding="utf-8")
    except OSError as exc:
        raise ValueError("could not open the run log: %s" % exc)
    try:
        proc = subprocess.Popen(
            command, cwd=config.YBX_HOME, env=_subprocess_env(),
            stdout=handle, stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        handle.close()
        raise ValueError("could not start the model: %s" % exc)
    finally:
        handle.close()

    save_settings(model, conf, classes)
    set_output_dir(out_path)
    _JOB["proc"] = proc
    _JOB["output_dir"] = out_path
    return {
        "ok": True, "running": True, "output_dir": out_path,
        "model": model, "conf": conf, "classes": classes,
    }


def _progress():
    """The live run status: running flag, counts, current image and any error."""
    prog = _read_json(_home_path(PROGRESS_FILE))
    if not isinstance(prog, dict):
        prog = {}
    proc = _JOB.get("proc")
    running = proc is not None and proc.poll() is None
    result = {
        "running": running,
        "done": int(prog.get("done") or 0),
        "total": int(prog.get("total") or 0),
        "current": prog.get("current") or None,
        "phase": prog.get("phase") or ("running" if running else "idle"),
        "output_dir": get_output_dir() or "",
    }
    if prog.get("error"):
        result["error"] = prog["error"]
    if proc is not None and not running:
        code = proc.poll()
        result["returncode"] = code
        if code not in (0, None) and "error" not in result:
            result["error"] = _tail_log() or ("model run exited with code %s" % code)
    return result


# --- capabilities (used by the panel and /api/extensions/call) ------------ #
def _cap_get(key):
    entry = _entry_for_key(key)
    if not entry:
        return []
    boxes = read_boxes(entry)
    # Label each box with the model's own class name when we know it (the panel
    # setting, or the names the model reported). With none, leave the label out
    # so the editor falls back to the dataset's classes.
    names = class_names()
    if names:
        for box in boxes:
            index = box["class"]
            if 0 <= index < len(names):
                box["label"] = "%d: %s" % (index, names[index])
    return boxes


def _cap_set_dir(folder):
    _require_writable()
    folder = (folder or "").strip()
    path = os.path.abspath(os.path.expanduser(folder)) if folder else None
    if path and not os.path.isdir(path):
        raise ValueError(f"not a folder: {path}")
    set_output_dir(path)
    return {"output_dir": path}


def _cap_status():
    status = get_settings()
    status["running"] = _job_running()
    # The model's own names are used for labels when the panel setting is empty;
    # report them so the panel can show what will be used.
    status["auto_classes"] = auto_classes()
    return status


def _cap_start(opts):
    return _start(opts)


def _cap_progress():
    return _progress()


# --- HTTP routes (served by the host's runtime dispatcher) ---------------- #
def _get_labels():
    from flask import jsonify, request
    return jsonify({"ok": True, "boxes": _cap_get(request.args.get("key", ""))})


def _post_dir():
    from flask import jsonify, request
    if state.STATE["readonly"]:
        return jsonify({"ok": False, "error": "read-only mode"}), 403
    data = request.get_json(silent=True) or {}
    try:
        result = _cap_set_dir(data.get("output_dir"))
    except (ValueError, PermissionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    result["ok"] = True
    return jsonify(result)


def _get_progress():
    from flask import jsonify
    return jsonify({"ok": True, **_progress()})


# Rules are relative to `/api/extension/<prefix>` (prefix = the manifest
# `prefix:` or the package id, here `annotate`).
extension_routes = (
    {"rule": "", "methods": ["GET"], "handler": _get_labels},
    {"rule": "/dir", "methods": ["POST"], "handler": _post_dir},
    {"rule": "/progress", "methods": ["GET"], "handler": _get_progress},
)


def register(ctx):
    """Return the capability table (routes are declared in `extension_routes`)."""
    return {
        "capabilities": {
            "annotate.get": lambda key: _cap_get(key),
            "annotate.setDir": lambda folder: _cap_set_dir(folder),
            "annotate.status": lambda *a: _cap_status(),
            "annotate.start": lambda opts=None: _cap_start(opts),
            "annotate.progress": lambda *a: _cap_progress(),
        },
    }
