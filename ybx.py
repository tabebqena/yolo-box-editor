#!/usr/bin/env python3
"""Install, update and remove yolo-box-editor.

This is the single self-contained installer/updater. It is deliberately
stdlib-only and runs under any Python 3 before the app's own virtual
environment exists:

* all downloads use `urllib` (never curl),
* archives are unpacked with `tarfile`,
* the app is swapped in atomically with `os.rename`,
* the virtual environment and pip are driven with `subprocess`.

The launcher (`app/ybe/launcher.py`) delegates `version` / `check-update` /
`update` / `upgrade` / `uninstall` here, and a copy of this file is kept at
`<dir>/ybx.py` so `ybe update` works without the original checkout.

Usage:
    ybx.py install  [options]   install or reinstall the app
    ybx.py upgrade  [options]   install a newer version (alias: update)
    ybx.py version  [--dir DIR] print the installed version
    ybx.py check-update [--dir DIR] compare installed vs latest
    ybx.py uninstall [options]  remove the app, venv and launchers
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "tabebqena"
REPO = "yolo-box-editor"
BASE = "https://github.com/%s/%s" % (OWNER, REPO)
API = "https://api.github.com/repos/%s/%s" % (OWNER, REPO)
RAW = "https://raw.githubusercontent.com/%s/%s" % (OWNER, REPO)

DEFAULT_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), REPO
)
PYTHON_CMD = os.environ.get("PYTHON_CMD", "python3")
SUBCOMMANDS = ("install", "upgrade", "update", "version", "check-update", "uninstall")

USER_DIRS = ("actions", "hooks", "filters", "scripts")


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
def say(message):
    print("\033[1;34m==>\033[0m %s" % message)


def warn(message):
    print("\033[1;33mwarning:\033[0m %s" % message, file=sys.stderr)


def die(message):
    print("\033[1;31merror:\033[0m %s" % message, file=sys.stderr)
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
def parse_version(value):
    """`v2.2.0` -> (2, 2, 0); None when there is no leading numeric part."""
    if value is None:
        return None
    match = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate, current):
    """True when `candidate` is a strictly newer version than `current`.

    Mirrors the installer's historical behaviour: an empty candidate is never
    newer, an empty current version means "install anything", a non-numeric
    candidate counts as newer, and a non-numeric current version counts as not
    newer.
    """
    if not candidate:
        return False
    if not current:
        return True
    if candidate == current:
        return False
    a, b = parse_version(candidate), parse_version(current)
    if a is None:
        return True
    if b is None:
        return False
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a > b


def read_version_file(path):
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return ""


def strip_v(value):
    return value[1:] if value[:1] in ("v", "V") else value


# --------------------------------------------------------------------------- #
# network (urllib only)
# --------------------------------------------------------------------------- #
def http_get_text(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "yolo-box-editor-installer"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def http_get_json(url, timeout=30):
    return json.loads(http_get_text(url, timeout))


def download_file(url, destination, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "yolo-box-editor-installer"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(destination, "wb") as out:
        shutil.copyfileobj(response, out)


def download_ref(ref, destination):
    """Download a tag/branch/commit tarball; True on success."""
    for url in (
        "%s/archive/refs/tags/%s.tar.gz" % (BASE, ref),
        "%s/archive/refs/heads/%s.tar.gz" % (BASE, ref),
        "%s/archive/%s.tar.gz" % (BASE, ref),
    ):
        try:
            download_file(url, destination)
            return True
        except (urllib.error.URLError, OSError):
            continue
    return False


def resolve_target(opts):
    """Pick the ref/version to install and store them on `opts`."""
    if opts.commit:
        opts.resolved_ref = opts.commit
        opts.resolved_version = opts.commit[:12]
        return
    if opts.latest:
        opts.resolved_ref = "main"
        try:
            head = http_get_json("%s/commits/main" % API)
            opts.resolved_version = str(head.get("sha") or "")[:12]
        except (urllib.error.URLError, OSError, ValueError, AttributeError):
            opts.resolved_version = ""
        if not opts.resolved_version:
            opts.resolved_version = "main"
        return
    if opts.ref:
        opts.resolved_ref = opts.ref
        opts.resolved_version = strip_v(opts.ref)
        return

    candidates = []
    try:
        data = http_get_json("%s/releases/latest" % API)
        tag = str(data.get("tag_name") or "").strip()
        if tag:
            candidates.append(tag)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass
    try:
        data = http_get_json("%s/tags" % API)
        if isinstance(data, list):
            for entry in data:
                name = str((entry or {}).get("name") or "").strip()
                if name and parse_version(name):
                    candidates.append(name)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass

    parsed = [(parse_version(name), name) for name in candidates if parse_version(name)]
    if parsed:
        best = max(parsed)[1]
        opts.resolved_ref = best
        opts.resolved_version = strip_v(best)
        return

    try:
        text = http_get_text("%s/main/app/VERSION" % RAW).strip()
        if text:
            opts.resolved_ref = "main"
            opts.resolved_version = text.splitlines()[0].strip()
            return
    except (urllib.error.URLError, OSError):
        pass
    opts.resolved_ref = "main"
    opts.resolved_version = candidates[0] if candidates else ""


# --------------------------------------------------------------------------- #
# archives and app placement
# --------------------------------------------------------------------------- #
def extract_tar(path, destination):
    try:
        with tarfile.open(path) as archive:
            try:
                archive.extractall(destination, filter="data")
            except TypeError:  # Python < 3.12 has no `filter`
                archive.extractall(destination)
    except (tarfile.TarError, OSError) as exc:
        die("could not extract %s: %s" % (path, exc))


def find_app_dir(root):
    """The app directory inside `root` (holding app.py + VERSION), or None."""
    for pattern in ("app", "*/app", "*/*/app", "*/*/*/app"):
        for candidate in Path(root).glob(pattern):
            if (candidate / "app.py").is_file() and (candidate / "VERSION").is_file():
                return str(candidate)
    return None


def prepare_remote_source(tmp, opts):
    tarball = os.path.join(tmp, "src.tar.gz")
    if not download_ref(opts.resolved_ref, tarball):
        die("could not download %r (check the name / your network)" % opts.resolved_ref)
    extract_tar(tarball, tmp)
    app_src = find_app_dir(tmp)
    if not app_src:
        die("the archive does not contain app/app.py")
    return app_src


def prepare_from_source(tmp, opts):
    source = opts.from_path
    if os.path.isdir(source):
        app_src = find_app_dir(source)
        if not app_src:
            die("no app/app.py found under %s" % source)
        return app_src
    if not os.path.isfile(source):
        die("--from path not found: %s" % source)
    extract_tar(source, tmp)
    app_src = find_app_dir(tmp)
    if not app_src:
        die("%s does not contain app/app.py" % source)
    return app_src


def place_app(src, dest):
    """Atomically replace `<dest>/app` with `src`; user files/venv untouched."""
    staging = os.path.join(dest, ".app.staging.%d" % os.getpid())
    old = os.path.join(dest, ".app.old.%d" % os.getpid())
    if not (os.path.isfile(os.path.join(src, "app.py")) and os.path.isfile(os.path.join(src, "VERSION"))):
        die("staged app is missing app.py or VERSION")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(src, staging, symlinks=True)
    app_dest = os.path.join(dest, "app")
    if os.path.exists(app_dest):
        os.rename(app_dest, old)
    try:
        os.rename(staging, app_dest)
    except OSError:
        if os.path.exists(old):
            os.rename(old, app_dest)
        die("could not install app/ (rolled back)")
    shutil.rmtree(old, ignore_errors=True)


# --------------------------------------------------------------------------- #
# virtual environment
# --------------------------------------------------------------------------- #
def venv_python(venv):
    for candidate in (
        os.path.join(venv, "bin", "python"),
        os.path.join(venv, "Scripts", "python.exe"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(venv, "bin", "python")


def setup_venv(opts):
    venv = os.path.join(opts.dir, ".venv")
    if shutil.which(opts.python) is None:
        die(
            "%s not found. Install Python 3.8+ (e.g. 'sudo apt install python3 "
            "python3-venv')." % opts.python
        )
    if not os.path.isfile(venv_python(venv)):
        say("Creating virtual environment: %s" % venv)
        try:
            subprocess.run([opts.python, "-m", "venv", venv], check=True)
        except (subprocess.CalledProcessError, OSError):
            die("could not create the venv (on Debian/Ubuntu: sudo apt install python3-venv)")
    else:
        say("Reusing virtual environment: %s" % venv)
    python = venv_python(venv)
    try:
        subprocess.run(
            [python, "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [python, "-m", "pip", "install", "-r", os.path.join(opts.dir, "app", "requirements.txt")],
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        die("pip install failed: %s" % exc)


# --------------------------------------------------------------------------- #
# launcher and self-install
# --------------------------------------------------------------------------- #
def bin_dir():
    return os.path.abspath(os.path.expanduser(os.environ.get("BIN_DIR") or "~/.local/bin"))


def install_self(opts, app_src):
    """Refresh `<dir>/ybx.py` from the source tree being installed.

    Preferring the freshly installed tree (not this running copy) is what makes
    `ybe update` upgrade the installer itself, not just the app.
    """
    target = os.path.join(opts.dir, "ybx.py")
    candidates = [os.path.join(os.path.dirname(app_src), "ybx.py")]
    if opts.from_path and os.path.isdir(opts.from_path):
        candidates.append(os.path.join(opts.from_path, "ybx.py"))
    candidates.append(os.path.abspath(__file__))
    source = next((path for path in candidates if os.path.isfile(path)), None)
    if not source:
        warn("could not find a ybx.py to install")
        return
    try:
        if os.path.exists(target) and os.path.samefile(source, target):
            os.chmod(target, 0o755)
        else:
            shutil.copy2(source, target)
            os.chmod(target, 0o755)
    except OSError as exc:
        warn("could not save a local copy of ybx.py: %s" % exc)


def render_launcher(template_path, opts):
    if os.path.isfile(template_path):
        with open(template_path, encoding="utf-8") as handle:
            text = handle.read()
        return text.replace("@DIR@", opts.dir).replace("@VENV@", os.path.join(opts.dir, ".venv"))
    # Fallback when the template is somehow missing: an equivalent one-liner.
    return (
        "#!/usr/bin/env bash\n"
        'exec "%s/bin/python" "%s/app/launcher.py" --home "%s" "$@"\n'
        % (os.path.join(opts.dir, ".venv"), opts.dir, opts.dir)
    )


def make_launcher(opts):
    target_dir = bin_dir()
    os.makedirs(target_dir, exist_ok=True)
    launcher = os.path.join(target_dir, "yolo-box-editor")
    text = render_launcher(os.path.join(opts.dir, "app", "launcher.sh.in"), opts)
    with open(launcher, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(launcher, 0o755)

    alias = os.path.join(target_dir, "ybe")
    if os.path.isdir(alias) and not os.path.islink(alias):
        warn("%s is a directory; moving it to %s.bak" % (alias, alias))
        try:
            os.rename(alias, alias + ".bak")
        except OSError:
            pass
    else:
        try:
            os.remove(alias)
        except OSError:
            pass
    try:
        os.symlink("yolo-box-editor", alias)
    except OSError:
        # Some filesystems (and Windows without privileges) cannot symlink; a
        # plain copy of the launcher works just as well.
        try:
            shutil.copy2(launcher, alias)
        except OSError:
            warn("could not create the ybe alias at %s" % alias)
    say("Launchers: %s (and ybe)" % launcher)
    if target_dir not in os.environ.get("PATH", "").split(os.pathsep):
        warn("%s is not on your PATH; add it or use the full path." % target_dir)


# --------------------------------------------------------------------------- #
# running process management (mirrors ybe.launcher)
# --------------------------------------------------------------------------- #
def read_pid(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def pid_is_app(pid, app_path):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    cmdline = ""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            cmdline = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        try:
            result = subprocess.run(
                ["ps", "-ww", "-p", str(pid), "-o", "args="], capture_output=True, text=True
            )
            cmdline = result.stdout.strip()
        except OSError:
            cmdline = ""
    return app_path in cmdline


def stop_installed(opts):
    pidfile = os.path.join(opts.dir, "ybe.pid")
    pid = read_pid(pidfile)
    if pid_is_app(pid, os.path.join(opts.dir, "app", "app.py")):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        for _ in range(50):
            if not pid_is_app(pid, os.path.join(opts.dir, "app", "app.py")):
                break
            time.sleep(0.1)
        if pid_is_app(pid, os.path.join(opts.dir, "app", "app.py")):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        say("Stopped the running app (pid %d)." % pid)
    try:
        os.remove(pidfile)
    except OSError:
        pass


def remove_launchers(opts):
    for path in (os.path.join(bin_dir(), "yolo-box-editor"), os.path.join(bin_dir(), "ybe")):
        if not (os.path.exists(path) or os.path.islink(path)):
            continue
        if os.path.islink(path):
            os.remove(path)
            say("Removed launcher %s" % path)
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                owned = opts.dir in handle.read()
        except OSError:
            owned = False
        if owned:
            os.remove(path)
            say("Removed launcher %s" % path)
        else:
            warn("left %s (does not belong to %s)" % (path, opts.dir))


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def do_install(opts):
    tmp = tempfile.mkdtemp(prefix="ybx-")
    try:
        if opts.from_path:
            app_src = prepare_from_source(tmp, opts)
        else:
            resolve_target(opts)
            if not opts.resolved_ref:
                die("could not determine a version to install")
            app_src = prepare_remote_source(tmp, opts)
        version = opts.resolved_version or read_version_file(os.path.join(app_src, "VERSION")) or "unknown"

        say("Installing yolo-box-editor %s into %s" % (version, opts.dir))
        os.makedirs(opts.dir, exist_ok=True)
        place_app(app_src, opts.dir)
        for name in USER_DIRS:
            os.makedirs(os.path.join(opts.dir, name), exist_ok=True)
        setup_venv(opts)
        install_self(opts, app_src)
        make_launcher(opts)

        print("")
        say("Done: yolo-box-editor %s" % read_version_file(os.path.join(opts.dir, "app", "VERSION")))
        print("User folder: %s" % opts.dir)
        maybe_start(opts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_upgrade(opts):
    current_file = os.path.join(opts.dir, "app", "VERSION")
    if not os.path.isfile(current_file):
        die("not installed in %s; run 'ybx.py install' first." % opts.dir)
    current = read_version_file(current_file)
    if not opts.from_path and not opts.ref and not opts.commit and not opts.latest:
        resolve_target(opts)
        if not opts.resolved_version:
            say("Could not determine the latest version; nothing to do.")
            return 0
        if not is_newer(opts.resolved_version, current):
            say("Already at %s (latest: %s); nothing to do." % (current, opts.resolved_version))
            return 0
    elif opts.commit or opts.latest:
        resolve_target(opts)
    target = opts.resolved_version or opts.ref or ""
    if not target and opts.from_path and os.path.isfile(os.path.join(opts.from_path, "app", "VERSION")):
        target = read_version_file(os.path.join(opts.from_path, "app", "VERSION"))
    if target and not opts.resolved_ref:
        opts.resolved_ref = target
    say("Upgrading %s -> %s" % (current, opts.resolved_version or opts.ref or target or "local"))
    do_install(opts)
    return 0


def cmd_version(opts):
    version_file = os.path.join(opts.dir, "app", "VERSION")
    if os.path.isfile(version_file):
        print("yolo-box-editor %s" % read_version_file(version_file))
        return 0
    print("yolo-box-editor: not installed in %s" % opts.dir)
    return 1


def cmd_check_update(opts):
    current = read_version_file(os.path.join(opts.dir, "app", "VERSION"))
    resolve_target(opts)
    latest = opts.resolved_version
    if not latest:
        print("exit code: 2\ncurrent_version: %s\nlatest_version: unknown" % current)
        return 2
    rc = 0 if is_newer(latest, current) else 1
    print("exit code: %d\ncurrent_version: %s\nlatest_version: %s" % (rc, current, latest))
    return rc


def cmd_uninstall(opts):
    if not os.path.isdir(opts.dir):
        say("Nothing installed in %s." % opts.dir)
        return 0
    stop_installed(opts)
    remove_launchers(opts)

    if opts.purge:
        if not opts.yes:
            if sys.stdin.isatty():
                answer = input("Remove %s and ALL its files (actions/, hooks/, filters/, scripts/, ...)? [y/N] " % opts.dir)
                if answer.strip().lower() not in ("y", "yes"):
                    say("Aborted; nothing else was removed.")
                    return 1
            else:
                die("--purge needs --yes when not run interactively.")
        shutil.rmtree(opts.dir, ignore_errors=True)
        say("Removed %s" % opts.dir)
        return 0

    shutil.rmtree(os.path.join(opts.dir, "app"), ignore_errors=True)
    shutil.rmtree(os.path.join(opts.dir, ".venv"), ignore_errors=True)
    for name in ("ybx.py", "ybe.log"):
        try:
            os.remove(os.path.join(opts.dir, name))
        except OSError:
            pass
    say("Removed the app and its virtual environment from %s." % opts.dir)
    say("Kept your files: actions/ hooks/ filters/ scripts/ shortcuts.txt")
    say("Remove everything with: ybx.py uninstall --purge --yes")
    return 0


# --------------------------------------------------------------------------- #
# start after install
# --------------------------------------------------------------------------- #
def maybe_start(opts):
    if not opts.start:
        print_run_hint()
        return
    launcher = os.path.join(bin_dir(), "yolo-box-editor")
    if not os.access(launcher, os.X_OK):
        warn("launcher not found at %s; start it manually:" % launcher)
        print('Run:         "%s" "%s"' % (venv_python(os.path.join(opts.dir, ".venv")), os.path.join(opts.dir, "app", "app.py")))
        return
    pid = read_pid(os.path.join(opts.dir, "ybe.pid"))
    command = "restart" if pid_is_app(pid, os.path.join(opts.dir, "app", "app.py")) else "start"
    say("Starting yolo-box-editor...")
    try:
        result = subprocess.run([launcher, command], capture_output=True, text=True)
    except OSError as exc:
        warn("could not run the launcher: %s" % exc)
        return
    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        warn("could not %s; run 'ybe start' manually." % command)
        return
    print("Open:        http://127.0.0.1:5000")
    print("Stop:        ybe stop        (logs: ybe logs -f)")


def print_run_hint():
    print("Run:         yolo-box-editor start --data /path/to/data.yaml   (or: ybe start ...)")


# --------------------------------------------------------------------------- #
# argument parsing
# --------------------------------------------------------------------------- #
class Options:
    def __init__(self):
        self.cmd = ""
        self.dir = DEFAULT_DIR
        self.ref = ""
        self.latest = False
        self.commit = ""
        self.from_path = ""
        self.start = True
        self.purge = False
        self.yes = False
        self.python = PYTHON_CMD
        self.help = False
        self.resolved_ref = ""
        self.resolved_version = ""


USAGE = """ybx.py - install and update yolo-box-editor.

