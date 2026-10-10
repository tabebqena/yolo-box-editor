"""Self-contained tests for the shipped Tags extension.

They live next to the extension so the package can be read (and tested) on its
own. Run the whole suite with `python -m pytest -q` from the repo root, or just
this package with `python -m pytest app/extensions/tags -q`.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from flask import Flask

import app as ybe
from ybe import plugins
from ybe.packages import load_packages

PKG = Path(__file__).resolve().parents[1]
BASE = Path(ybe.config.BASE_DIR)

DEFAULT_STATE = {
    "data_yaml": None, "dataset_path": None, "splits": [], "images": [],
    "active_split": None, "active_filters": [], "filter_images": None,
    "filter_error": None, "classes": [], "readonly": False, "debug": False,
    "keep_pipe": False, "keep_filter_pipes": False, "no_update_check": False,
}


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Reset STATE; discover the shipped package and keep the user home local."""
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(BASE / "extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(tmp_path / "app-filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe.config, "APP_SCRIPT_DIR", str(tmp_path / "app-scripts"))
    monkeypatch.setattr(ybe.config, "USER_SCRIPT_DIR", str(tmp_path / "scripts"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return tmp_path


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


def _backend():
    """Import this package's backend.py and return (module, capabilities)."""
    pkg = next(p for p in load_packages()[0] if p["id"] == "tags")
    path = plugins.package_backend_path(pkg)
    spec = importlib.util.spec_from_file_location("tags_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = plugins.PluginContext(Flask("tags-test"), pkg)
    result = module.register(ctx) or {}
    caps = result.get("capabilities", result) if isinstance(result, dict) else {}
    return module, caps


def _activated(tmp_path, monkeypatch):
    """A copy of the package with `active: true`, in the shipped position."""
    ext = tmp_path / "app-extensions"
    pkg = ext / "tags"
    shutil.copytree(PKG, pkg, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = (pkg / "extension.yaml").read_text(encoding="utf-8")
    (pkg / "extension.yaml").write_text(
        manifest.replace("active: false", "active: true"), encoding="utf-8")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    return pkg


def test_register_declares_dataset_tags_filter_option(clean_state, tmp_path):
    module, _caps = _backend()
    result = module.register(plugins.PluginContext(Flask("tags-test"), {"id": "tags"}))
    provider = result["filter_options"]["{DATASET_TAGS}"]
    assert callable(provider)
    _dataset(tmp_path)
    assert provider() == ["fire", "smoke"]


def test_tag_filters_expose_tag_dropdown(clean_state, tmp_path, monkeypatch):
    _activated(tmp_path, monkeypatch)
    _dataset(tmp_path)
    plugins.install(Flask("tags-test"))
    try:
        filters, errors = ybe.load_filters()
        assert errors == []
        args = {a["name"]: a for a in filters["Has tag"]["arguments"]}
        assert args["tag_name"]["options"] == ["{DATASET_TAGS}"]
        assert ybe.resolve_filter_options(args["tag_name"]["options"], []) == ["fire", "smoke"]
    finally:
        plugins.disable("tags")


def test_declares_app_actions(clean_state):
    from ybe.packages import extension_app_action_defs
    defs = {d["id"]: d for d in extension_app_action_defs(only_active=False)}
    assert defs["ext.tags.clear_tags"]["extension"] == "tags"
    assert defs["ext.tags.clear_tags"]["capability"] == "tags.clear"


def test_capabilities_roundtrip(clean_state, tmp_path):
    _module, caps = _backend()
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


def test_copy_from_prev(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    caps["tags.set"]("train/a.jpg", ["fire"])
    caps["tags.copyFromPrev"]("train/b.jpg")
    assert caps["tags.get"]("train/b.jpg") == ["fire"]


def test_set_dir_updates_override(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    custom = tmp_path / "mytags"
    custom.mkdir()
    assert caps["tags.setDir"](str(custom)) == {"tags_dir": str(custom)}
    store = Path(ybe.config.YBX_HOME) / ".tags_extension.json"
    assert list(json.loads(store.read_text()).values()) == [str(custom)]


def test_mutations_refuse_readonly(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    ybe.state.STATE["readonly"] = True
    with pytest.raises(PermissionError):
        caps["tags.set"]("train/a.jpg", ["fire"])


def test_extension_routes_dispatch_and_toggle_without_restart(clean_state, tmp_path):
    _dataset(tmp_path)
    plugins.PLUGIN_REGISTRY.clear()
    plugins.PLUGIN_CAPABILITIES.clear()
    client = ybe.app.test_client()
    base = "/api/extension/tags"
    try:
        # disabled: the catch-all dispatcher finds no owner
        assert client.get(base + "?key=train/a.jpg").status_code == 404
        # enable live (no restart, no new Flask rules)
        assert plugins.enable(ybe.app, "tags") is True
        resp = client.get(base + "?key=train/a.jpg")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] and "fire" in body["available"]
        # a capability works too
        call = client.post("/api/extensions/call",
                           json={"package": "tags", "method": "tags.get",
                                 "args": ["train/a.jpg"]}).get_json()
        assert call["ok"] and call["value"] == []
        # the package's own sub-routes
        post = client.post(base + "/dir", json={"tags_dir": ""})
        assert post.status_code == 200 and post.get_json()["tags_dir"] is None
        post = client.post(base, json={"key": "train/a.jpg", "tags": ["fire"]})
        assert post.status_code == 200 and post.get_json()["tags"] == ["fire"]
        # disable live
        assert plugins.disable("tags") is True
        assert client.get(base + "?key=train/a.jpg").status_code == 404
    finally:
        plugins.PLUGIN_REGISTRY.clear()
        plugins.PLUGIN_CAPABILITIES.clear()


def test_install_loads_backend_and_call_capability(clean_state, tmp_path, monkeypatch):
    _activated(tmp_path, monkeypatch)
    _dataset(tmp_path)
    plugins.install(Flask("plugins-install-test"))
    assert "tags" in plugins.PLUGIN_CAPABILITIES
    try:
        value = plugins.call_capability("tags", "tags.available", [])
        assert "fire" in value
    finally:
        plugins.PLUGIN_CAPABILITIES.clear()
