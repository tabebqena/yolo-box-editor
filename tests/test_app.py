"""Test suite for the yolo-box-editor Flask app (app.py).

Run from the repo root; the app is a single module with no package layout, so
the repo root is added to sys.path here.

The app's own support files (the actions/ folder / shortcuts.txt /
.recent_data_yamls.json) are NEVER touched: fixtures monkeypatch every file
constant to disposable paths under tmp_path, and STATE is reset per test.
"""

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as ybe

# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
DEFAULT_STATE = {
    "data_yaml": None,
    "dataset_path": None,
    "splits": [],
    "images": [],
    "active_split": None,
    "active_filter": None,
    "filter_images": None,
    "filter_error": None,
    "classes": [],
    "readonly": False,
    "debug": False,
    "keep_pipe": False,
}


def _img(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (10, 20, 30)).save(path)


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Reset STATE and redirect file constants away from the repo."""
    monkeypatch.setattr(ybe, "RECENT_FILE", str(tmp_path / "recent.json"))
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "shortcuts.txt"))
    monkeypatch.setattr(ybe, "SHORTCUTS_ADD_FILE", str(tmp_path / "shortcuts.a.txt"))
    monkeypatch.setattr(ybe, "PIPE_DIR", str(tmp_path / "pipes"))
    ybe.STATE.clear()
    ybe.STATE.update(DEFAULT_STATE)
    return tmp_path


def make_dataset(root, names=("fire", "smoke"), splits=("train", "val", "test"),
                 images=("a", "b")):
    """Create a disposable YOLO dataset tree with real image files."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    yaml_names = "[" + ", ".join(names) + "]"
    (root / "data.yaml").write_text(
        f"path: {root}\n"
        + "".join(f"{s}: images/{s}\n" for s in splits)
        + f"nc: {len(names)}\n"
        f"names: {yaml_names}\n",
        encoding="utf-8",
    )
    for s in splits:
        for n in images:
            _img(root / "images" / s / f"{n}.jpg")
    return root


def load_dataset(client, root):
    """POST the dataset and assert success; returns the config payload."""
    resp = client.post("/api/data", json={"data_yaml": str(root / "data.yaml")})
    assert resp.status_code == 200
    cfg = resp.get_json()
    assert cfg["ok"] is True
    return cfg


def write_action(root, fname, body):
    """Write one action file into <root>/actions (created on demand)."""
    d = Path(root) / "actions"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def write_hook(root, fname, body):
    """Write one hook file into <root>/hooks (created on demand)."""
    d = Path(root) / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def write_filter(root, fname, body):
    """Write one filter script into <root>/filters (created on demand)."""
    d = Path(root) / "filters"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# yaml parsing
# --------------------------------------------------------------------------- #
def test_strip_comment():
    assert ybe._strip_comment("names: [a] # trailing") == "names: [a]"
    assert ybe._strip_comment("# whole line") == ""


def test_yaml_names_inline_list():
    value = ybe._parse_yaml_names_value("['fire', 'smoke', other]  # x")
    assert value == ["fire", "smoke", "other"]


def test_yaml_names_block_form():
    value = ybe._parse_yaml_names_value("\n- fire\n- smoke\n- other\n")
    assert value == ["fire", "smoke", "other"]


def test_yaml_names_mapping_form():
    value = ybe._parse_yaml_names_value("0: fire\n1: smoke")
    assert value == ["fire", "smoke"]


def test_yaml_names_empty_value():
    assert ybe._parse_yaml_names_value("") == []
    assert ybe._parse_yaml_names_value("   ") == []


def test_extract_yaml_block_finds_nested_key():
    lines = ["a: 1", "  names:", "    - fire", "b: 2"]
    block = ybe._extract_yaml_block(lines, "names")
    assert "fire" in block and "a: 1" not in block


def test_extract_yaml_block_missing_key():
    assert ybe._extract_yaml_block(["a: 1"], "names") is None


def test_parse_data_yaml_full(tmp_path):
    p = tmp_path / "data.yaml"
    p.write_text(
        "# comment\n"
        f"path: {tmp_path}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"test: images/test\n"
        f"nc: 3\n"
        f"names: ['fire', 'smoke', 'other']\n",
        encoding="utf-8",
    )
    data = ybe._parse_data_yaml(str(p))
    assert data["path"] == str(tmp_path)
    assert data["train"] == "images/train"
    assert data["val"] == "images/val"
    assert data["test"] == "images/test"
    assert data["nc"] == 3
    assert data["names"] == ["fire", "smoke", "other"]


def test_parse_data_yaml_missing_file(tmp_path):
    assert ybe._parse_data_yaml(str(tmp_path / "nope.yaml")) == {}


