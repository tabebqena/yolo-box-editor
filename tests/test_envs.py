"""Tests for per-extension Python environments (`ybe.envs`).

The env builder shells out to `python -m venv` / `pip`, so those calls are
mocked; these tests only assert the resolution logic and the wiring (manifest
keys, `{EXT_*}` placeholders, the setup route and the launcher command).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import app as ybe
from ybe import envs
from ybe.packages import _parse_manifest

DEFAULT_STATE = {
    "data_yaml": None, "dataset_path": None, "splits": [], "images": [],
    "active_split": None, "active_filters": [], "filter_images": None,
    "filter_error": None, "classes": [], "readonly": False, "debug": False,
    "keep_pipe": False, "keep_filter_pipes": False, "no_update_check": False,
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point every relevant path constant at a disposable home."""
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(tmp_path / "app-extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "extensions"))
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "app-actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "app-hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(tmp_path / "app-filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe.config, "WIDGETS_DIR", str(tmp_path / "app-widgets"))
    monkeypatch.setattr(ybe.config, "USER_WIDGETS_DIR", str(tmp_path / "widgets"))
    monkeypatch.setattr(ybe.config, "EXTENSION_ENVS_DIR", str(tmp_path / "extension_envs"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    return tmp_path


def write_pkg(home, pid, manifest, files=None):
    pkg_dir = Path(home) / "extensions" / pid
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "extension.yaml").write_text(manifest, encoding="utf-8")
    for name, body in (files or {}).items():
        path = pkg_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return pkg_dir


# --- manifest parsing ------------------------------------------------------- #
def test_manifest_parses_environment_keys():
    data = _parse_manifest(
        "api_version: 6\nid: p\npython: current\n"
        "requirements:\n  - ultralytics>=8\n  - onnxruntime\n"
        "requirements_file: req.txt\n"
    )
    assert data["python"] == "current"
    assert data["requirements"] == ["ultralytics>=8", "onnxruntime"]
    assert data["requirements_file"] == "req.txt"


def test_manifest_defaults_have_no_environment():
    data = _parse_manifest("api_version: 6\nid: p\n")
    assert data["python"] is None
    assert data["requirements"] == []
    assert data["requirements_file"] is None


# --- mode parsing ----------------------------------------------------------- #
@pytest.mark.parametrize("value,expected_mode", [
    (None, envs.MODE_VENV),
    ("", envs.MODE_VENV),
    ("venv", envs.MODE_VENV),
    ("auto", envs.MODE_VENV),
    ("current", envs.MODE_CURRENT),
])
def test_parse_mode_keywords(value, expected_mode):
    mode, interpreter = envs.parse_mode(value)
    assert mode == expected_mode
    assert interpreter is None


def test_parse_mode_path():
    mode, interpreter = envs.parse_mode("/opt/py/bin/python")
    assert mode == envs.MODE_PATH
    assert interpreter == os.path.abspath("/opt/py/bin/python")


# --- resolution ------------------------------------------------------------- #
def _pkg(home, **kw):
    base = {"id": "p", "path": str(home), "python": None,
            "requirements": [], "requirements_file": None}
    base.update(kw)
    return base


def test_requirements_for_merges_inline_and_file(home):
    (Path(home) / "req.txt").write_text(
        "# a comment\nfoo==1.0\n\nbar>=2\n", encoding="utf-8")
    pkg = _pkg(home, requirements=["bar>=2", "baz"], requirements_file="req.txt")
    assert envs.requirements_for(pkg) == ["bar>=2", "baz", "foo==1.0"]


def test_resolve_none_when_nothing_declared(home):
    info = envs.resolve(_pkg(home))
    assert info["status"] == "none"
    assert info["declared"] is False


def test_resolve_venv_missing_then_ready(home):
    pkg = _pkg(home, requirements=["foo"])
    info = envs.resolve(pkg)
    assert info["mode"] == envs.MODE_VENV
    assert info["status"] == "missing"
    assert info["env_dir"] == str(Path(home) / "extension_envs" / "p")

    py = Path(info["env_dir"]) / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    info = envs.resolve(pkg)
    assert info["status"] == "ready"
    assert info["python"] == str(py)


def test_resolve_current_uses_app_interpreter(home):
    info = envs.resolve(_pkg(home, python="current", requirements=["foo"]))
    assert info["mode"] == envs.MODE_CURRENT
    assert info["python"] == sys.executable
    assert info["env_dir"] == ""
    assert info["status"] == "ready"


def test_placeholder_values_for_package(home):
    write_pkg(home, "p", "api_version: 6\nid: p\npython: current\nrequirements:\n  - foo\n")
    values = envs.placeholder_values("p")
    assert values["EXT_DIR"] == str(Path(home) / "extensions" / "p")
    assert values["EXT_PYTHON"] == sys.executable
    assert values["EXT_ENV_DIR"] == ""


def test_placeholder_values_fall_back_for_loose_files(home):
    values = envs.placeholder_values(None)
    assert values == {"EXT_DIR": "", "EXT_PYTHON": sys.executable, "EXT_ENV_DIR": ""}


# --- setup (subprocess mocked) ---------------------------------------------- #
def test_setup_builds_venv_and_installs(home, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(envs.subprocess, "run", fake_run)
    pkg = _pkg(home, requirements=["foo"])
    result = envs.setup(pkg)
    assert result["ok"] is True
    assert any("-m" in c and "venv" in c for c in calls)
    assert any(c[:3] == [envs.venv_python(result["info"]["env_dir"]), "-m", "pip"]
               for c in calls)
    pip = [c for c in calls if "install" in c]
    assert pip and "foo" in pip[-1]


def test_setup_reports_pip_failure(home, monkeypatch):
    def fake_run(cmd, **kwargs):
        if "install" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(envs.subprocess, "run", fake_run)
    result = envs.setup(_pkg(home, requirements=["foo"]))
    assert result["ok"] is False
    assert "pip install failed" in result["error"]


# --- server wiring ---------------------------------------------------------- #
def test_api_config_includes_environment(home):
    write_pkg(home, "p", "api_version: 6\nid: p\npython: current\nrequirements:\n  - foo\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    pkg = next(p for p in cfg["extension_packages"] if p["id"] == "p")
    assert pkg["environment"]["declared"] is True
    assert pkg["environment"]["requirements"] == ["foo"]


def test_api_extension_env_route(home, monkeypatch):
    write_pkg(home, "p", "api_version: 6\nid: p\nrequirements:\n  - foo\n")
    monkeypatch.setattr(envs, "setup", lambda pkg, **kw: {
        "ok": True, "mode": "venv", "log": "done", "error": None,
        "info": envs.resolve(pkg)})
    resp = ybe.app.test_client().post("/api/extensions/env", json={"package": "p"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True and data["log"] == "done"


def test_api_extension_env_unknown_package(home):
    resp = ybe.app.test_client().post("/api/extensions/env", json={"package": "nope"})
    assert resp.status_code == 400
