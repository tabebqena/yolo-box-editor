"""Per-user extension enable/disable flags and the tags-flag migration."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app as ybe
from ybe import extension_flags
from ybe.packages import load_packages


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "SETTINGS_FILE", str(tmp_path / ".settings.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(tmp_path / "app-extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "extensions"))
    return tmp_path


def _write_config(home, settings):
    (home / "config.json").write_text(json.dumps({"settings": settings}), encoding="utf-8")


def test_fresh_install_enables_tags(home):
    assert extension_flags.migrate_tags_flag() is True
    saved = json.loads((home / "extensions.json").read_text())
    assert saved == {"active": {"tags": True}}


def test_update_reads_old_tags_flag(home):
    _write_config(home, {"tags": False})
    assert extension_flags.migrate_tags_flag() is False


def test_update_reads_old_visibility_flag(home):
    _write_config(home, {"ybe_tags_visible": "0"})
    assert extension_flags.migrate_tags_flag() is False
    _write_config(home, {"ybe_tags_visible": "1"})
    (home / "extensions.json").unlink()
    assert extension_flags.migrate_tags_flag() is True


def test_update_without_flag_keeps_tags_on(home):
    _write_config(home, {"autoSave": "1"})
    assert extension_flags.migrate_tags_flag() is True


def test_legacy_settings_file_is_read(home):
    (home / ".settings.json").write_text(json.dumps({"tags": False}), encoding="utf-8")
    assert extension_flags.migrate_tags_flag() is False


def test_migration_is_idempotent(home):
    extension_flags.set_flag("tags", False)
    _write_config(home, {"tags": True})
    assert extension_flags.migrate_tags_flag() is False


def test_set_flag_preserves_others(home):
    extension_flags.set_flag("other", True)
    extension_flags.set_flag("tags", False)
    assert extension_flags.load_flags() == {"other": True, "tags": False}


def test_load_packages_applies_override(home):
    pkg = home / "app-extensions" / "tags"
    pkg.mkdir(parents=True)
    (pkg / "extension.yaml").write_text(
        "api_version: 5\nname: Tags\nactive: false\n", encoding="utf-8")

    assert next(p for p in load_packages()[0] if p["id"] == "tags")["active"] is False
    extension_flags.set_flag("tags", True)
    assert next(p for p in load_packages()[0] if p["id"] == "tags")["active"] is True
    extension_flags.set_flag("tags", False)
    assert next(p for p in load_packages()[0] if p["id"] == "tags")["active"] is False


def test_migrate_script_runs_standalone(home, tmp_path):
    script = Path(ybe.config.BASE_DIR) / "scripts" / "migrate_tags_extension.py"
    target = tmp_path / "userhome"
    target.mkdir()
    (target / "config.json").write_text(json.dumps({"settings": {"tags": False}}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "--home", str(target)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "disabled" in proc.stdout
    assert json.loads((target / "extensions.json").read_text()) == {"active": {"tags": False}}
    # --enable overrides
    proc = subprocess.run(
        [sys.executable, str(script), "--home", str(target), "--enable"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads((target / "extensions.json").read_text()) == {"active": {"tags": True}}
