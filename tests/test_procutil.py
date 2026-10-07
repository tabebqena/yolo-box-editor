"""Tests for `ybe.procutil` (the POSIX paths; Windows branches need Windows)."""

import os
import subprocess
import sys
import time

from ybe import procutil as proc

STUB = "import time\ntime.sleep(30)\n"


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_pid_alive():
    assert proc.pid_alive(os.getpid())
    assert not proc.pid_alive(0)
    assert not proc.pid_alive(999999)


def test_pid_cmdline_of_self():
    assert "python" in proc.pid_cmdline(os.getpid()).lower()


def test_pid_is_app(tmp_path):
    app = tmp_path / "app.py"
    app.write_text(STUB)
    child = subprocess.Popen([sys.executable, str(app)])
    try:
        assert _wait_for(lambda: proc.pid_is_app(child.pid, str(app)))
        assert not proc.pid_is_app(os.getpid(), str(app))
        assert not proc.pid_is_app(999999, str(app))
    finally:
        child.terminate()
        child.wait()


def test_terminate_stops_process(tmp_path):
    app = tmp_path / "app.py"
    app.write_text(STUB)
    child = subprocess.Popen([sys.executable, str(app)])
    assert _wait_for(lambda: proc.pid_alive(child.pid))
    proc.terminate(child.pid)
    assert not proc.pid_alive(child.pid)


def test_spawn_detaches_and_writes_log(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text(
        "import sys, time\n"
        "print('hello from child', flush=True)\n"
        "time.sleep(30)\n"
    )
    log = tmp_path / "out.log"
    child = proc.spawn([sys.executable, str(script)], str(log))
    try:
        assert _wait_for(lambda: log.exists() and "hello from child" in log.read_text())
        assert proc.pid_alive(child.pid)
    finally:
        proc.terminate(child.pid)
