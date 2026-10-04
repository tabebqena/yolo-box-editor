"""Shared command/pipe helpers for action and filter runs.

Commands run with `cwd=YBX_HOME` and receive the resolved user paths through
the environment; each run may own a scratch `{PIPE_PATH}` file. These helpers
only depend on `config`, so both the action and filter engines can reuse them.
"""

import os
import shlex
import tempfile

from ybe import config


def build_command(template, values):
    """Replace only the placeholders present in `template` with shell-quoted paths."""
    cmd = template
    for key, val in values.items():
        cmd = cmd.replace("{" + key + "}", shlex.quote(val))
    return cmd


def create_pipe():
    """Create an empty per-run pipe file; return its path (None when it fails).

    The file backs the `{PIPE_PATH}` placeholder: every step of a run (and the
    actions in its `after_success` chain) can read/write it to pass data on.
    """
    try:
        os.makedirs(config.PIPE_DIR, exist_ok=True)
        # mkstemp opens the file for us; we only need the path, so close the fd.
        fd, path = tempfile.mkstemp(prefix="pipe_", suffix=".txt", dir=config.PIPE_DIR)
    except OSError:
        return None
    os.close(fd)
    return path


def is_pipe_path(path):
    """True when `path` is a pipe file the app may delete.

    Only paths inside config.PIPE_DIR qualify, so a stray path can never make the app
    remove an unrelated file.
    """
    if not path:
        return False
    base = os.path.abspath(config.PIPE_DIR)
    target = os.path.abspath(path)
    try:
        # commonpath resolves `..`/symlink-free components, so a path that only
        # appears to start with PIPE_DIR cannot slip through.
        return os.path.commonpath([base, target]) == base
    except ValueError:
        return False  # e.g. different drives on Windows


def remove_pipe(path):
    """Delete a pipe file; ignore a missing/mismatched one."""
    if not is_pipe_path(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _subprocess_env():
    """Environment handed to every command/filter: the resolved user paths."""
    env = os.environ.copy()
    env["YBE_HOME"] = config.YBX_HOME
    env["YBE_APP_DIR"] = config.BASE_DIR
    env["YBE_APP_SCRIPT_DIR"] = config.APP_SCRIPT_DIR
    env["YBE_USER_SCRIPT_DIR"] = config.USER_SCRIPT_DIR
    return env
