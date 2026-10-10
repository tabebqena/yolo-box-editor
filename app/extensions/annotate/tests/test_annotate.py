"""Self-contained tests for the annotate example extension.

They live next to the extension so the package can be read (and tested) on its
own. Run the whole suite with `python -m pytest -q` from the repo root, or just
this package with `python -m pytest app/extensions/annotate -q`.

They exercise the manifest/environment, the backend capabilities and routes, the
async run start, and the standalone `data.yaml` reader — none of them needs
`ultralytics` (the model run is only exercised by a real user).
"""

import importlib.util
import json
from pathlib import Path

import pytest
from flask import Flask

import app as ybe
from ybe import envs, plugins
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
    """Reset STATE and point the user folders at tmp_path."""
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(BASE / "extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(ybe.config, "EXTENSION_ENVS_DIR", str(tmp_path / "extension_envs"))
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    monkeypatch.setattr(ybe.state, "USERS", {})
    return tmp_path


def _dataset(tmp_path):
    """A tiny dataset (real files are unnecessary: the backend only reads paths)."""
    root = tmp_path / "ds"
    (root / "images" / "train").mkdir(parents=True)
    (root / "images" / "train" / "a.jpg").write_bytes(b"x")
    (root / "images" / "train" / "b.jpg").write_bytes(b"x")
    (root / "data.yaml").write_text(
        f"path: {root}\ntrain: images/train\nnames: [a]\n", encoding="utf-8")
    ybe._load_dataset(str(root / "data.yaml"))
    return root


def _backend():
    """Import this package's backend.py and return (module, capabilities)."""
    pkg = next(p for p in load_packages()[0] if p["id"] == "annotate")
    path = plugins.package_backend_path(pkg)
    spec = importlib.util.spec_from_file_location("annotate_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = plugins.PluginContext(Flask("annotate-test"), pkg)
    result = module.register(ctx) or {}
    caps = result.get("capabilities", result) if isinstance(result, dict) else {}
    return module, caps


def test_manifest_declares_a_venv_environment(clean_state):
    pkg = next(p for p in load_packages()[0] if p["id"] == "annotate")
    info = envs.resolve(pkg)
    assert info["mode"] == "venv"
    assert info["requirements"] == ["ultralytics>=8.0"]


def test_backend_reads_separate_labels(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    out = tmp_path / "ext_labels"
    (out / "train").mkdir(parents=True)
    (out / "train" / "a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    assert caps["annotate.setDir"](str(out)) == {"output_dir": str(out)}
    assert caps["annotate.get"]("train/a.jpg") == [
        {"class": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]
    assert caps["annotate.get"]("train/b.jpg") == []
    # the override lives in the user home, keyed by the dataset
    store = Path(ybe.config.YBX_HOME) / ".annotate_extension.json"
    assert list(json.loads(store.read_text()).values()) == [str(out)]


def test_set_dir_refuses_readonly(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    ybe.state.STATE["readonly"] = True
    with pytest.raises(PermissionError):
        caps["annotate.setDir"](str(tmp_path))


def test_status_reports_settings_and_running(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    status = caps["annotate.status"]()
    assert status["running"] is False
    assert status["model"] == "" and status["conf"] == "0.25"


def test_start_validates_and_saves_settings(clean_state, tmp_path, monkeypatch):
    module, caps = _backend()
    _dataset(tmp_path)
    model = tmp_path / "model.pt"
    model.write_bytes(b"x")
    out = tmp_path / "ext_labels"

    class FakeProc:
        def poll(self):
            return None  # pretend the run is still in flight

    calls = {}

    def fake_popen(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    res = caps["annotate.start"](
        {"model": str(model), "output_dir": str(out), "conf": "0.4"})
    assert res["ok"] is True and res["running"] is True
    assert "--progress" in calls["command"]
    assert calls["kwargs"]["cwd"] == ybe.config.YBX_HOME
    # the panel settings are persisted and reported back
    status = caps["annotate.status"]()
    assert status["model"] == str(model) and status["conf"] == "0.4"
    assert status["running"] is True
    # a second run is refused while one is live
    again = caps["annotate.start"](
        {"model": str(model), "output_dir": str(out)})
    assert again["ok"] is False and again["running"] is True


def test_start_needs_a_dataset_and_a_model(clean_state, tmp_path):
    _module, caps = _backend()
    with pytest.raises(ValueError):
        caps["annotate.start"]({"model": "m.pt", "output_dir": "x"})
    _dataset(tmp_path)
    with pytest.raises(ValueError):
        caps["annotate.start"]({"model": "", "output_dir": str(tmp_path)})


def test_progress_reads_the_script_file(clean_state, tmp_path):
    _module, caps = _backend()
    _dataset(tmp_path)
    (Path(ybe.config.YBX_HOME) / ".annotate_progress.json").write_text(
        '{"done": 3, "total": 10, "current": "c.jpg", "phase": "running"}',
        encoding="utf-8")
    prog = caps["annotate.progress"]()
    assert prog["running"] is False  # no process was started here
    assert prog["done"] == 3 and prog["total"] == 10
    assert prog["current"] == "c.jpg"


def test_extension_routes_dispatch(clean_state, tmp_path):
    _dataset(tmp_path)
    plugins.PLUGIN_REGISTRY.clear()
    plugins.PLUGIN_CAPABILITIES.clear()
    client = ybe.app.test_client()
    base = "/api/extension/annotate"
    try:
        assert client.get(base + "?key=train/a.jpg").status_code == 404
        assert plugins.enable(ybe.app, "annotate") is True
        resp = client.get(base + "?key=train/a.jpg")
        assert resp.status_code == 200 and resp.get_json()["boxes"] == []
        post = client.post(base + "/dir", json={"output_dir": ""})
        assert post.status_code == 200 and post.get_json()["output_dir"] is None
        assert plugins.disable("annotate") is True
        assert client.get(base + "?key=train/a.jpg").status_code == 404
    finally:
        plugins.PLUGIN_REGISTRY.clear()
        plugins.PLUGIN_CAPABILITIES.clear()


def test_script_parses_data_yaml(tmp_path):
    """The model script has no ultralytics dependency for this part."""
    script = PKG / "scripts" / "annotate_all.py"
    spec = importlib.util.spec_from_file_location("annotate_all", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    root = tmp_path / "ds"
    root.mkdir()
    (root / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\n"
        "names:\n  0: fire\n  1: smoke\n", encoding="utf-8")
    base, splits, names = module.parse_data_yaml(str(root / "data.yaml"))
    assert base == str(root)
    assert splits == {"train": "images/train", "val": "images/val"}
    assert names == {0: "fire", 1: "smoke"}


def test_script_writes_progress(tmp_path):
    script = PKG / "scripts" / "annotate_all.py"
    spec = importlib.util.spec_from_file_location("annotate_all", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    target = tmp_path / "progress.json"
    module.write_progress(str(target), 2, 5, current="b.jpg")
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "done": 2, "total": 5, "current": "b.jpg", "phase": "running"}
    module.write_progress(str(target), 5, 5, phase="done")
    assert json.loads(target.read_text(encoding="utf-8"))["phase"] == "done"
