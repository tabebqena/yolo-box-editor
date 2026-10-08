"""Cross-platform `ybe` launcher commands, implemented in Python.

The installed `yolo-box-editor` / `ybe` command is only a thin boot script
(`app/launcher.sh.in`, rendered by the installer) that executes this module with
the virtual environment's Python. All of the process management lives here so a
single implementation serves Linux and macOS today and a Windows `.cmd`/`.ps1`
shim later.

Commands:
    start / stop / restart / status / logs
        manage the background server (pid file + log file in the user folder).
    version / check-update / update / upgrade / uninstall
        delegated to the standalone installer `<home>/ybx.py`, which owns all
        install logic and downloads (via Python's urllib, never curl).
"""

import os
import subprocess
import sys
import time

from ybe import procutil as proc


INSTALL_DOCS_URL = "https://github.com/tabebqena/yolo-box-editor/blob/main/docs/install.md"
INSTALL_ONELINER = (
    "curl -fsSL "
    "https://raw.githubusercontent.com/tabebqena/yolo-box-editor/main/ybx.sh | sh -s -- install"
)


def app_dir():
    """The shipped `app/` folder (this file's grandparent)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_py():
    return os.path.join(app_dir(), "app.py")


def installer_path(home):
    return os.path.join(home, "ybx.py")


def pid_file(home):
    return os.path.join(home, "ybe.pid")


def log_file(home):
    return os.path.join(home, "ybe.log")


def resolve_home(explicit=None):
    """`--home` > $YBX_HOME > the parent of the shipped `app/` folder.

    Matches `ybe.config._resolve_home`, so a clone and an install behave the
    same without extra flags.
    """
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("YBX_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(app_dir())


def say(message):
    print(message)


def die(message):
    sys.stderr.write("yolo-box-editor: %s\n" % message)
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# pid helpers
# --------------------------------------------------------------------------- #
def read_pid(path):
    """The PID stored in `path`, or 0 when missing/invalid."""
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def write_pid(path, pid):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("%d\n" % pid)
    except OSError:
        pass


def pid_is_app(pid, python_app=None):
    """True when `pid` is alive and its command line references our app.py.

    Guards against a stale pid file whose PID was reused by an unrelated
    process after a crash or reboot. The platform specifics live in
    `ybe.procutil`.
    """
    return proc.pid_is_app(pid, python_app or app_py())


# --------------------------------------------------------------------------- #
# start / stop / restart / status / logs
# ---------------------------------------------------------------------------#
def _terminate(pid):
    proc.terminate(pid)


def do_start(home, args):
    foreground = False
    app_args = []
    for arg in args:
        if arg in ("--fg", "--foreground"):
            foreground = True
        elif arg in ("-h", "--help"):
            # Forward to the app so `ybe start -h` prints the app's help.
            foreground = True
            app_args.append(arg)
        else:
            app_args.append(arg)

    python_app = app_py()
    stored = read_pid(pid_file(home))
    if pid_is_app(stored, python_app):
        say("yolo-box-editor is already running (pid %d); 'ybe restart' to restart." % stored)
        return 0

    if not os.path.isfile(python_app):
        die("cannot find %s (reinstall with the installer)" % python_app)

    if foreground:
        os.execv(sys.executable, [sys.executable, python_app, "--home", home] + app_args)
        return 0  # unreachable

    logpath = log_file(home)
    os.makedirs(home, exist_ok=True)
    try:
        with open(logpath, "wb"):
            pass
    except OSError:
        pass

    # Detach so the server keeps running after this command returns (see
    # procutil.spawn: new session on POSIX, DETACHED_PROCESS on Windows).
    child = proc.spawn(
        [sys.executable, python_app, "--home", home, "--no-reload", "--log-file", logpath] + app_args,
        logpath,
    )
    write_pid(pid_file(home), child.pid)

    deadline = time.time() + 2.0
    while time.time() < deadline and not pid_is_app(child.pid, python_app):
        time.sleep(0.1)
    if pid_is_app(child.pid, python_app):
        say("yolo-box-editor started (pid %d)." % child.pid)
        say("Log:  %s" % logpath)
        say("Stop: ybe stop")
        return 0

    try:
        os.remove(pid_file(home))
    except OSError:
        pass
    die("failed to start; see %s" % logpath)


def do_stop(home, quiet=False):
    pidfile = pid_file(home)
    pid = read_pid(pidfile)
    if not pid_is_app(pid, app_py()):
        try:
            os.remove(pidfile)
        except OSError:
            pass
        if not quiet:
            say("yolo-box-editor is not running.")
        return 0
    _terminate(pid)
    try:
        os.remove(pidfile)
    except OSError:
        pass
    if not quiet:
        say("yolo-box-editor stopped.")
    return 0


def do_restart(home, args):
    do_stop(home, quiet=True)
    return do_start(home, args)


def do_status(home):
    pid = read_pid(pid_file(home))
    if pid_is_app(pid, app_py()):
        say("yolo-box-editor is running (pid %d)." % pid)
        say("Log: %s" % log_file(home))
        return 0
    say("yolo-box-editor is not running.")
    return 1


def _tail(path, count):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        die("cannot read %s: %s" % (path, exc))
        return
    for line in lines[-count:]:
        sys.stdout.write(line)


def do_logs(home, args):
    logpath = log_file(home)
    if not os.path.isfile(logpath):
        die("no log file yet (%s)" % logpath)
    if not args or args[0] not in ("-f", "--follow"):
        _tail(logpath, 100)
        return 0
    _tail(logpath, 100)
    try:
        with open(logpath, encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                line = handle.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)
    except KeyboardInterrupt:
        return 0


# --------------------------------------------------------------------------- #
# delegated installer commands
# --------------------------------------------------------------------------- #
def missing_installer_error(path):
    """Explain a missing `<home>/ybx.py` and how to recover.

    Installs made before the launcher moved to Python (7.15.0) kept only the old
    shell installer `ybx.sh`; that script copies itself, so it can never leave a
    `ybx.py` behind. A reinstall is the fix (user files and venv are kept).
    """
    die(
        "cannot find %s\n"
        "This install was made with the old shell installer, which only saved "
        "ybx.sh (not the ybx.py that 'ybe update' needs).\n"
        "Reinstall to fix it; your dataset, extensions and venv are kept. For example:\n"
        "  %s\n"
        "Why this is required: %s" % (path, INSTALL_ONELINER, INSTALL_DOCS_URL)
    )


def delegate(home, command, args):
    installer = installer_path(home)
    if not os.path.isfile(installer):
        missing_installer_error(installer)
    result = subprocess.run([sys.executable, installer, command, "--dir", home] + args)
    return result.returncode


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
USAGE = """yolo-box-editor (alias: ybe)

