"""Backward-compatibility fixtures: every extension format version is tested on
each API update.

The real files live under `tests/fixtures/ext_api/v<N>/` (one folder per format
version, holding the artifacts that version introduced). When the format is
bumped, add a fixture folder and a history entry; these tests then exercise the
new version and re-check the older ones.
"""

import shutil
from pathlib import Path

import pytest

import app as ybe
from ybe import compat

FIX = Path(__file__).parent / "fixtures" / "ext_api"
NEWEST = ybe.config.EXTENSION_API_VERSION
MIN = compat.min_supported()

_KINDS = (
    ("actions", "USER_ACTIONS_DIR"),
    ("hooks", "USER_HOOKS_DIR"),
    ("filters", "USER_FILTERS_DIR"),
    ("widgets", "USER_WIDGETS_DIR"),
    ("extensions", "USER_EXTENSIONS_DIR"),
)

_DEFAULT_STATE = {
    "data_yaml": None, "dataset_path": None, "splits": [], "images": [],
    "active_split": None, "active_filters": [], "filter_images": None,
    "filter_error": None, "classes": [], "readonly": False, "debug": False,
    "keep_pipe": False, "keep_filter_pipes": False, "no_update_check": False,
}


def _home(tmp_path, monkeypatch, version):
    """Point the user folders at a copy of the v<version> fixture."""
    home = tmp_path / ("v%d" % version)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(home))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(home / "config.json"))
    for sub, attr in _KINDS:
        dest = home / sub
        dest.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(ybe.config, attr, str(dest))
        src = FIX / ("v%d" % version) / sub
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
    for attr in ("ACTIONS_DIR", "HOOKS_DIR", "FILTERS_DIR", "WIDGETS_DIR", "EXTENSIONS_DIR"):
        monkeypatch.setattr(ybe.config, attr, str(home / ("none-" + attr)))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(_DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return home


@pytest.mark.parametrize("version", range(MIN, NEWEST + 1))
def test_versions_in_window_load(version, tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, version)
    actions, action_errors = ybe.load_actions_report()
    assert ("Greet%d" % version) in [a["name"] for a in actions]
    assert action_errors == []
    assert ybe.load_hooks()[1] == []
    assert ybe.load_filters()[1] == []
    assert ybe.load_widgets()[1] == []
    if version >= 3:
        expected = {3: "oldpack", 4: "panelpack", 5: "backendpack", 6: "envpack"}[version]
        assert expected in [p["id"] for p in ybe.load_packages()[0]]


@pytest.mark.parametrize("version", range(1, MIN))
def test_versions_below_window_are_gated(version, tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, version)
    actions, errors = ybe.load_actions_report()
    assert ("Greet%d" % version) not in [a["name"] for a in actions]
    assert any("--allow-old-extensions" in e for e in errors)
    # the user can force parsing
    monkeypatch.setattr(ybe.config, "ALLOW_OLD_EXTENSIONS", True)
    actions, _ = ybe.load_actions_report()
    assert ("Greet%d" % version) in [a["name"] for a in actions]


def test_every_history_version_has_a_fixture():
    versions = [v for v, _ in ybe.config.EXTENSION_API_HISTORY]
    assert max(versions) == NEWEST, (
        "EXTENSION_API_HISTORY must end at EXTENSION_API_VERSION")
    for v in versions:
        assert (FIX / ("v%d" % v)).is_dir(), "missing fixture folder for v%d" % v


def test_support_table_declares_the_window():
    table = compat.support_table()
    ext = table["extension"]
    assert ext["newest"] == NEWEST
    assert ext["window"] == ybe.config.EXTENSION_API_SUPPORT_WINDOW
    assert ext["min_supported"] == MIN
    assert "responsible" in table["note"]
