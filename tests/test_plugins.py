"""Extension backend plugins and extension app actions (framework tests).

The individual shipped packages carry their own tests next to them
(`app/extensions/<id>/tests/`); this file covers the generic plugin machinery.
"""

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


def _mini_package(tmp_path, monkeypatch):
    """A tiny active package that declares one extension app action."""
    ext = tmp_path / "app-extensions"
    pkg = ext / "mini"
    pkg.mkdir(parents=True)
    (pkg / "extension.yaml").write_text(
        "api_version: 6\nid: mini\nname: Mini\nactive: true\n"
        "app_actions:\n"
        "  - name: clear\n"
        "    label: Clear\n"
        "    capability: mini.clear\n",
        encoding="utf-8")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    return pkg


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
    _mini_package(tmp_path, monkeypatch)
    ids = extension_app_action_ids()
    assert "ext.mini.clear" in ids
    defs = {d["id"]: d for d in extension_app_action_defs()}
    assert defs["ext.mini.clear"]["extension"] == "mini"
    assert defs["ext.mini.clear"]["capability"] == "mini.clear"


def test_resolve_entry_accepts_extension_app_actions(tmp_path, monkeypatch):
    _mini_package(tmp_path, monkeypatch)
    assert ybe._resolve_entry("ext.mini.clear", {}) == ("app", "ext.mini.clear", None)
    kind, msg, _pkg = ybe._resolve_entry("ext.mini.bogus", {})
    assert kind == "bad" and "unknown extension app action" in msg


def test_route_prefix_collision_blocks_enable(clean_state, tmp_path, monkeypatch):
    ext = tmp_path / "app-extensions"
    for pid in ("a", "b"):
        d = ext / pid
        d.mkdir(parents=True)
        (d / "backend.py").write_text(
            "def register(ctx):\n    return {}\n"
            "extension_routes = ({'rule': '', 'handler': lambda: 'x'},)\n",
            encoding="utf-8")
        (d / "extension.yaml").write_text(
            f"api_version: 5\nid: {pid}\nname: {pid}\nprefix: shared\nactive: true\n"
            "backend: backend.py\n", encoding="utf-8")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    from ybe.packages import package_route_prefix_duplicates
    assert package_route_prefix_duplicates() == {"shared": ["a", "b"]}
    # the first package enabled claims the prefix; the second is refused
    assert plugins.enable(ybe.app, "a") is True
    assert plugins.enable(ybe.app, "b") is False
    plugins.PLUGIN_REGISTRY.clear()
    plugins.PLUGIN_CAPABILITIES.clear()


def test_backend_registers_and_unregisters_filter_options(clean_state, tmp_path, monkeypatch):
    ext = tmp_path / "app-extensions"
    pkg = ext / "opts"
    pkg.mkdir(parents=True)
    (pkg / "backend.py").write_text(
        "def register(ctx):\n"
        "    return {'filter_options': {'{DATASET_THINGS}': lambda: ['a', 'b']}}\n",
        encoding="utf-8")
    (pkg / "extension.yaml").write_text(
        "api_version: 6\nid: opts\nname: Opts\nactive: true\nbackend: backend.py\n",
        encoding="utf-8")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    from ybe import extensions
    try:
        assert plugins.enable(ybe.app, "opts") is True
        assert extensions.resolve_filter_options(["{DATASET_THINGS}"], []) == ["a", "b"]
        assert plugins.disable("opts") is True
        # gone again: the token is a literal option when no provider owns it
        assert extensions.resolve_filter_options(["{DATASET_THINGS}"], []) == ["{DATASET_THINGS}"]
    finally:
        plugins.PLUGIN_REGISTRY.clear()
        plugins.PLUGIN_CAPABILITIES.clear()
        extensions.clear_filter_options()


def test_disabled_package_excludes_all_its_extensions(clean_state, tmp_path):
    base = tmp_path / "app-extensions" / "pkg"
    for kind, fname, body in (
        ("actions", "act.yaml", "name: pkg_action\nsteps:\n  - echo hi\n"),
        ("hooks", "on_after_save.yaml", "steps:\n  - echo hi\n"),
        ("filters", "f.yaml", "name: pkg_filter\nsteps:\n  - echo hi\n"),
        ("widgets", "w.yaml",
         "name: pkg_widget\ntitle: W\ncontrols:\n  - type: button\n    label: Go\n"
         "    steps:\n      - echo hi\n"),
    ):
        d = base / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(f"api_version: 5\n{body}", encoding="utf-8")
    (base / "extension.yaml").write_text(
        "api_version: 5\nid: pkg\nname: Pkg\nactive: true\n", encoding="utf-8")

    def names(kind):
        if kind == "action":
            return {a["name"] for a in ybe.load_actions()}
        if kind == "hook":
            return {h["name"] for h in ybe.load_hooks()[0]}
        if kind == "filter":
            return set(ybe.load_filters()[0])
        return set(ybe.load_widgets()[0])

    extension_flags.set_flag("pkg", True)
    assert "pkg_action" in names("action")
    assert "on_after_save" in names("hook")
    assert "pkg_filter" in names("filter")
    assert "pkg_widget" in names("widget")

    extension_flags.set_flag("pkg", False)
    assert "pkg_action" not in names("action")
    assert "on_after_save" not in names("hook")
    assert "pkg_filter" not in names("filter")
    assert "pkg_widget" not in names("widget")


def test_plugin_context_require_writable(clean_state):
    ctx = plugins.PluginContext(object(), {"id": "x"})
    ctx.require_writable()
    ybe.state.STATE["readonly"] = True
    with pytest.raises(PermissionError):
        ctx.require_writable()


def test_api_extensions_active_sets_flag(clean_state):
    client = ybe.app.test_client()
    resp = client.post("/api/extensions/active", json={"package": "demo", "active": False})
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False
    assert extension_flags.load_flags() == {"demo": False}
    resp = client.post("/api/extensions/active", json={"package": "demo", "active": True})
    assert resp.get_json()["active"] is True
    assert extension_flags.load_flags() == {"demo": True}
