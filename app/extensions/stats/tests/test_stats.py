"""Self-contained tests for the shipped Dataset statistics extension.

Run the whole suite with `python -m pytest -q` from the repo root, or just this
package with `python -m pytest app/extensions/stats -q`.
"""

import importlib.util
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
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(BASE / "extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return tmp_path


def _dataset(tmp_path):
    """Train (a, b) + val (c); a has two boxes, b one, c none; tags on all three."""
    root = tmp_path / "ds"
    for split, names in (("train", ["a.jpg", "b.jpg"]), ("val", ["c.jpg"])):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        (root / "tags" / split).mkdir(parents=True)
        for name in names:
            (root / "images" / split / name).write_bytes(b"x")
    (root / "data.yaml").write_text(
        f"path: {root}\ntrain: images/train\nval: images/val\n"
        "names: [person, car, bike]\n", encoding="utf-8")
    (root / "tags.yaml").write_text("- fire\n- smoke\n", encoding="utf-8")
    (root / "labels" / "train" / "a.txt").write_text(
        "0 0.5 0.5 0.2 0.2\n1 0.3 0.3 0.1 0.1\n", encoding="utf-8")
    (root / "labels" / "train" / "b.txt").write_text(
        "0 0.4 0.4 0.2 0.2\n", encoding="utf-8")
    (root / "tags" / "train" / "a.txt").write_text("fire\n", encoding="utf-8")
    (root / "tags" / "train" / "b.txt").write_text("fire\nsmoke\n", encoding="utf-8")
    (root / "tags" / "val" / "c.txt").write_text("smoke\n", encoding="utf-8")
    ybe._load_dataset(str(root / "data.yaml"))
    return root


def _backend():
    pkg = next(p for p in load_packages()[0] if p["id"] == "stats")
    path = plugins.package_backend_path(pkg)
    spec = importlib.util.spec_from_file_location("stats_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = plugins.PluginContext(Flask("stats-test"), pkg)
    result = module.register(ctx) or {}
    caps = result.get("capabilities", result) if isinstance(result, dict) else {}
    return module, caps


def _activated(tmp_path, monkeypatch):
    ext = tmp_path / "app-extensions"
    pkg = ext / "stats"
    shutil.copytree(PKG, pkg, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = (pkg / "extension.yaml").read_text(encoding="utf-8")
    (pkg / "extension.yaml").write_text(
        manifest.replace("active: false", "active: true"), encoding="utf-8")
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(ext))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    return pkg


def test_summary_counts(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    s = caps["stats.summary"]()
    assert s["loaded"] is True
    assert s["total"] == 3
    assert {r["name"]: r["images"] for r in s["splits"]} == {"train": 2, "val": 1}
    assert s["splits"][0]["percent"] == pytest.approx(66.7)

    tags = {r["name"]: r["images"] for r in s["tags"]["available"]}
    assert tags == {"fire": 2, "smoke": 2}
    assert s["tags"]["tagged"] == 3
    assert s["tags"]["untagged"] == 0

    classes = {r["name"]: r for r in s["classes"]}
    assert classes["person"]["boxes"] == 2
    assert classes["person"]["images"] == 2
    assert classes["car"]["boxes"] == 1
    assert classes["car"]["images"] == 1
    assert classes["bike"]["boxes"] == 0

    assert s["labels"] == {
        "with_labels": 2, "empty": 1, "boxes": 3, "boxes_per_image": 1.0}


def test_unknown_tag_is_reported(clean_state, tmp_path):
    _module, caps = _backend()
    root = _dataset(tmp_path)
    (root / "tags" / "val" / "c.txt").write_text("smoke\nstrange\n", encoding="utf-8")
    s = caps["stats.summary"]()
    unknown = {r["name"]: r["images"] for r in s["tags"]["unknown"]}
    assert unknown == {"strange": 1}
    assert s["tags"]["available"][1]["name"] == "smoke"


def test_query_by_tag_name_and_index(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    by_name = caps["stats.query"]("tag:smoke")
    assert by_name["count"] == 2 and by_name["total"] == 3
    assert by_name["percent"] == pytest.approx(66.7)
    assert by_name["by_split"] == {"train": 1, "val": 1}
    # index 1 is the first tag in tags.yaml (fire)
    assert caps["stats.query"]("tag:1")["count"] == 2
    assert caps["stats.query"]("tagged")["count"] == 3
    assert caps["stats.query"]("untagged")["count"] == 0


def test_query_by_class_split_and_empty(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    assert caps["stats.query"]("class:person")["count"] == 2
    assert caps["stats.query"]("class:1")["count"] == 1       # id 1 == car
    assert caps["stats.query"]("split:train")["count"] == 2
    assert caps["stats.query"]("empty")["count"] == 1         # only val/c.jpg
    assert caps["stats.query"]("empty")["images"] == ["val/c.jpg"]


def test_query_and_or(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    both = caps["stats.query"]("split:train tag:smoke")
    assert both["count"] == 1 and both["images"] == ["train/b.jpg"]
    either = caps["stats.query"]("tag:smoke or class:car")
    assert either["count"] == 3
    quoted = caps["stats.query"]('tag:"smoke"')
    assert quoted["count"] == 2


def test_query_errors_on_unknown_term(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    with pytest.raises(ValueError):
        caps["stats.query"]("nonsense")
    with pytest.raises(ValueError):
        caps["stats.query"]("split:nope")


def test_works_in_readonly(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    ybe.state.STATE["readonly"] = True
    assert caps["stats.summary"]()["total"] == 3
    assert caps["stats.query"]("tagged")["count"] == 3


def test_routes_and_live_enable(clean_state, tmp_path, monkeypatch):
    _activated(tmp_path, monkeypatch)
    _dataset(tmp_path)
    plugins.PLUGIN_REGISTRY.clear()
    plugins.PLUGIN_CAPABILITIES.clear()
    client = ybe.app.test_client()
    try:
        assert plugins.enable(ybe.app, "stats") is True
        body = client.get("/api/extension/stats").get_json()
        assert body["ok"] and body["summary"]["total"] == 3
        resp = client.get("/api/extension/stats/query?expr=tag:fire")
        assert resp.status_code == 200
        assert resp.get_json()["result"]["count"] == 2
        bad = client.get("/api/extension/stats/query?expr=oops")
        assert bad.status_code == 400 and bad.get_json()["ok"] is False
    finally:
        plugins.PLUGIN_REGISTRY.clear()
        plugins.PLUGIN_CAPABILITIES.clear()
