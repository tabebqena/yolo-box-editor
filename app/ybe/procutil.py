"""Cross-platform process helpers for the `ybe` launcher.

Everything that differs between Linux/macOS and Windows (pid liveness, reading a
process command line, detaching a background server, stopping it) lives here, so
the launcher logic itself stays platform-neutral.

Branches:
* pid liveness — `os.kill(pid, 0)` on POSIX; `OpenProcess`/`GetExitCodeProcess`
  on Windows (where `os.kill(pid, 0)` is not a liveness probe).
* command line — `/proc/<pid>/cmdline` on Linux, `ps -ww` on macOS/BSD, and
  PowerShell CIM (else the image path) on Windows.
* background start — a new session on POSIX; `DETACHED_PROCESS` +
  `CREATE_NEW_PROCESS_GROUP` on Windows.
* stop — `SIGTERM` then `SIGKILL` on POSIX; `taskkill /T /F` on Windows.
"""

import os
import shutil
import signal
import subprocess
import time

IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------- #
# liveness
# --------------------------------------------------------------------------- #
def pid_alive(pid):
    if pid <= 0:
        return False
    if IS_WINDOWS:
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # `kill -0` also succeeds for a zombie; treat one as not running so stop/wait
    # do not hang when the child has exited but not been reaped yet.
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as handle:
            data = handle.read()
        if data.rsplit(")", 1)[1].split()[0] == "Z":
            return False
    except (OSError, IndexError):
        pass
    return True


def _pid_alive_windows(pid):
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #
def pid_cmdline(pid):
    """The command line of `pid` as one string (empty when unavailable)."""
    if IS_WINDOWS:
        return _pid_cmdline_windows(pid)
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError:
        return ""
    return result.stdout.strip()


def _pid_cmdline_windows(pid):
    # PowerShell CIM includes the arguments (wmic is removed on recent Windows).
    for shell in ("powershell", "pwsh"):
        if not shutil.which(shell):
            continue
        command = "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\").CommandLine" % pid
        try:
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
            )
        except OSError:
            continue
        text = result.stdout.strip()
        if text:
            return text
    # Last resort: the executable image path (no arguments).
    return _windows_image_path(pid)


def _windows_image_path(pid):
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def pid_is_app(pid, app_path):
    """True when `pid` is alive and its command line references our app.py.

    Guards against a stale pid file whose PID was reused by an unrelated
    process after a crash or reboot.
    """
    if not pid_alive(pid):
        return False
    return app_path in pid_cmdline(pid)


# --------------------------------------------------------------------------- #
# start detached
# --------------------------------------------------------------------------- #
def spawn(argv, stdout_path, cwd=None):
    """Start `argv` detached from this process, output appended to a file.

    POSIX: `start_new_session` (setsid). Windows: `DETACHED_PROCESS` so the
    server keeps running without a console and survives this command exiting.
    """
    try:
        handle = open(stdout_path, "ab")
    except OSError:
        handle = subprocess.DEVNULL
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
    }
    if cwd:
        kwargs["cwd"] = cwd
    if IS_WINDOWS:
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs)
    finally:
        if hasattr(handle, "close"):
            handle.close()


# --------------------------------------------------------------------------- #
# stop
# --------------------------------------------------------------------------- #
def terminate(pid):
    """Stop `pid`, waiting briefly for it to exit before forcing it."""
    if not pid_alive(pid):
        return
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
            )
        except OSError:
            pass
        for _ in range(50):
            if not pid_alive(pid):
                return
            time.sleep(0.1)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(50):
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    time.sleep(0.2)