def test_parse_data_yaml_ignores_bad_nc(tmp_path):
    p = tmp_path / "data.yaml"
    p.write_text("nc: nope\nnames: [fire]\n", encoding="utf-8")
    data = ybe._parse_data_yaml(str(p))
    assert "nc" not in data
    assert data["names"] == ["fire"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def test_is_image():
    assert ybe.is_image("x.JPG")
    assert ybe.is_image("x.png")
    assert not ybe.is_image("x.txt")
    assert not ybe.is_image("x")


def test_labels_dir_replaces_images_segment():
    assert ybe._labels_dir_for("/d/images/train") == "/d/labels/train"


def test_labels_dir_fallback_sibling():
    assert ybe._labels_dir_for("/d/train") == "/d/labels/train"


def test_build_command_quotes_placeholders_with_spaces():
    cmd = ybe.build_command(
        "echo {IMAGE_PATH} {LABEL_PATH}", {"IMAGE_PATH": "a b.jpg", "LABEL_PATH": "x"}
    )
    assert cmd == "echo 'a b.jpg' x"


def test_build_command_only_known_placeholders():
    cmd = ybe.build_command(
        "touch {LABEL_PATH}", {"IMAGE_PATH": "a", "LABEL_PATH": "b.txt"}
    )
    assert cmd == "touch b.txt"
    assert "a" not in cmd


def test_build_command_substitutes_dataset_path_and_index():
    cmd = ybe.build_command(
        "echo {DATASET_PATH} {IMAGE_INDEX}",
        {"DATASET_PATH": "a b", "IMAGE_INDEX": "1"},
    )
    assert cmd == "echo 'a b' 1"


# --------------------------------------------------------------------------- #
# actions/ / shortcuts.txt
# --------------------------------------------------------------------------- #
def test_parse_shortcut_line_valid():
    assert ybe.parse_shortcut_line("app_next <ArrowRight> next image") == (
        "app_next",
        "ArrowRight",
        "next image",
    )


def test_parse_shortcut_line_modifiers():
    name, key, _ = ybe.parse_shortcut_line("X <Ctrl+Shift+K> go")
    assert (name, key) == ("X", "Ctrl+Shift+K")


def test_parse_shortcut_line_rejects_bad_forms():
    assert ybe.parse_shortcut_line("# comment") is None
    assert ybe.parse_shortcut_line("") is None
    assert ybe.parse_shortcut_line("just_a_name") is None
    assert ybe.parse_shortcut_line("X no-brackets") is None
    assert ybe.parse_shortcut_line("X <> empty key") is None


def test_parse_action_file_list_and_single_value_forms():
    parsed = ybe._parse_action_file(
        "# comment\n"
        "name: Remove\n"
        "steps:\n"
        "  - rm -f {IMAGE_PATH}\n"
        "  - rm -f {LABEL_PATH}\n"
        "after_success: app_refresh_image\n"
    )
    assert parsed["name"] == "Remove"
    assert parsed["steps"] == ["rm -f {IMAGE_PATH}", "rm -f {LABEL_PATH}"]
    assert parsed["after_success"] == ["app_refresh_image"]


def test_parse_action_file_unquotes_scalars():
    parsed = ybe._parse_action_file("steps:\n  - \"gimp '{IMAGE_PATH}'\"\n")
    assert parsed["steps"] == ["gimp '{IMAGE_PATH}'"]


def test_load_actions_dir_one_file_per_action(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    write_action(tmp_path, "Keep.yaml", "steps:\n  - echo one\n")
    write_action(
        tmp_path,
        "Remove.yaml",
        "steps:\n  - rm {IMAGE_PATH}\n"
        "after_success:\n  - app_refresh_images_list\n",
    )
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Keep"]["steps"] == ["echo one"]  # name from the file name
    assert actions["Remove"]["steps"] == ["rm {IMAGE_PATH}"]
    assert actions["Remove"]["after_success"] == ["app_refresh_images_list"]


def test_load_actions_name_key_overrides_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    write_action(tmp_path, "whatever.yaml", "name: Custom\nsteps:\n  - echo hi\n")
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert "Custom" in actions and "whatever" not in actions


def test_load_actions_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    write_action(tmp_path, "Shared.yaml", "steps:\n  - echo repo\n")
    write_action(tmp_path, "Shared.a.yaml", "steps:\n  - echo user\n")
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Shared"]["steps"] == ["echo user"]


def test_load_actions_override_targets_name_key(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    write_action(tmp_path, "Shared.yaml", "steps:\n  - echo repo\n")
    write_action(tmp_path, "mine.a.yaml", "name: Shared\nsteps:\n  - echo user\n")
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Shared"]["steps"] == ["echo user"]


def test_load_actions_ignores_empty_entries_and_non_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    write_action(tmp_path, "Empty.yaml", "name: Empty\nafter_success: []\n")
    write_action(tmp_path, "notes.txt", "steps:\n  - echo hi\n")
    assert ybe.load_actions() == []


def test_load_actions_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "nope"))
    assert ybe.load_actions() == []


def test_is_hook_name_matches_only_on_prefix():
    assert ybe.is_hook_name("on_after_save")
    assert ybe.is_hook_name("on_box_created")
    assert ybe.is_hook_name("on_prev")
    assert ybe.is_hook_name("on_next")
    assert not ybe.is_hook_name("app_save")
    assert not ybe.is_hook_name("Remove")
    assert not ybe.is_hook_name("")
    assert not ybe.is_hook_name(None)


def test_parse_action_file_reads_event_name_and_active():
    parsed = ybe._parse_action_file(
        "event_name: after_save\nactive: false\nsteps:\n  - echo hi\n"
    )
    assert parsed["event_name"] == "after_save"
    assert parsed["active"] is False


def test_load_hooks_event_from_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo saved\n")
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]
    assert hooks[0]["event"] == "after_save"
    assert hooks[0]["steps"] == ["echo saved"]


def test_load_hooks_event_name_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(
        tmp_path, "whatever.yaml", "event_name: after_save\nsteps:\n  - echo hi\n"
    )
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]


