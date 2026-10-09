"""Action execution: run one action's `steps` + `after_success` as a queue.

The backend runs server-side entries inline and pauses at a frontend (`app_*`)
entry, handing it to the UI by execution uid; the client runs it and calls back
to resume. The backend owns the whole run, including its `{PIPE_PATH}` file.
Also holds the server-side built-in action registry.
"""

import subprocess
import sys

from ybe import config, envs, state
from ybe.dataset import scan_images
from ybe.extensions import load_actions
from ybe.filters import _clear_filter, apply_filters
from ybe.packages import extension_app_action_ids
from ybe.pipes import _subprocess_env, build_command, remove_pipe
from ybe.userconfig import _disabled_extensions


def _run_command(run, command):
    """Run one shell command, accumulating output in `run`.

    Returns "ok", "failed", "timeout" or "error"; `run["exit_code"]` holds the
    failing command's code on "failed". Runs with cwd=config.YBX_HOME (logged), so
    relative paths land in the user folder (`scripts/…` is yours); reach shipped
    helpers with {APP_DIR}/scripts/… explicitly.
    """
    print(f"[ybe] command: cwd={config.YBX_HOME} cmd={command}", file=sys.stderr)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=config.ACTION_TIMEOUT,
            cwd=config.YBX_HOME,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        run["stderr"].append(f"$ {command}\ntimed out")
        return "timeout"
    except OSError as exc:
        run["stderr"].append(f"$ {command}\n{exc}")
        return "error"
    run["commands"].append(command)
    if proc.stdout.strip():
        run["stdout"].append(f"$ {command}\n{proc.stdout.rstrip()}")
    if proc.stderr.strip():
        run["stderr"].append(f"$ {command}\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        run["exit_code"] = proc.returncode
        return "failed"
    return "ok"


def _resolve_entry(entry, actions_by_name, package=None):
    """Resolve one `steps` / `after_success` entry into a work-queue item.

    Both lists share one syntax:
      - an `app_*` app action          -> ("app", name)     run in the UI
      - a `backend_*` built-in action  -> ("backend", name) run inline
      - `action_<Name>` known action   -> ("action", dict)  run inline
      - anything else                  -> ("cmd", entry)    shell command
    An unknown `app_*`, `backend_*` or `action_*` name becomes a
    ("bad", message) item. The owning `package` id rides along so a command can
    resolve its `{EXT_*}` placeholders from that package's environment.
    """
    if entry in config.APP_ACTIONS:
        return ("app", entry, package)
    if entry.startswith(config.EXTENSION_ACTION_PREFIX):
        if entry in extension_app_action_ids():
            return ("app", entry, package)
        return ("bad", f"unknown extension app action: {entry}", package)
    if entry.startswith("app_"):
        return ("bad", f"unknown app action: {entry}", package)
    if entry in config.BACKEND_ACTION_NAMES:
        return ("backend", entry, package)
    if entry.startswith("backend_"):
        return ("bad", f"unknown backend action: {entry}", package)
    if entry.startswith(config.ACTION_REF_PREFIX):
        name = entry[len(config.ACTION_REF_PREFIX):]
        if name in actions_by_name:
            return ("action", actions_by_name[name], package)
        return ("bad", f"unknown action: {name}", package)
    return ("cmd", entry, package)


def _action_items(action):
    """Expand an action into its ordered work-queue items (steps, then after_success).

    An `action_<Name>` reference to an action disabled for this dataset does not
    resolve, matching the toolbar (there is no way to run a disabled action).
    """
    disabled = _disabled_extensions()["action"]
    actions_by_name = {
        a["name"]: a for a in load_actions() if a["name"] not in disabled
    }
    package = action.get("package")
    entries = list(action.get("steps") or []) + list(action.get("after_success") or [])
    return [_resolve_entry(entry, actions_by_name, package) for entry in entries]


def _advance_execution(run):
    """Process the queue until a frontend action is reached or the run ends.

    Returns (status, detail):
        ("client", name)  the named app action must run in the UI next
        ("done", None)    the whole chain finished successfully
        ("failed", None)  a command failed (see run["exit_code"])
        ("timeout", None) a command timed out
        ("error", msg)    an unknown action / bad after_success / cascade limit
    """
    while run["queue"]:
        kind, value, package = run["queue"].pop(0)
        if kind == "app":  # frontend action: pause for the client
            return "client", value
        if kind == "bad":
            # An unknown `app_*`/`backend_*`/`action_*` reference.
            return "error", value
        if kind == "action":
            # A referenced action runs inline: expand it and splice its items
            # into the front of the queue. `runs` caps runaway action chains.
            run["runs"] += 1
            if run["runs"] > config.MAX_CASCADE_DEPTH:
                return "error", f"action cascade exceeded {config.MAX_CASCADE_DEPTH} levels"
            run["queue"][0:0] = _action_items(value)
            continue
        if kind == "backend":
            # A server-side built-in runs immediately; a non-None result is an
            # error message that aborts the run.
            error = BACKEND_ACTIONS[value]()
            if error:
                return "error", error
            continue
        # Anything else is a shell command. Its {EXT_*} placeholders resolve
        # from the package that owns the step (empty/`{PYTHON}` for loose files).
        values = run["values"]
        ext = envs.placeholder_values(package)
        if ext:
            values = {**values, **ext}
        status = _run_command(run, build_command(value, values))
        if status != "ok":
            return status, None
    return "done", None


def begin_execution(action, action_name, values, pipe_path):
    """Start a run: queue the action's steps + after_success, then advance it.

    Returns (run, status, detail) as `_advance_execution` does.
    """
    run = {
        "action": action_name,
        "values": values,
        "pipe_path": pipe_path,
        "cwd": config.YBX_HOME,
        "queue": _action_items(action),
        "stdout": [],
        "stderr": [],
        "commands": [],
        "exit_code": 0,
        "runs": 1,
    }
    status, detail = _advance_execution(run)
    return run, status, detail


def finish_execution(run):
    """Delete the run's pipe file (unless --keep-pipe) and forget the run."""
    uid = run.get("uid")
    if uid:
        state.EXECUTIONS.pop(uid, None)
    if not state.STATE["keep_pipe"]:
        remove_pipe(run.get("pipe_path"))


def _rescan_images():
    """Re-scan the image folders and re-apply the active filter in place.

    Used by `POST /api/images/rescan` (an explicit refresh) and by the
    `backend_rescan_images` action entry. The flat list is rebuilt and a filter
    that depends on the files (e.g. tags) is re-run; an active split that no
    longer has any image is cleared.
    """
    state.STATE["images"] = scan_images()
    if state.STATE["active_split"] and not any(
        e["split"] == state.STATE["active_split"] for e in state.STATE["images"]
    ):
        state.STATE["active_split"] = None
    # the flat list changed: an active filter chain must be re-evaluated
    if state.STATE["active_filters"]:
        error = apply_filters(state.STATE["active_filters"])
        if error:
            _clear_filter()
            state.STATE["filter_error"] = error


# Server-side built-in action callables (see config.BACKEND_ACTION_NAMES). Each
# returns None on success or an error message that stops the run.
BACKEND_ACTIONS = {
    "backend_rescan_images": _rescan_images,
}