Usage:
  ybx.py install        [options]   install or reinstall the app
  ybx.py upgrade        [options]   install a newer version (alias: update)
  ybx.py version        [--dir DIR] print the installed version
  ybx.py check-update   [--dir DIR] compare installed vs latest
  ybx.py uninstall      [options]   remove the app, venv and launchers

Options:
  --dir DIR       install/user folder (default: ~/.local/share/yolo-box-editor)
  --home DIR      alias for --dir
  --version REF   tag/branch/commit to install (default: latest release, then
                  the newest tag, then the main branch)
  --latest        install the latest commit on the main branch (no git needed)
  --commit SHA    install a specific commit (no git needed)
  --from PATH     install from a local clone/folder or a .tar.gz (offline)
  --no-start      do not start the app after installing/upgrading
  --purge         uninstall: also delete the user folder (with --yes)
  --yes, -y       uninstall: skip the --purge confirmation
  --python CMD    python used to build the venv (default: python3)
  -h, --help      show this help

uninstall removes <dir>/app, <dir>/.venv, ybx.py and the launchers; your
actions/ hooks/ filters/ scripts/ shortcuts.txt are kept (add --purge --yes to
remove the whole folder).

All downloads use Python's urllib (no curl needed). The app is started in the
background after installing/upgrading (unless --no-start).
"""


def _need_value(argv, index, option):
    if index + 1 >= len(argv):
        die("%s needs a value" % option)
    return argv[index + 1]


def parse_args(argv):
    opts = Options()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in SUBCOMMANDS:
            opts.cmd = arg
        elif arg in ("--dir", "--home"):
            opts.dir = _need_value(argv, i, arg)
            i += 1
        elif arg.startswith("--dir=") or arg.startswith("--home="):
            opts.dir = arg.split("=", 1)[1]
        elif arg == "--version":
            opts.ref = _need_value(argv, i, arg)
            i += 1
        elif arg.startswith("--version="):
            opts.ref = arg.split("=", 1)[1]
        elif arg == "--latest":
            opts.latest = True
        elif arg == "--commit":
            opts.commit = _need_value(argv, i, arg)
            i += 1
        elif arg.startswith("--commit="):
            opts.commit = arg.split("=", 1)[1]
        elif arg == "--from":
            opts.from_path = _need_value(argv, i, arg)
            i += 1
        elif arg.startswith("--from="):
            opts.from_path = arg.split("=", 1)[1]
        elif arg == "--link":
            pass  # accepted no-op: launchers are always created
        elif arg == "--no-start":
            opts.start = False
        elif arg == "--purge":
            opts.purge = True
        elif arg in ("--yes", "-y"):
            opts.yes = True
        elif arg == "--python":
            opts.python = _need_value(argv, i, arg)
            i += 1
        elif arg.startswith("--python="):
            opts.python = arg.split("=", 1)[1]
        elif arg in ("-h", "--help"):
            opts.help = True
        else:
            sys.stderr.write("unknown option: %s\n" % arg)
            sys.stderr.write(USAGE)
            raise SystemExit(2)
        i += 1

    if opts.dir == "~" or opts.dir.startswith("~/"):
        opts.dir = os.path.expanduser(opts.dir)
    opts.dir = os.path.abspath(opts.dir)
    return opts


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Keep our progress lines in order with pip/subprocess output when stdout is
    # a pipe (e.g. `curl ... | bash`).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    opts = parse_args(argv)
    if opts.help or not opts.cmd:
        print(USAGE, end="")
        return 0
    if opts.cmd == "install":
        do_install(opts)
        return 0
    if opts.cmd in ("upgrade", "update"):
        return cmd_upgrade(opts)
    if opts.cmd == "version":
        return cmd_version(opts)
    if opts.cmd == "check-update":
        return cmd_check_update(opts)
    if opts.cmd == "uninstall":
        return cmd_uninstall(opts)
    print(USAGE, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
