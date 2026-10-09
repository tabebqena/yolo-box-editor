"""Extension permissions: parsing, the honesty check and the install command."""

import json
import os
from pathlib import Path

import pytest

import app as ybe
from ybe import launcher, permissions
from ybe.packages import load_packages

_DEFAULT_STATE = {
    "data_yaml": None, "dataset_path": None, "splits": [], "images": [],
    "active_split": None, "active_filters": [], "filter_images": None,
    "filter_error": None, "classes": [], "readonly": False, "debug": False,
    "keep_pipe": False, "keep_filter_pipes": False, "no_update_check": False,
}


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Point the user folder at tmp_path and reset the runtime state."""
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(tmp_path / "app-extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "extensions"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(_DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return tmp_path


SAMPLE = """\
api_version: 1
ybe:
  - state.read
  - capabilities
backend: true
ui: true
routes:
  - ""
  - /dir
actions:
  - My action
filters:
  - By tag
scripts:
  - helper.py
"""


def test_parse_permissions_reads_everything():
    perms = permissions.parse_permissions(SAMPLE)
    assert perms["api_version"] == 1
    assert perms["ybe"] == ["state.read", "capabilities"]
    assert perms["backend"] is True and perms["ui"] is True
    assert perms["routes"] == ["/dir"]          # empty rule is the mount point
    assert perms["actions"] == ["My action"]
    assert perms["filters"] == ["By tag"]
    assert perms["scripts"] == ["helper.py"]


def test_describe_explains_ybe_and_artifacts():
    lines = permissions.describe(permissions.parse_permissions(SAMPLE))
    assert any("state.read" in l and "editor state" in l for l in lines)
    assert any(l.startswith("Runs server-side Python") for l in lines)
    assert "Action: My action" in lines
    assert "Script: helper.py" in lines


def test_allows_gates_ybe_methods():
    perms = permissions.parse_permissions("ybe:\n  - state.read\n")
    assert permissions.allows("state.getImage", perms) is True
    assert permissions.allows("callbacks.save", perms) is False
    assert permissions.allows("callbacks.save", None) is True  # legacy: no file


def _write_pkg(path, manifest, perms=None, parts=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / "extension.yaml").write_text(manifest, encoding="utf-8")
    if perms is not None:
        (path / "permissions.yaml").write_text(perms, encoding="utf-8")
    for sub, names in (parts or {}).items():
        d = path / sub
        d.mkdir(parents=True, exist_ok=True)
        for fname, body in names.items():
            (d / fname).write_text(body, encoding="utf-8")


def test_coverage_flags_undeclared_artifacts(clean_state, tmp_path, monkeypatch):
    ext = tmp_path / "app-extensions"
    _write_pkg(
        ext / "pkg",
        "api_version: 5\nid: pkg\nname: Pkg\nactive: true\nbackend: backend.py\n",
        perms="api_version: 1\n",  # declares nothing
        parts={
            "actions": {"a.yaml": "api_version: 5\nname: My action\nsteps:\n  - echo hi\n"},
            "scripts": {"helper.py": "# helper\n"},
        },
    )
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    pkg = next(p for p in load_packages()[0] if p["id"] == "pkg")
    assert pkg["permissions"] is not None
    errs = pkg["permission_errors"]
    assert any("action" in e and "My action" in e for e in errs)
    assert any("script" in e and "helper.py" in e for e in errs)
    assert any("backend.py" in e for e in errs)


def test_load_packages_without_permissions_file(clean_state, tmp_path, monkeypatch):
    ext = tmp_path / "app-extensions"
    _write_pkg(ext / "pkg", "api_version: 5\nid: pkg\nname: Pkg\nactive: true\n")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    pkg = next(p for p in load_packages()[0] if p["id"] == "pkg")
    assert pkg["permissions"] is None
    assert pkg["permission_errors"] == []


def test_shipped_packages_have_consistent_permissions():
    ybe.config.EXTENSIONS_DIR  # sanity: path exists
    packages, _ = load_packages()
    # Every shipped package that ships a permissions file must be honest.
    shipped = [p for p in packages if p["source"] == "shipped" and p["permissions"]]
    assert shipped, "expected shipped packages to declare permissions"
    for pkg in shipped:
        assert pkg["permission_errors"] == [], (pkg["id"], pkg["permission_errors"])


def test_install_extension_copies_and_enables(clean_state, tmp_path):
    src = tmp_path / "src_hello"
    _write_pkg(src, "api_version: 5\nid: hello\nname: Hello\nui: true\n",
               perms="api_version: 1\nybe:\n  - state.read\nui: true\n")
    rc = launcher.do_install_extension(str(tmp_path), [str(src), "--yes"])
    assert rc == 0
    dest = Path(ybe.config.USER_EXTENSIONS_DIR) / "hello"
    assert (dest / "extension.yaml").is_file()
    assert (dest / "permissions.yaml").is_file()
    flags = json.loads((Path(ybe.config.YBX_HOME) / "extensions.json").read_text())
    assert flags == {"active": {"hello": True}}


def test_install_extension_refuses_builtin(clean_state, tmp_path):
    ext = tmp_path / "app-extensions"
    (ext / "tags").mkdir(parents=True)
    (ext / "tags" / "extension.yaml").write_text("api_version: 5\nid: tags\nname: Tags\n")
    ybe.config.EXTENSIONS_DIR = str(ext)
    src = tmp_path / "src_tags"
    _write_pkg(src, "api_version: 5\nid: tags\nname: Tags\n",
               perms="api_version: 1\n")
    with pytest.raises(SystemExit):
        launcher.do_install_extension(str(tmp_path), [str(src), "--yes"])


def test_install_extension_requires_permissions(clean_state, tmp_path):
    src = tmp_path / "src_np"
    _write_pkg(src, "api_version: 5\nid: np\nname: NP\n")
    with pytest.raises(SystemExit):
        launcher.do_install_extension(str(tmp_path), [str(src), "--yes"])
    # --force installs it anyway
    assert launcher.do_install_extension(str(tmp_path), [str(src), "--yes", "--force"]) == 0
