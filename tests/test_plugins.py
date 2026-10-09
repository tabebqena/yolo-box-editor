"""Extension backend plugins, extension app actions and the tags package."""

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest
from flask import Flask

import app as ybe
from ybe import extension_flags, plugins
from ybe.packages import (
    _parse_manifest,
    extension_app_action_defs,
    extension_app_action_ids,
    load_packages,
)

BASE = Path(ybe.config.BASE_DIR)

_DEFAULT_STATE = {
    "data_yaml": None, "dataset_path": None, "splits": [], "images": [],
    "active_split": None, "active_filters": [], "filter_images": None,
    "filter_error": None, "classes": [], "readonly": False, "debug": False,
    "keep_pipe": False, "keep_filter_pipes": False, "no_update_check": False,
}


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Reset STATE and point the user folder at tmp_path."""
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(tmp_path / "app-extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "extensions"))
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(tmp_path / "app-filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe.config, "APP_SCRIPT_DIR", str(tmp_path / "app-scripts"))
    monkeypatch.setattr(ybe.config, "USER_SCRIPT_DIR", str(tmp_path / "scripts"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(_DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return tmp_path


def _tags_package(tmp_path):
    """Copy the shipped tags package into `extensions/tags`, activated."""
    ext = tmp_path / "extensions"
    ext.mkdir(parents=True, exist_ok=True)
    pkg = ext / "tags"
    shutil.copytree(BASE / "extensions" / "tags", pkg)
    manifest = (pkg / "extension.yaml").read_text(encoding="utf-8")
    (pkg / "extension.yaml").write_text(
        manifest.replace("active: false", "active: true"), encoding="utf-8")
    return ext


def _dataset(tmp_path):
    root = tmp_path / "ds"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "images" / "train" / "a.jpg").write_bytes(b"x")
    (root / "images" / "train" / "b.jpg").write_bytes(b"x")
    (root / "data.yaml").write_text(
        f"path: {root}\ntrain: images/train\nnames: [a]\n", encoding="utf-8")
    (root / "tags.yaml").write_text("- fire\n- smoke\n", encoding="utf-8")
    ybe._load_dataset(str(root / "data.yaml"))
    return root


def test_manifest_parses_backend_and_app_actions():
    data = _parse_manifest(
        "api_version: 5\n"
        "name: X\n"
        "backend: backend.py\n"
        "app_actions:\n"
        "  - name: clear_tags\n"
        "    label: Clear tags\n"
        "    shortcut: Alt+C\n"
        "    capability: tags.clear\n"
    )
    assert data["backend"] == "backend.py"
    assert data["app_actions"] == [{
        "name": "clear_tags", "label": "Clear tags",
        "shortcut": "Alt+C", "capability": "tags.clear",
    }]


def test_load_packages_discovers_app_actions(tmp_path, monkeypatch):
    ext = _tags_package(tmp_path)
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    ids = extension_app_action_ids()
    assert "ext.tags.clear_tags" in ids
    defs = {d["id"]: d for d in extension_app_action_defs()}
    assert defs["ext.tags.clear_tags"]["extension"] == "tags"
    assert defs["ext.tags.clear_tags"]["capability"] == "tags.clear"


def test_resolve_entry_accepts_extension_app_actions(tmp_path, monkeypatch):
    ext = _tags_package(tmp_path)
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    assert ybe._resolve_entry("ext.tags.clear_tags", {}) == ("app", "ext.tags.clear_tags")
    kind, msg = ybe._resolve_entry("ext.tags.bogus", {})
    assert kind == "bad" and "unknown extension app action" in msg


def _tags_capabilities(tmp_path, monkeypatch):
    """Import the tags backend and build its capability table with a real ctx."""
    ext = _tags_package(tmp_path)
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    pkg = next(p for p in load_packages()[0] if p["id"] == "tags")
    path = plugins.package_backend_path(pkg)
    spec = importlib.util.spec_from_file_location("tags_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = plugins.PluginContext(Flask("tags-test"), pkg)
    result = module.register(ctx) or {}
    caps = result.get("capabilities", result) if isinstance(result, dict) else {}
    return module, caps, ctx


def test_tags_capabilities_roundtrip(clean_state, tmp_path, monkeypatch):
    module, caps, ctx = _tags_capabilities(tmp_path, monkeypatch)
    root = _dataset(tmp_path)
    assert caps["tags.available"]() == ["fire", "smoke"]
    assert caps["tags.get"]("train/a.jpg") == []
    caps["tags.set"]("train/a.jpg", ["fire", "new"])
    assert caps["tags.get"]("train/a.jpg") == ["fire", "new"]
    # new names are registered in tags.yaml
    assert "new" in caps["tags.available"]()
    assert (root / "tags" / "train" / "a.txt").read_text() == "fire\nnew\n"
    caps["tags.clear"]("train/a.jpg")
    assert caps["tags.get"]("train/a.jpg") == []


def test_tags_copy_from_prev(clean_state, tmp_path, monkeypatch):
    module, caps, ctx = _tags_capabilities(tmp_path, monkeypatch)
    _dataset(tmp_path)
    caps["tags.set"]("train/a.jpg", ["fire"])
    caps["tags.copyFromPrev"]("train/b.jpg")
    assert caps["tags.get"]("train/b.jpg") == ["fire"]


def test_tags_set_dir_updates_override(clean_state, tmp_path, monkeypatch):
    module, caps, ctx = _tags_capabilities(tmp_path, monkeypatch)
    _dataset(tmp_path)
    custom = tmp_path / "mytags"
    custom.mkdir()
    assert caps["tags.setDir"](str(custom)) == {"tags_dir": str(custom)}
    store = Path(ybe.config.YBX_HOME) / ".tags_extension.json"
    saved = json.loads(store.read_text())
    assert list(saved.values()) == [str(custom)]


def test_tags_mutations_refuse_readonly(clean_state, tmp_path, monkeypatch):
    module, caps, ctx = _tags_capabilities(tmp_path, monkeypatch)
    _dataset(tmp_path)
    ybe.state.STATE["readonly"] = True
    with pytest.raises(PermissionError):
        caps["tags.set"]("train/a.jpg", ["fire"])


def test_extension_routes_dispatch_and_toggle_without_restart(clean_state, tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR",
                        str(Path(ybe.config.BASE_DIR) / "extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    _dataset(tmp_path)
    plugins.PLUGIN_REGISTRY.clear()
    plugins.PLUGIN_CAPABILITIES.clear()
    client = ybe.app.test_client()
    try:
        # disabled: the catch-all dispatcher finds no owner
        assert client.get("/api/tags?key=train/a.jpg").status_code == 404
        # enable live (no restart, no new Flask rules)
        assert plugins.enable(ybe.app, "tags") is True
        resp = client.get("/api/tags?key=train/a.jpg")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] and "fire" in body["available"]
        # a capability works too
        call = client.post("/api/extensions/call",
                           json={"package": "tags", "method": "tags.get",
                                 "args": ["train/a.jpg"]}).get_json()
        assert call["ok"] and call["value"] == []
        # url params + POST route
        post = client.post("/api/tags", json={"key": "train/a.jpg", "tags": ["fire"]})
        assert post.status_code == 200 and post.get_json()["tags"] == ["fire"]
        # disable live
        assert plugins.disable("tags") is True
        assert client.get("/api/tags?key=train/a.jpg").status_code == 404
    finally:
        plugins.PLUGIN_REGISTRY.clear()
        plugins.PLUGIN_CAPABILITIES.clear()


def test_plugin_context_require_writable(clean_state):
    ctx = plugins.PluginContext(object(), {"id": "x"})
    ctx.require_writable()
    ybe.state.STATE["readonly"] = True
    with pytest.raises(PermissionError):
        ctx.require_writable()


def test_api_extensions_active_sets_flag(clean_state, tmp_path):
    client = ybe.app.test_client()
    resp = client.post("/api/extensions/active", json={"package": "tags", "active": False})
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False
    assert extension_flags.load_flags() == {"tags": False}
    resp = client.post("/api/extensions/active", json={"package": "tags", "active": True})
    assert resp.get_json()["active"] is True
    assert extension_flags.load_flags() == {"tags": True}


def test_install_loads_shipped_backend_and_call_capability(clean_state, tmp_path, monkeypatch):
    ext = _tags_package(tmp_path)
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    _dataset(tmp_path)
    plugins.install(Flask("plugins-install-test"))
    assert "tags" in plugins.PLUGIN_CAPABILITIES
    try:
        value = plugins.call_capability("tags", "tags.available", [])
        assert "fire" in value
    finally:
        plugins.PLUGIN_CAPABILITIES.clear()