def test_load_hooks_known_filename_wins_over_event_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "event_name: before_save\nsteps:\n  - echo hi\n",
    )
    hooks, _ = ybe.load_hooks()
    assert hooks[0]["event"] == "after_save"


def test_load_hooks_inactive_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "active: false\nsteps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_unknown_event_with_steps_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(tmp_path, "on_nope.yaml", "steps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == []
    assert len(errors) == 1 and "on_nope.yaml" in errors[0]


def test_load_hooks_empty_template_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(tmp_path, "example.yaml", "# comments only, no steps\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo repo\n")
    write_hook(tmp_path, "on_after_save.a.yaml", "steps:\n  - echo user\n")
    hooks, _ = ybe.load_hooks()
    assert [h["steps"] for h in hooks] == [["echo user"]]


def test_load_hooks_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "nope"))
    assert ybe.load_hooks() == ([], [])


def test_load_shortcuts_merges_and_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe, "SHORTCUTS_ADD_FILE", str(tmp_path / "s.a.txt"))
    (tmp_path / "s.txt").write_text("app_next <D> repo\napp_undo <Z> undo\n",
                                    encoding="utf-8")
    (tmp_path / "s.a.txt").write_text("app_next <F> user\n", encoding="utf-8")
    shortcuts = ybe.load_shortcuts()
    assert shortcuts["app_next"]["shortcut"] == "F"
    assert shortcuts["app_undo"]["label"] == "undo"


def test_modifier_only_shortcut_is_valid_app_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe, "SHORTCUTS_ADD_FILE", str(tmp_path / "s.a.txt"))
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    (tmp_path / "s.txt").write_text(
        "app_force_draw <Ctrl> hold + drag\napp_fix_box <F> fix\n",
        encoding="utf-8",
    )
    app, user, errors = ybe.split_shortcuts(ybe.load_shortcuts())
    assert errors == []
    assert user == {}
    assert app["app_force_draw"]["shortcut"] == "Ctrl"
    assert "app_fix_box" in app
    assert "app_fix_box" in ybe.APP_ACTIONS
    assert "app_force_draw" in ybe.APP_ACTIONS


def test_split_shortcuts_partitions_and_reports_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    write_action(tmp_path, "Mine.yaml", "steps:\n  - echo hi\n")
    shortcuts = {
        "app_next": {"shortcut": "ArrowRight", "label": "next"},
        "Mine": {"shortcut": "M", "label": "run"},
        "Bogus": {"shortcut": "B", "label": "?"},
    }
    app, user, errors = ybe.split_shortcuts(shortcuts)
    assert set(app) == {"app_next"}
    assert set(user) == {"Mine"}
    assert len(errors) == 1 and "Bogus" in errors[0]


def test_split_shortcuts_rejects_hook_binding(clean_state):
    write_hook(clean_state, "on_after_save.yaml", "steps:\n  - echo x\n")
    shortcuts = {"on_after_save": {"shortcut": "H", "label": "hook"}}
    app, user, errors = ybe.split_shortcuts(shortcuts)
    assert app == {} and user == {}
    assert len(errors) == 1
    assert "event hook" in errors[0] and "on_after_save" in errors[0]


def test_recent_cap_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "RECENT_FILE", str(tmp_path / "r.json"))
    assert ybe._load_recent() == []
    for i in range(12):
        ybe._push_recent(f"/d/{i}.yaml")
    recents = ybe._load_recent()
    assert len(recents) <= ybe.MAX_RECENT
    assert recents[0] == "/d/11.yaml"  # newest first
    assert len(set(recents)) == len(recents)
    ybe._push_recent("/d/5.yaml")
    assert ybe._load_recent()[0] == "/d/5.yaml"


# --------------------------------------------------------------------------- #
# resuming the last dataset at startup
# --------------------------------------------------------------------------- #
def test_load_dataset_sets_state(clean_state, tmp_path):
    root = make_dataset(tmp_path, names=("fire", "smoke"))
    assert ybe._load_dataset(str(root / "data.yaml")) is True
    assert ybe.STATE["data_yaml"] == str(root / "data.yaml")
    assert [s["name"] for s in ybe.STATE["splits"]] == ["train", "val", "test"]
    assert ybe.STATE["images"]


def test_load_dataset_false_without_splits(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=())
    assert ybe._load_dataset(str(root / "data.yaml")) is False


def test_resume_last_dataset_opens_most_recent(clean_state, tmp_path):
    first = make_dataset(tmp_path / "one")
    second = make_dataset(tmp_path / "two")
    ybe._push_recent(str(first / "data.yaml"))
    ybe._push_recent(str(second / "data.yaml"))
    resumed = ybe._resume_last_dataset()
    assert resumed == str(second / "data.yaml")
    assert ybe.STATE["data_yaml"] == str(second / "data.yaml")


def test_resume_last_dataset_skips_missing_files(clean_state, tmp_path):
    good = make_dataset(tmp_path / "good")
    ybe._push_recent(str(good / "data.yaml"))
    ybe._push_recent(str(tmp_path / "gone" / "data.yaml"))
    assert ybe._resume_last_dataset() == str(good / "data.yaml")


def test_resume_last_dataset_none_clears_state(clean_state):
    ybe.STATE["data_yaml"] = "/stale/data.yaml"
    ybe.STATE["splits"] = [{"name": "train"}]
    ybe.STATE["images"] = [{"split": "train", "name": "a.jpg"}]
    assert ybe._resume_last_dataset() is None
    assert ybe.STATE["data_yaml"] is None
    assert ybe.STATE["splits"] == []
    assert ybe.STATE["images"] == []