Usage:
  ybe                         show this help
  ybe start [--fg] [OPTIONS]  start in the background (default)
  ybe start --fg [OPTIONS]    run in the foreground (visible here)
  ybe stop                    stop the background process
  ybe restart [OPTIONS]       stop, then start again
  ybe status                  report whether it is running
  ybe logs [-f]               show the last log lines (or follow with -f)
  ybe version                 print the installed version
  ybe check-update            check for a newer version
  ybe update                  update in place, keeping your files and venv
  ybe uninstall               remove the app, venv and launchers

OPTIONS are the app's flags, e.g.:
  --data /path/to/data.yaml   dataset to open
  --readonly                  viewer only (no saving)
  --create-user name          register or reset a login user (prompts), then exit
  --list-users                list registered users, then exit
  --debug                     verbose browser-console logging
  --host 0.0.0.0 --port 5000  bind address
  --no-resume                 skip reopening the last dataset
  --no-update-check           do not check GitHub for updates
"""


def _pop_home(argv):
    """Pull the launcher's own leading `--home`/`--dir` off `argv`.

    Only a leading option is ours: the installer shim always passes
    `--home <dir>` first, while any later `--home` is meant for the app and is
    forwarded untouched.
    """
    if not argv:
        return None, []
    first = argv[0]
    if first in ("--home", "--dir") and len(argv) >= 2:
        return argv[1], argv[2:]
    if first.startswith("--home=") or first.startswith("--dir="):
        return first.split("=", 1)[1], argv[1:]
    return None, argv


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    home_arg, rest = _pop_home(argv)
    home = resolve_home(home_arg)

    if not rest:
        print(USAGE, end="")
        return 0
    command = rest[0]
    args = rest[1:]

    if command in ("start", "daemon"):
        return do_start(home, args)
    if command == "fg":
        return do_start(home, ["--fg"] + args)
    if command == "stop":
        return do_stop(home)
    if command == "restart":
        return do_restart(home, args)
    if command == "status":
        return do_status(home)
    if command == "logs":
        return do_logs(home, args)
    if command in ("version", "check-update", "update", "upgrade", "uninstall"):
        return delegate(home, command, args)
    if command in ("help", "-h", "--help"):
        print(USAGE, end="")
        return 0

    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
