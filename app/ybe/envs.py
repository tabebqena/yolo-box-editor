"""Per-extension Python environments.

A package may need Python packages the app does not ship (for example a model
runtime). Its manifest declares how to satisfy that:

    python: venv               # dedicated venv (default when requirements exist)
    python: current            # install into the app's own interpreter
    python: /path/to/python    # use that interpreter as-is
    requirements:              # inline pip specs
      - ultralytics>=8.0
    requirements_file: requirements.txt   # or a file inside the package

`{EXT_PYTHON}` resolves to the interpreter a package's steps should use,
`{EXT_ENV_DIR}` to its venv folder (empty for the other modes) and `{EXT_DIR}`
to the package folder. Building an env is explicit (at install time or through
`ybe extension-env`); nothing here runs on its own. The venvs live in
`config.EXTENSION_ENVS_DIR` (inside the user folder), so they survive updates.
"""

import os
import subprocess
import sys

from ybe import config
from ybe.packages import load_packages

MODE_VENV = "venv"
MODE_CURRENT = "current"
MODE_PATH = "path"


def venv_python(env_dir):
    """The interpreter inside a venv folder (POSIX or Windows layout).

    The POSIX path is returned when neither exists, so callers can test with
    `os.path.isfile`.
    """
    posix = os.path.join(env_dir, "bin", "python")
    windows = os.path.join(env_dir, "Scripts", "python.exe")
    if os.path.isfile(windows) and not os.path.isfile(posix):
        return windows
    return posix


def env_dir(package_id):
    """The folder a package's dedicated venv lives in."""
    return os.path.join(config.EXTENSION_ENVS_DIR, package_id)


def parse_mode(value):
    """Classify a manifest `python:` value into `(mode, interpreter)`.

    Empty / `auto` / `venv` -> a dedicated venv; `current` -> the app's
    interpreter; anything else -> that path used as-is.
    """
    value = (value or "").strip()
    if not value or value.lower() in ("venv", "auto"):
        return MODE_VENV, None
    if value.lower() == "current":
        return MODE_CURRENT, None
    return MODE_PATH, os.path.abspath(os.path.expanduser(value))


def requirements_for(pkg):
    """The pip specs a package declares (inline list + `requirements_file`)."""
    reqs = [str(r).strip() for r in (pkg.get("requirements") or []) if str(r).strip()]
    rel = (pkg.get("requirements_file") or "").strip()
    if rel:
        try:
            with open(os.path.join(pkg["path"], rel), encoding="utf-8") as handle:
                for line in handle:
                    line = line.split("#", 1)[0].strip()
                    if line:
                        reqs.append(line)
        except OSError:
            pass
    seen, out = set(), []
    for req in reqs:
        if req not in seen:
            seen.add(req)
            out.append(req)
    return out


def resolve(pkg):
    """How a package's steps should run.

    Returns `{mode, python, env_dir, requirements, declared, ready, status}`.
    `status` is `"none"` (nothing declared), `"missing"` (declared but not built)
    or `"ready"`.
    """
    mode, explicit = parse_mode(pkg.get("python"))
    reqs = requirements_for(pkg)
    declared = bool(pkg.get("python")) or bool(reqs)
    venv = env_dir(pkg["id"])
    if mode == MODE_PATH and explicit:
        interpreter = explicit
        env = ""
        ready = os.path.isfile(interpreter)
    elif mode == MODE_CURRENT:
        interpreter = sys.executable
        env = ""
        ready = True
    else:  # venv
        interpreter = venv_python(venv)
        env = venv
        ready = os.path.isfile(interpreter)
        if not ready:
            interpreter = ""
    if not declared:
        status = "none"
    else:
        status = "ready" if ready else "missing"
    return {
        "mode": mode,
        "python": interpreter or "",
        "env_dir": env,
        "requirements": reqs,
        "declared": declared,
        "ready": ready,
        "status": status,
    }


def find(package_id):
    """The loaded package dict for `package_id`, or None."""
    return next((p for p in load_packages()[0] if p["id"] == package_id), None)


def resolve_id(package_id):
    """`resolve` for a package id, or None when the package is unknown."""
    pkg = find(package_id)
    if pkg is None:
        return None
    return resolve(pkg)


def placeholder_values(package_id):
    """The `{EXT_*}` substitution values for a step owned by `package_id`."""
    values = {"EXT_DIR": "", "EXT_PYTHON": sys.executable, "EXT_ENV_DIR": ""}
    if not package_id:
        return values
    pkg = find(package_id)
    if pkg is None:
        return values
    values["EXT_DIR"] = pkg.get("path") or ""
    info = resolve(pkg)
    values["EXT_PYTHON"] = info["python"] or sys.executable
    values["EXT_ENV_DIR"] = info["env_dir"] or ""
    return values


def setup(pkg, base_python=None, log=None):
    """Build a package's environment; returns `{ok, mode, log, error, info}`.

    A dedicated venv is created (reusing an existing one) and the requirements
    are pip-installed into it; `current`/path install into that interpreter.
    Nothing is built when the package declares no requirements/interpreter.
    """
    lines = []

    def emit(message):
        lines.append(message)
        if log:
            log(message)

    info = resolve(pkg)
    reqs = info["requirements"]
    mode = info["mode"]
    if not info["declared"]:
        return {"ok": True, "mode": mode, "log": "no environment needed",
                "error": None, "info": info}

    if mode == MODE_VENV:
        target = info["env_dir"]
        if not os.path.isfile(venv_python(target)):
            base = base_python or sys.executable
            emit("Creating virtual environment: %s" % target)
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                subprocess.run([base, "-m", "venv", target], check=True,
                               capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                return {"ok": False, "mode": mode, "log": "\n".join(lines),
                        "error": "could not create venv: %s" % detail, "info": info}
        interpreter = venv_python(target)
    else:
        interpreter = info["python"]
        if not interpreter or not os.path.isfile(interpreter):
            return {"ok": False, "mode": mode, "log": "\n".join(lines),
                    "error": "interpreter not found: %s" % (interpreter or "?"),
                    "info": info}

    if reqs:
        emit("Installing %d requirement(s) into %s" % (len(reqs), interpreter))
        try:
            subprocess.run([interpreter, "-m", "pip", "install", "--upgrade", "pip"],
                           check=True, capture_output=True, text=True)
            subprocess.run([interpreter, "-m", "pip", "install", *reqs],
                           check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            return {"ok": False, "mode": mode, "log": "\n".join(lines),
                    "error": "pip install failed: %s" % detail, "info": info}
    emit("Environment ready.")
    return {"ok": True, "mode": mode, "log": "\n".join(lines),
            "error": None, "info": resolve(pkg)}