# --------------------------------------------------------------------------- #
# dataset scanning
# --------------------------------------------------------------------------- #
def test_scan_splits_builds_splits(clean_state, tmp_path):
    root = make_dataset(tmp_path, names=("fire", "smoke"))
    clean_state_path = str(root / "data.yaml")
    ybe.STATE["data_yaml"] = clean_state_path
    splits = ybe.scan_splits()
    assert [s["name"] for s in splits] == ["train", "val", "test"]
    assert splits[0]["images_dir"].endswith("images/train")
    assert splits[0]["labels_dir"].endswith("labels/train")
    assert ybe.STATE["classes"] == ["fire", "smoke"]


def test_scan_splits_skips_missing_images_dir(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",))
    ybe.STATE["data_yaml"] = str(root / "data.yaml")
    splits = ybe.scan_splits()
    assert [s["name"] for s in splits] == ["train"]


def test_scan_splits_empty_without_data_yaml(clean_state):
    assert ybe.scan_splits() == []


def test_scan_images_sorted_and_filtered(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("b", "a"))
    ybe.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.STATE["splits"] = ybe.scan_splits()
    images = ybe.scan_images()
    assert [e["name"] for e in images] == ["a.jpg", "b.jpg"]
    assert all(e["split"] == "train" for e in images)


def test_read_classes_fallback_from_label_files(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",), names=())
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text("3 0.5 0.5 0.2 0.2\n",
                                                     encoding="utf-8")
    ybe.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.STATE["splits"] = ybe.scan_splits()
    ybe.STATE["images"] = ybe.scan_images()
    assert ybe.read_classes() == ["class_0", "class_1", "class_2", "class_3"]


# --------------------------------------------------------------------------- #
# routes: config / data / split
# --------------------------------------------------------------------------- #
def test_index_serves_page():
    client = ybe.app.test_client()
    html = client.get("/").data.decode()
    assert "id=\"canvas\"" in html
    assert "id=\"boxList\"" in html
    assert "id=\"shortcutBar\"" in html
    assert "id=\"hookStatusBar\"" in html
    assert "id=\"autoSaveSw\"" in html
    assert "id=\"filterSelect\"" in html


def test_api_config_defaults(clean_state):
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["data_yaml"] is None
    assert cfg["classes"] == ["class_0"]
    assert cfg["images"] == []
    assert cfg["readonly"] is False
    assert cfg["splits"] == []
    assert cfg["recent_data_yamls"] == []
    assert "shortcuts" in cfg and "action_shortcuts" in cfg
    assert cfg["actions"] == [] and cfg["hooks"] == []
    assert cfg["hook_errors"] == []
    assert cfg["debug"] is False


def test_api_config_reports_debug_flag(clean_state):
    ybe.STATE["debug"] = True
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["debug"] is True


def test_api_config_separates_hooks_from_actions(clean_state):
    write_action(clean_state, "Remove.yaml", "steps:\n  - echo hi\n")
    write_hook(clean_state, "on_after_save.yaml", "steps:\n  - echo saved\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["actions"] == ["Remove"]
    assert cfg["hooks"] == ["on_after_save"]
    assert cfg["hook_errors"] == []


def test_api_config_reports_hook_errors(clean_state):
    write_hook(clean_state, "on_nope.yaml", "steps:\n  - echo hi\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["hooks"] == []
    assert len(cfg["hook_errors"]) == 1 and "on_nope.yaml" in cfg["hook_errors"][0]


def test_api_data_requires_path(clean_state):
    resp = ybe.app.test_client().post("/api/data", json={})
    assert resp.status_code == 400
    assert "required" in resp.get_json()["error"]


def test_api_data_rejects_missing_file(clean_state, tmp_path):
    resp = ybe.app.test_client().post("/api/data", json={"data_yaml": str(tmp_path / "x.yaml")})
    assert resp.status_code == 400
    assert "not a file" in resp.get_json()["error"]


def test_api_data_loads_dataset(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    cfg = load_dataset(ybe.app.test_client(), root)
    assert cfg["dataset_path"] == str(root)
    assert cfg["classes"] == ["fire", "smoke"]
    assert len(cfg["images"]) == 6  # a.jpg + b.jpg across 3 splits
    assert cfg["active_split"] is None


def test_api_data_rejects_dataset_with_no_image_splits(clean_state, tmp_path):
    p = tmp_path / "data.yaml"
    p.write_text(f"path: {tmp_path}\nnc: 1\nnames: [fire]\n", encoding="utf-8")
    resp = ybe.app.test_client().post("/api/data", json={"data_yaml": str(p)})
    assert resp.status_code == 400
    assert "no train/val/test" in resp.get_json()["error"]


def test_api_split_set_and_clear(clean_state, tmp_path):
    client = ybe.app.test_client()
    root = make_dataset(tmp_path)
    load_dataset(client, root)

    resp = client.post("/api/split", json={"split": "train"})
    cfg = resp.get_json()
    assert cfg["ok"] and cfg["active_split"] == "train"
    assert {e["split"] for e in cfg["images"]} == {"train"}

    resp = client.post("/api/split", json={"split": None})
    assert resp.get_json()["active_split"] is None


def test_api_split_rejects_unknown(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/split", json={"split": "nope"})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# routes: image / labels
# --------------------------------------------------------------------------- #
def test_api_image_serves_bytes(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.get("/api/image/0")
    assert resp.status_code == 200
    assert resp.data[:2] == b"\xff\xd8"  # JPEG (files are .jpg)


def test_api_image_out_of_range_404(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/image/999").status_code == 404


def test_api_labels_get_empty_without_file(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/labels/0").get_json() == []


def test_api_labels_get_parses_existing(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text(
        "1 0.5 0.25 0.2 0.4\nbad line\n", encoding="utf-8"
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    boxes = client.get("/api/labels/0").get_json()
    assert boxes == [{"class": 1, "cx": 0.5, "cy": 0.25, "w": 0.2, "h": 0.4}]


def test_api_labels_post_writes_clamped(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/labels/0", json={"boxes": [
        {"class": 2, "cx": -1.0, "cy": 0.5, "w": 2.0, "h": 0.1},
        {"class": -3, "cx": 0.4, "cy": 0.4, "w": 0.2, "h": 0.2},
    ]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] and resp.get_json()["count"] == 2
    written = (root / "labels" / "train" / "a.txt").read_text().splitlines()
    assert written[0].startswith("2 0.000000 0.500000 1.000000 0.100000")
    assert written[1].startswith("0 0.400000 0.400000")


def test_api_labels_post_invalid_box(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/labels/0", json={"boxes": [{"class": "x", "cx": 0, "cy": 0, "w": 0, "h": 0}]})
    assert resp.status_code == 400


def test_api_labels_post_readonly_rejected(clean_state, tmp_path, monkeypatch):
    ybe.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    cfg = client.get("/api/config").get_json()
    assert cfg["readonly"] is True
    resp = client.post("/api/labels/0", json={"boxes": []})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# tags: paths / tags.yaml IO
# --------------------------------------------------------------------------- #
def test_tags_dir_replaces_images_segment():
    assert ybe._tags_dir_for("/d/images/train") == "/d/tags/train"


def test_tags_dir_fallback_sibling():
    assert ybe._tags_dir_for("/d/train") == "/d/tags/train"


def test_normalize_tags_dedupes_and_cleans():
    assert ybe._normalize_tags(["  fire ", "smoke", "fire", "", "  ", "a\nb", 7]) == [
        "fire",
        "smoke",
    ]


def test_read_tags_yaml_empty_without_dataset(clean_state, tmp_path):
    assert ybe.read_tags_yaml() == []


def test_read_tags_yaml_parses_block_and_inline(clean_state, tmp_path):
    (tmp_path / "data.yaml").write_text(f"nc: 1\nnames: [fire]\n", encoding="utf-8")
    ybe.STATE["data_yaml"] = str(tmp_path / "data.yaml")
    assert ybe.read_tags_yaml() == []
    (tmp_path / "tags.yaml").write_text("tags:\n  - fire\n  - smoke\n", encoding="utf-8")
    assert ybe.read_tags_yaml() == ["fire", "smoke"]
    (tmp_path / "tags.yaml").write_text("tags: [a, b] # inline\n", encoding="utf-8")
    assert ybe.read_tags_yaml() == ["a", "b"]


def test_save_tags_yaml_appends_key_when_missing(clean_state, tmp_path):
    (tmp_path / "data.yaml").write_text("nc: 1\nnames: [fire]\n", encoding="utf-8")
    ybe.STATE["data_yaml"] = str(tmp_path / "data.yaml")
    path = ybe.save_tags_yaml(["fire", "smoke"])
    assert path == str(tmp_path / "tags.yaml")
    assert ybe.read_tags_yaml() == ["fire", "smoke"]


def test_save_tags_yaml_preserves_other_content(clean_state, tmp_path):
    ybe.STATE["data_yaml"] = str(tmp_path / "data.yaml")
    (tmp_path / "tags.yaml").write_text(
        "version: 2\nnames:\n  - a\ntags:\n  - old\n", encoding="utf-8",
    )
    ybe.save_tags_yaml(["new", "fire"])
    text = (tmp_path / "tags.yaml").read_text()
    assert "version: 2" in text
    assert "names:" in text and "- a" in text
    assert "old" not in text
    assert ybe.read_tags_yaml() == ["new", "fire"]


def test_api_tags_yaml_get_and_post(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/tags.yaml").get_json() == {"tags": []}

    resp = client.post("/api/tags.yaml", json={"tags": ["fire", "smoke", "fire"]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] and resp.get_json()["tags"] == ["fire", "smoke"]
    assert client.get("/api/tags.yaml").get_json() == {"tags": ["fire", "smoke"]}


def test_api_tags_yaml_post_requires_dataset(clean_state, tmp_path):
    resp = ybe.app.test_client().post("/api/tags.yaml", json={"tags": ["fire"]})
    assert resp.status_code == 400


def test_api_tags_yaml_post_readonly_rejected(clean_state, tmp_path):
    ybe.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/tags.yaml", json={"tags": ["fire"]})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# tags: per-image routes
# --------------------------------------------------------------------------- #
def test_api_tags_get_empty_without_file(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/tags/0").get_json() == {"tags": []}


def test_api_tags_get_parses_existing(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    (root / "tags" / "train").mkdir(parents=True)
    (root / "tags" / "train" / "a.txt").write_text("fire\nsmoke\n\n", encoding="utf-8")
    client = ybe.app.test_client()
    load_dataset(client, root)
    assert client.get("/api/tags/0").get_json() == {"tags": ["fire", "smoke"]}


def test_api_tags_post_writes_deduped(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/tags/0", json={"tags": ["fire", "", "smoke", "fire"]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] and resp.get_json()["count"] == 2
    written = (root / "tags" / "train" / "a.txt").read_text().splitlines()
    assert written == ["fire", "smoke"]


def test_api_tags_post_readonly_rejected(clean_state, tmp_path):
    ybe.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.post("/api/tags/0", json={"tags": ["fire"]}).status_code == 403


def test_api_tags_out_of_range_404(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/tags/999").status_code == 404


# --------------------------------------------------------------------------- #
# routes: user actions
# --------------------------------------------------------------------------- #
def test_api_action_run_unknown_action(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Nope", "idx": 0})
    assert resp.status_code == 400


def test_api_action_run_invalid_idx(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "X", "idx": "nope"})
    assert resp.status_code == 400


def test_api_action_run_success(clean_state, tmp_path):
    write_action(tmp_path, "Echo.yaml", "steps:\n  - echo {IMAGE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Echo", "idx": 0})
    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert payload["command"].startswith("echo ")
    assert payload["stdout"].strip().endswith("images/train/a.jpg")


def test_api_action_run_failure_surfaces_exit_code(clean_state, tmp_path):
    write_action(tmp_path, "Fail.yaml", "steps:\n  - false\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Fail", "idx": 0}).get_json()
    assert payload["ok"] is False
    assert payload["exit_code"] == 1


def test_api_action_run_timeout(clean_state, tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTION_TIMEOUT", 0.2)
    write_action(tmp_path, "Slow.yaml", "steps:\n  - sleep 5\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Slow", "idx": 0})
    assert resp.status_code == 500
    assert "timed out" in resp.get_json()["error"]


def test_api_action_run_without_after_success_omits_it(clean_state, tmp_path):
    write_action(tmp_path, "Echo.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Echo", "idx": 0}).get_json()
    assert payload["ok"] is True
    assert "after_success" not in payload


def test_api_action_run_steps_success(clean_state, tmp_path):
    write_action(
        tmp_path,
        "EchoMany.yaml",
        "steps:\n  - echo one\n  - echo two\n"
        "after_success:\n  - app_refresh_images_list\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "EchoMany", "idx": 0}).get_json()
    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert "one" in payload["stdout"] and "two" in payload["stdout"]
    assert payload["after_success"] == ["app_refresh_images_list"]


def test_api_action_run_stops_on_first_failure(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Bad.yaml",
        "steps:\n  - echo ok\n  - false\n  - echo never\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Bad", "idx": 0}).get_json()
    assert payload["ok"] is False
    assert payload["exit_code"] == 1
    assert "ok" in payload["stdout"]
    assert "never" not in payload["stdout"]
    assert "after_success" not in payload


def test_api_action_run_substitutes_dataset_path_and_image_index(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_action(
        tmp_path,
        "Info.yaml",
        "steps:\n  - echo {DATASET_PATH}\n  - echo {IMAGE_INDEX}\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    payload = client.post("/api/actions/run", json={"action": "Info", "idx": 1}).get_json()
    assert payload["ok"] is True
    assert str(root) in payload["stdout"]
    assert payload["stdout"].splitlines()[-1].strip() == "2"  # 1-based


def test_api_action_run_substitutes_data_yaml_path(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_action(tmp_path, "Yaml.yaml", "steps:\n  - echo {DATA_YAML_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    payload = client.post("/api/actions/run", json={"action": "Yaml", "idx": 0}).get_json()
    assert payload["ok"] is True
    assert str(root / "data.yaml") in payload["stdout"]


def test_api_action_run_can_run_a_hook_by_name(clean_state, tmp_path):
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "steps:\n  - echo hooked\n"
        "after_success:\n  - app_refresh_image\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "idx": 0}
    ).get_json()
    assert payload["ok"] is True
    assert "hooked" in payload["stdout"]
    assert payload["after_success"] == ["app_refresh_image"]


def test_api_action_run_substitutes_app_dir(clean_state, tmp_path):
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo {APP_DIR}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "idx": 0}
    ).get_json()
    assert payload["ok"] is True
    assert ybe.BASE_DIR in payload["stdout"]


def test_api_action_run_sets_cwd_to_app_dir(clean_state, tmp_path):
    # scripts/ is a sibling of app.py; steps must resolve it regardless of the
    # directory the server was started from
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - pwd\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "idx": 0}
    ).get_json()
    assert payload["ok"] is True
    assert ybe.BASE_DIR in payload["stdout"]


def test_api_action_run_pipe_path_is_a_file(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Pipe.yaml",
        "steps:\n  - echo hello > {PIPE_PATH}\n  - cat {PIPE_PATH}\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Pipe", "idx": 0}).get_json()
    assert payload["ok"] is True
    assert "{PIPE_PATH}" not in payload["command"]
    pipe = payload["pipe_path"]
    assert ybe.is_pipe_path(pipe)
    assert Path(pipe).is_file()
    assert "hello" in payload["stdout"]
    # the server keeps the file: the client deletes it when the run ends
    assert Path(pipe).is_file()


def test_api_action_run_reuses_forwarded_pipe_path(clean_state, tmp_path):
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo one > {PIPE_PATH}\n")
    write_action(tmp_path, "Read.yaml", "steps:\n  - cat {PIPE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    first = client.post("/api/actions/run", json={"action": "Write", "idx": 0}).get_json()
    pipe = first["pipe_path"]
    second = client.post(
        "/api/actions/run", json={"action": "Read", "idx": 0, "pipe_path": pipe}
    ).get_json()
    assert second["ok"] is True
    assert second["pipe_path"] == pipe
    assert "one" in second["stdout"]


def test_api_action_run_ignores_foreign_pipe_path(clean_state, tmp_path):
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo x > {PIPE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run",
        json={"action": "Write", "idx": 0, "pipe_path": "/etc/passwd"},
    ).get_json()
    assert payload["ok"] is True
    assert payload["pipe_path"] != "/etc/passwd"
    assert ybe.is_pipe_path(payload["pipe_path"])


def test_pipe_cleanup_removes_file(clean_state, tmp_path):
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo x > {PIPE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    pipe = client.post(
        "/api/actions/run", json={"action": "Write", "idx": 0}
    ).get_json()["pipe_path"]
    assert Path(pipe).is_file()
    resp = client.post("/api/actions/pipe/cleanup", json={"pipe_path": pipe})
    assert resp.get_json() == {"ok": True, "removed": True}
    assert not Path(pipe).exists()


def test_pipe_cleanup_keep_pipe_keeps_file(clean_state, tmp_path):
    ybe.STATE["keep_pipe"] = True
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo x > {PIPE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    pipe = client.post(
        "/api/actions/run", json={"action": "Write", "idx": 0}
    ).get_json()["pipe_path"]
    resp = client.post("/api/actions/pipe/cleanup", json={"pipe_path": pipe})
    assert resp.get_json() == {"ok": True, "kept": True}
    assert Path(pipe).is_file()


def test_pipe_cleanup_ignores_foreign_path(clean_state, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/pipe/cleanup", json={"pipe_path": str(victim)})
    assert resp.get_json() == {"ok": True, "removed": False}
    assert victim.read_text(encoding="utf-8") == "keep me"


# --------------------------------------------------------------------------- #
# routes: image list rescan
# --------------------------------------------------------------------------- #
def test_api_images_rescan_removes_deleted_image(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    assert len(client.get("/api/config").get_json()["images"]) == 2
    (root / "images" / "train" / "b.jpg").unlink()
    data = client.post("/api/images/rescan").get_json()
    assert data["ok"] is True
    assert [e["name"] for e in data["images"]] == ["a.jpg"]
    assert [e["name"] for e in client.get("/api/config").get_json()["images"]] == ["a.jpg"]


def test_api_images_rescan_resets_empty_active_split(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    client = ybe.app.test_client()
    load_dataset(client, root)
    assert client.post("/api/split", json={"split": "train"}).get_json()["ok"] is True
    (root / "images" / "train" / "a.jpg").unlink()
    data = client.post("/api/images/rescan").get_json()
    assert data["active_split"] is None
    assert data["images"] == []


def test_api_image_no_store_header(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.get("/api/image/0")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"


# --------------------------------------------------------------------------- #
# filters/ (script-based image-list filters)
# --------------------------------------------------------------------------- #
def test_filter_name_strips_py_and_override_suffix():
    assert ybe._filter_name("/d/Odd.py") == "Odd"
    assert ybe._filter_name("/d/Odd.a.py") == "Odd"


def test_load_filters_one_script_per_filter(clean_state):
    write_filter(clean_state, "Odd.py", "print('train/a.jpg')\n")
    write_filter(clean_state, "Even.py", "# nothing\n")
    assert sorted(ybe.load_filters()) == ["Even", "Odd"]


def test_load_filters_user_override_wins(clean_state):
    write_filter(clean_state, "Odd.py", "print('repo')\n")
    write_filter(clean_state, "Odd.a.py", "print('user')\n")
    assert ybe.load_filters()["Odd"].endswith("Odd.a.py")


def test_load_filters_ignores_non_py(clean_state):
    (clean_state / "filters").mkdir()
    (clean_state / "filters" / "notes.txt").write_text("x", encoding="utf-8")
    assert ybe.load_filters() == {}


def test_load_filters_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "FILTERS_DIR", str(tmp_path / "nope"))
    assert ybe.load_filters() == {}


def test_parse_filter_output_keeps_known_dedupes_and_order(clean_state):
    ybe.STATE["images"] = [
        {"split": "train", "name": "a.jpg"},
        {"split": "train", "name": "b.jpg"},
        {"split": "val", "name": "c.jpg"},
    ]
    text = "train/b.jpg\nval/c.jpg\ntrain/b.jpg\n\nunknown/x.jpg\ntrain/a.jpg\n"
    entries, skipped = ybe._parse_filter_output(text)
    assert entries == [
        {"split": "train", "name": "b.jpg"},
        {"split": "val", "name": "c.jpg"},
        {"split": "train", "name": "a.jpg"},
    ]
    assert skipped == 1


def test_parse_filter_output_counts_malformed_lines(clean_state):
    ybe.STATE["images"] = []
    entries, skipped = ybe._parse_filter_output("no-slash-here\n")
    assert entries == [] and skipped == 1


def test_run_filter_passes_data_yaml_and_split(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    ybe.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.STATE["splits"] = ybe.scan_splits()
    ybe.STATE["images"] = ybe.scan_images()
    out = clean_state / "args.txt"
    write_filter(
        clean_state,
        "Args.py",
        f"import sys\nopen({str(out)!r}, 'w').write('|'.join(sys.argv[1:]))\n",
    )
    result = ybe.run_filter("Args", "train")
    assert result["ok"] is True
    assert out.read_text(encoding="utf-8") == f"{root / 'data.yaml'}|train"


def test_run_filter_empty_split_for_all_splits(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    ybe.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.STATE["splits"] = ybe.scan_splits()
    ybe.STATE["images"] = ybe.scan_images()
    out = clean_state / "args.txt"
    write_filter(
        clean_state,
        "Args.py",
        f"import sys\nopen({str(out)!r}, 'w').write('|'.join(sys.argv[1:]))\n",
    )
    assert ybe.run_filter("Args", "")["ok"] is True
    assert out.read_text(encoding="utf-8") == f"{root / 'data.yaml'}|"


def test_run_filter_unknown(clean_state):
    assert ybe.run_filter("Nope", "train")["ok"] is False


def test_run_filter_nonzero_exit_reports_stderr(clean_state):
    write_filter(
        clean_state, "Boom.py", "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n"
    )
    result = ybe.run_filter("Boom", "train")
    assert result["ok"] is False and "boom" in result["error"]


def test_run_filter_timeout(clean_state, monkeypatch):
    monkeypatch.setattr(ybe, "FILTER_TIMEOUT", 0.2)
    write_filter(clean_state, "Slow.py", "import time\ntime.sleep(5)\n")
    result = ybe.run_filter("Slow", "train")
    assert result["ok"] is False and "timed out" in result["error"]


def test_api_config_reports_filters(clean_state):
    write_filter(clean_state, "Odd.py", "# nothing\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["filters"] == ["Odd"]
    assert cfg["active_filter"] is None


def test_api_filter_set_and_clear(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", "print('train/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)

    cfg = client.post("/api/filter", json={"filter": "OnlyA"}).get_json()
    assert cfg["ok"] is True and cfg["active_filter"] == "OnlyA"
    assert [e["name"] for e in cfg["images"]] == ["a.jpg"]

    cfg = client.post("/api/filter", json={"filter": None}).get_json()
    assert cfg["active_filter"] is None
    assert len(cfg["images"]) == 2


def test_api_filter_requires_dataset(clean_state):
    resp = ybe.app.test_client().post("/api/filter", json={"filter": "X"})
    assert resp.status_code == 400
    assert "no dataset" in resp.get_json()["error"]


def test_api_filter_unknown(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/filter", json={"filter": "Nope"})
    assert resp.status_code == 400
    assert "unknown filter" in resp.get_json()["error"]


def test_api_filter_can_span_splits_when_all(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    write_filter(clean_state, "All.py", "print('train/a.jpg')\nprint('val/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filter": "All"}).get_json()
    assert [(e["split"], e["name"]) for e in cfg["images"]] == [
        ("train", "a.jpg"),
        ("val", "a.jpg"),
    ]


def test_api_filter_reports_skipped_lines(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(
        clean_state, "Sloppy.py", "print('train/a.jpg')\nprint('nope/missing.jpg')\n"
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filter": "Sloppy"}).get_json()
    assert cfg["active_filter"] == "Sloppy"
    assert "ignored" in (cfg["filter_error"] or "")


def test_api_filter_allowed_in_readonly(clean_state, tmp_path):
    ybe.STATE["readonly"] = True
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "Keep.py", "print('train/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/filter", json={"filter": "Keep"})
    assert resp.status_code == 200 and resp.get_json()["active_filter"] == "Keep"


def test_api_data_clears_active_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "Keep.py", "print('train/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filter": "Keep"})
    assert ybe.STATE["active_filter"] == "Keep"
    load_dataset(client, root)
    assert ybe.STATE["active_filter"] is None


def test_api_split_reruns_active_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", "import sys\nprint(sys.argv[2] + '/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filter": "OnlyA"})
    cfg = client.post("/api/split", json={"split": "val"}).get_json()
    assert cfg["ok"] is True and cfg["active_split"] == "val"
    assert cfg["images"] == [{"split": "val", "name": "a.jpg"}]


def test_api_split_filter_failure_keeps_state(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    write_filter(
        clean_state,
        "Pick.py",
        "import sys\n"
        "if sys.argv[2] == 'val':\n"
        "    sys.exit(1)\n"
        "print('train/a.jpg')\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filter": "Pick"})
    resp = client.post("/api/split", json={"split": "val"})
    assert resp.status_code == 400
    assert ybe.STATE["active_split"] is None  # unchanged
    assert ybe.STATE["active_filter"] == "Pick"


def test_api_images_rescan_reruns_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", "print('train/a.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filter": "OnlyA"})
    (root / "images" / "train" / "a.jpg").unlink()
    data = client.post("/api/images/rescan").get_json()
    assert data["active_filter"] == "OnlyA"
    assert data["images"] == []


def test_api_image_uses_filtered_index(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyB.py", "print('train/b.jpg')\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filter": "OnlyB"}).get_json()
    assert [e["name"] for e in cfg["images"]] == ["b.jpg"]
    assert client.get("/api/image/0").status_code == 200
    assert client.get("/api/image/1").status_code == 404