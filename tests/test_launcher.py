"""Tests for the Python `ybe` launcher (`app/ybe/launcher.py`).

These run real child processes against a stub `app.py` (a sleeping script), so
they exercise pid tracking, stale-pid detection, background start and stop
without ever starting Flask.
"""

import os
import subprocess
import sys
import time

import pytest

from ybe import launcher

STUB_APP = "import time\ntime.sleep(30)\n"


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_pop_home_only_takes_the_first():
    home, rest = launcher._pop_home(["--home", "/x", "start", "--data", "d"])
    assert home == "/x"
    assert rest == ["start", "--data", "d"]

    # A later --home belongs to the app and is forwarded untouched.
    home, rest = launcher._pop_home(["start", "--home", "/y"])
    assert home is None
    assert rest == ["start", "--home", "/y"]

    home, rest = launcher._pop_home(["--dir=/z", "status"])
    assert home == "/z"
    assert rest == ["status"]


def test_resolve_home_prefers_explicit_then_env(tmp_path, monkeypatch):
    monkeypatch.delenv("YBX_HOME", raising=False)
    assert launcher.resolve_home(str(tmp_path)) == str(tmp_path.resolve())
    monkeypatch.setenv("YBX_HOME", str(tmp_path))
    assert launcher.resolve_home() == str(tmp_path.resolve())
    assert launcher.resolve_home(str(tmp_path / "other")) == str((tmp_path / "other").resolve())


def test_pid_roundtrip(tmp_path):
    path = str(tmp_path / "ybe.pid")
    assert launcher.read_pid(path) == 0
    launcher.write_pid(path, 4321)
    assert launcher.read_pid(path) == 4321


def test_pid_is_app_rejects_unrelated_pid(tmp_path):
    app = tmp_path / "app.py"
    app.write_text(STUB_APP)
    proc = subprocess.Popen([sys.executable, str(app)])
    try:
        assert _wait_for(lambda: launcher.pid_is_app(proc.pid, str(app)))
        # Our own (pytest) process does not reference the stub app.
        assert not launcher.pid_is_app(os.getpid(), str(app))
    finally:
        proc.terminate()
        proc.wait()


def test_status_and_stop_ignore_stale_pid(tmp_path, monkeypatch):
    app = tmp_path / "app.py"
    app.write_text(STUB_APP)
    monkeypatch.setattr(launcher, "app_py", lambda: str(app))
    home = str(tmp_path)

    # A pid file pointing at an unrelated live process must not read as running.
    launcher.write_pid(launcher.pid_file(home), os.getpid())
    assert launcher.do_status(home) == 1
    assert launcher.do_stop(home) == 0
    assert not os.path.exists(launcher.pid_file(home))


def test_background_start_status_stop(tmp_path, monkeypatch):
    app = tmp_path / "app.py"
    app.write_text(STUB_APP)
    monkeypatch.setattr(launcher, "app_py", lambda: str(app))
    home = str(tmp_path)

    try:
        assert launcher.do_start(home, []) == 0
        assert launcher.do_status(home) == 0
        pid = launcher.read_pid(launcher.pid_file(home))
        assert pid > 0
    finally:
        assert launcher.do_stop(home) == 0
    assert launcher.do_status(home) == 1


def test_main_dispatches_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "app_py", lambda: str(tmp_path / "app.py"))
    rc = launcher.main(["--home", str(tmp_path), "status"])
    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_main_unknown_command_exits_two(tmp_path, capsys):
    rc = launcher.main(["--home", str(tmp_path), "bogus"])
    assert rc == 2


def test_main_without_command_prints_usage(capsys):
    assert launcher.main([]) == 0
    assert "Usage:" in capsys.readouterr().out


def test_delegate_missing_installer_explains_fix(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        launcher.delegate(str(tmp_path), "update", [])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "ybx.py" in err
    assert launcher.INSTALL_ONELINER in err
    assert launcher.INSTALL_DOCS_URL in err


def _isolate_users(tmp_path, monkeypatch, password="s3cret"):
    """Point the account store at `tmp_path` without touching the real home."""
    from ybe import auth as ybe_auth, config as ybe_config

    monkeypatch.setattr(launcher, "app_py", lambda: str(tmp_path / "app.py"))
    monkeypatch.setattr(ybe_config, "configure_home", lambda path: None)
    monkeypatch.setattr(ybe_config, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(ybe_auth, "_prompt_password", lambda: password)


def test_do_users_create_list_update_delete(tmp_path, monkeypatch, capsys):
    _isolate_users(tmp_path, monkeypatch)
    home = str(tmp_path)

    assert launcher.do_users(home, []) == 0
    assert "no users" in capsys.readouterr().out

    assert launcher.do_users(home, ["--create", "alice"]) == 0
    assert "created user 'alice'" in capsys.readouterr().out

    assert launcher.do_users(home, []) == 0
    assert capsys.readouterr().out.strip() == "alice"

    assert launcher.do_users(home, ["--update", "alice"]) == 0
    assert "updated user 'alice'" in capsys.readouterr().out

    assert launcher.do_users(home, ["--delete", "alice"]) == 0
    assert "deleted user 'alice'" in capsys.readouterr().out

    assert launcher.do_users(home, []) == 0
    assert "no users" in capsys.readouterr().out


def test_do_users_create_rejects_duplicate(tmp_path, monkeypatch, capsys):
    _isolate_users(tmp_path, monkeypatch)
    home = str(tmp_path)
    launcher.do_users(home, ["--create", "alice"])
    with pytest.raises(SystemExit) as exc:
        launcher.do_users(home, ["--create", "alice"])
    assert exc.value.code == 1
    assert "already exists" in capsys.readouterr().err


def test_do_users_update_and_delete_require_existing(tmp_path, monkeypatch, capsys):
    _isolate_users(tmp_path, monkeypatch)
    home = str(tmp_path)
    for flag in ("--update", "--delete"):
        with pytest.raises(SystemExit) as exc:
            launcher.do_users(home, [flag, "ghost"])
        assert exc.value.code == 1
        assert "no such user" in capsys.readouterr().err


def test_do_users_lists_while_a_server_is_running(tmp_path, monkeypatch, capsys):
    _isolate_users(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, "pid_is_app", lambda pid, python_app=None: True)
    home = str(tmp_path)

    launcher.do_users(home, ["--create", "alice"])
    assert "run 'ybe restart'" in capsys.readouterr().out

    assert launcher.do_users(home, []) == 0
    assert capsys.readouterr().out.strip() == "alice"
