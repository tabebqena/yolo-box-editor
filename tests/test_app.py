"""Test suite for the yolo-box-editor Flask app (app.py).

Run from the repo root; the app is a single module with no package layout, so
the repo root is added to sys.path here.

The app's own support files (the actions/ folder / shortcuts.txt /
.recent_data_yamls.json) are NEVER touched: fixtures monkeypatch every file
constant to disposable paths under tmp_path, and STATE is reset per test.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import app as ybe

# --------------------------------------------------------------------------- #
# user home resolution
# --------------------------------------------------------------------------- #
def test_default_home_is_parent_of_app(monkeypatch):
    monkeypatch.delenv("YBX_HOME", raising=False)
    assert ybe._resolve_home() == os.path.dirname(ybe.BASE_DIR)


def test_home_env_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("YBX_HOME", str(tmp_path / "h"))
    assert ybe._resolve_home() == str(tmp_path / "h")


def test_configure_home_repoints_user_dirs(clean_state, tmp_path):
    target = tmp_path / "elsewhere"
    ybe.configure_home(str(target))
    assert ybe.YBX_HOME == str(target)
    assert ybe.USER_ACTIONS_DIR == str(target / "actions")
    assert ybe.USER_SCRIPT_DIR == str(target / "scripts")
    assert ybe.RECENT_FILE == str(target / ".recent_data_yamls.json")
    assert ybe.SETTINGS_FILE == str(target / ".settings.json")


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
DEFAULT_STATE = {
    "data_yaml": None,
    "dataset_path": None,
    "splits": [],
    "images": [],
    "active_split": None,
    "active_filters": [],
    "filter_images": None,
    "filter_error": None,
    "classes": [],
    "tags_dir": None,
    "readonly": False,
    "debug": False,
    "keep_pipe": False,
    "keep_filter_pipes": False,
    "no_update_check": False,
}


def _img(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (10, 20, 30)).save(path)


@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """Reset STATE and redirect file constants away from the repo.

    The fixtures write user files under `<tmp_path>/actions` etc. (the USER_*
    dirs, read last); the shipped `app-actions` etc. stay empty here so only the
    test's own files are loaded.
    """
    monkeypatch.setattr(ybe, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe, "RECENT_FILE", str(tmp_path / "recent.json"))
    monkeypatch.setattr(ybe, "VIEW_FILE", str(tmp_path / "view.json"))
    monkeypatch.setattr(ybe, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(ybe, "UPDATE_CHECK_FILE", str(tmp_path / "update.json"))
    monkeypatch.setattr(ybe, "VERSION_FILE", str(tmp_path / "VERSION"))
    monkeypatch.setattr(ybe, "CHANGES_FILE", str(tmp_path / "CHANGES"))
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "app-actions"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "app-hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "FILTERS_DIR", str(tmp_path / "app-filters"))
    monkeypatch.setattr(ybe, "USER_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe, "APP_SCRIPT_DIR", str(tmp_path / "app-scripts"))
    monkeypatch.setattr(ybe, "USER_SCRIPT_DIR", str(tmp_path / "scripts"))
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "app-shortcuts.txt"))
    monkeypatch.setattr(ybe, "USER_SHORTCUTS_FILE", str(tmp_path / "shortcuts.txt"))
    monkeypatch.setattr(ybe, "PIPE_DIR", str(tmp_path / "pipes"))
    monkeypatch.setattr(ybe, "FILTER_PIPES_DIR", str(tmp_path / "filter-pipes"))
    ybe.STATE.clear()
    ybe.STATE.update(DEFAULT_STATE)
    ybe.EXECUTIONS.clear()
    ybe.CLIENTS.clear()
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


def write_action(root, fname, body, subdir="actions"):
    """Write one action file into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def write_hook(root, fname, body, subdir="hooks"):
    """Write one hook file into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def write_filter(root, fname, body, subdir="filters"):
    """Write one filter script into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def load_into_state(root):
    """Activate `root`'s dataset in STATE without going through a client."""
    ybe.STATE["data_yaml"] = str(Path(root) / "data.yaml")
    ybe.STATE["splits"] = ybe.scan_splits()
    ybe.STATE["images"] = ybe.scan_images()


# Copies the input pipe to the output pipe unchanged (the identity filter).
FILTER_COPY = "import sys\nopen(sys.argv[4], 'w').write(open(sys.argv[3]).read())\n"


def filter_selecting(*names):
    """A filter that keeps only input paths whose file name is in `names`."""
    wanted = ", ".join(repr(n) for n in names)
    return (
        "import os, sys\n"
        "paths = [l.strip() for l in open(sys.argv[3], encoding='utf-8') if l.strip()]\n"
        f"wanted = {{{wanted}}}\n"
        "with open(sys.argv[4], 'w', encoding='utf-8') as out:\n"
        "    for p in paths:\n"
        "        if os.path.basename(p) in wanted:\n"
        "            out.write(p + '\\n')\n"
    )


def filter_recording_input(log_path):
    """A filter that copies its input to `log_path` as well as to the output."""
    return (
        "import sys\n"
        f"text = open(sys.argv[3], encoding='utf-8').read()\n"
        f"open({str(log_path)!r}, 'w', encoding='utf-8').write(text)\n"
        "open(sys.argv[4], 'w', encoding='utf-8').write(text)\n"
    )



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
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
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
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "whatever.yaml", "name: Custom\nsteps:\n  - echo hi\n")
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert "Custom" in actions and "whatever" not in actions


def test_load_actions_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "Shared.yaml", "steps:\n  - echo repo\n")
    write_action(
        tmp_path, "Shared.yaml", "steps:\n  - echo user\n", subdir="user-actions"
    )
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Shared"]["steps"] == ["echo user"]


def test_load_actions_override_targets_name_key(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "Shared.yaml", "steps:\n  - echo repo\n")
    write_action(
        tmp_path,
        "mine.yaml",
        "name: Shared\nsteps:\n  - echo user\n",
        subdir="user-actions",
    )
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Shared"]["steps"] == ["echo user"]


def test_load_actions_ignores_empty_entries_and_non_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "Empty.yaml", "name: Empty\nafter_success: []\n")
    write_action(tmp_path, "notes.txt", "steps:\n  - echo hi\n")
    assert ybe.load_actions() == []


def test_load_actions_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "nope-user"))
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
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo saved\n")
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]
    assert hooks[0]["event"] == "after_save"
    assert hooks[0]["steps"] == ["echo saved"]


def test_load_hooks_event_name_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(
        tmp_path, "whatever.yaml", "event_name: after_save\nsteps:\n  - echo hi\n"
    )
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]


def test_load_hooks_known_filename_wins_over_event_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "event_name: before_save\nsteps:\n  - echo hi\n",
    )
    hooks, _ = ybe.load_hooks()
    assert hooks[0]["event"] == "after_save"


def test_load_hooks_inactive_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "active: false\nsteps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_unknown_event_with_steps_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_nope.yaml", "steps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == []
    assert len(errors) == 1 and "on_nope.yaml" in errors[0]


def test_load_hooks_empty_template_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "example.yaml", "# comments only, no steps\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo repo\n")
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "steps:\n  - echo user\n",
        subdir="user-hooks",
    )
    hooks, _ = ybe.load_hooks()
    assert [h["steps"] for h in hooks] == [["echo user"]]


def test_load_hooks_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "nope-user"))
    assert ybe.load_hooks() == ([], [])


def test_load_shortcuts_merges_and_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe, "USER_SHORTCUTS_FILE", str(tmp_path / "s-user.txt"))
    (tmp_path / "s.txt").write_text("app_next <D> repo\napp_undo <Z> undo\n",
                                    encoding="utf-8")
    (tmp_path / "s-user.txt").write_text("app_next <F> user\n", encoding="utf-8")
    shortcuts = ybe.load_shortcuts()
    assert shortcuts["app_next"]["shortcut"] == "F"
    assert shortcuts["app_undo"]["label"] == "undo"


def test_modifier_only_shortcut_is_valid_app_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe, "USER_SHORTCUTS_FILE", str(tmp_path / "s-user.txt"))
    monkeypatch.setattr(ybe, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
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
    monkeypatch.setattr(ybe, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    monkeypatch.setattr(ybe, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
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
    assert "id=\"toasts\"" in html
    assert "id=\"settingsModal\"" in html
    assert "id=\"settingsBtn\"" in html
    assert "id=\"shortcutItems\"" in html
    assert "id=\"autoSaveSw\"" in html
    assert "id=\"filterPanelBody\"" in html
    assert "id=\"filterPanelApply\"" in html
    assert "id=\"tagFloat\"" in html
    assert "id=\"boxFloat\"" in html
    assert "id=\"navFloat\"" in html
    assert "id=\"saveFloat\"" in html
    assert "id=\"actionsFloat\"" in html
    assert "id=\"dockSide\"" in html
    assert "id=\"dockBottom\"" in html
    assert "id=\"panelSideSel\"" in html
    assert "id=\"tagsDockSel\"" in html
    assert "id=\"boxesDockSel\"" in html
    assert "id=\"actionsDockSel\"" in html
    assert "id=\"navDockSel\"" in html
    assert "id=\"saveDockSel\"" in html
    assert "id=\"tagsVisibleSw\"" in html
    assert "id=\"boxesVisibleSw\"" in html
    assert "id=\"actionsVisibleSw\"" in html
    assert "id=\"navVisibleSw\"" in html
    assert "id=\"saveVisibleSw\"" in html
    assert "id=\"tipModal\"" in html
    assert "id=\"tipText\"" in html
    assert "id=\"tipsSw\"" in html


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


def test_api_config_includes_tips(clean_state):
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert isinstance(cfg["tips"], list) and cfg["tips"]
    assert all(isinstance(t, str) and t for t in cfg["tips"])


def test_api_config_includes_settings(clean_state):
    Path(ybe.SETTINGS_FILE).write_text(
        json.dumps({"autoSave": "1", "ybe_panel_side": "left"}), encoding="utf-8"
    )
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["settings"] == {"autoSave": "1", "ybe_panel_side": "left"}


def test_api_settings_defaults_empty(clean_state):
    data = ybe.app.test_client().get("/api/settings").get_json()
    assert data["ok"] is True and data["settings"] == {}


def test_api_settings_post_merges_and_deletes(clean_state):
    client = ybe.app.test_client()
    data = client.post(
        "/api/settings", json={"settings": {"autoSave": "1", "ybe_show_boxes": "0"}}
    ).get_json()
    assert data["settings"] == {"autoSave": "1", "ybe_show_boxes": "0"}

    # a partial update leaves the other keys alone
    data = client.post("/api/settings", json={"settings": {"ybe_panel_side": "left"}}).get_json()
    assert data["settings"] == {
        "autoSave": "1", "ybe_show_boxes": "0", "ybe_panel_side": "left",
    }

    # null removes a key
    data = client.post("/api/settings", json={"settings": {"autoSave": None}}).get_json()
    assert "autoSave" not in data["settings"]
    assert client.get("/api/settings").get_json()["settings"] == data["settings"]


def test_api_settings_rejects_non_object(clean_state):
    resp = ybe.app.test_client().post("/api/settings", json={"settings": ["nope"]})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


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
    resp = client.get("/api/image?key=train/a.jpg")
    assert resp.status_code == 200
    assert resp.data[:2] == b"\xff\xd8"  # JPEG (files are .jpg)


def test_api_image_out_of_range_404(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/image?key=train/nope.jpg").status_code == 404


def test_api_labels_get_empty_without_file(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/labels?key=train/a.jpg").get_json() == []


def test_api_labels_get_parses_existing(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text(
        "1 0.5 0.25 0.2 0.4\nbad line\n", encoding="utf-8"
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    boxes = client.get("/api/labels?key=train/a.jpg").get_json()
    assert boxes == [{"class": 1, "cx": 0.5, "cy": 0.25, "w": 0.2, "h": 0.4}]


def test_api_labels_post_writes_clamped(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/labels?key=train/a.jpg", json={"boxes": [
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
    resp = client.post("/api/labels?key=train/a.jpg", json={"boxes": [{"class": "x", "cx": 0, "cy": 0, "w": 0, "h": 0}]})
    assert resp.status_code == 400


def test_api_labels_post_readonly_rejected(clean_state, tmp_path, monkeypatch):
    ybe.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    cfg = client.get("/api/config").get_json()
    assert cfg["readonly"] is True
    resp = client.post("/api/labels?key=train/a.jpg", json={"boxes": []})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# tags: paths / tags.yaml IO
# --------------------------------------------------------------------------- #
def test_tags_dir_replaces_images_segment(clean_state):
    assert ybe._tags_dir_for("/d/images/train") == "/d/tags/train"


def test_tags_dir_fallback_sibling(clean_state):
    assert ybe._tags_dir_for("/d/train") == "/d/tags/train"


def test_tags_dir_override_uses_split_subfolder(clean_state):
    ybe.STATE["tags_dir"] = "/custom/tags"
    assert ybe._tags_dir_for("/d/images/train", "train") == "/custom/tags/train"


def test_api_tags_dir_sets_and_clears(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    custom = tmp_path / "mytags"
    custom.mkdir()
    client = ybe.app.test_client()
    load_dataset(client, root)

    resp = client.post("/api/tags-dir", json={"tags_dir": str(custom)})
    assert resp.status_code == 200
    assert resp.get_json()["tags_dir"] == str(custom)
    assert ybe.STATE["splits"][0]["tags_dir"] == str(custom / "train")

    resp = client.post("/api/tags-dir", json={"tags_dir": ""})
    assert resp.status_code == 200
    assert resp.get_json()["tags_dir"] is None
    assert ybe.STATE["splits"][0]["tags_dir"] == str(root / "tags" / "train")


def test_api_tags_dir_rejects_missing_folder(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/tags-dir", json={"tags_dir": str(tmp_path / "nope")})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_tags_dir_persists_in_view_state(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    custom = tmp_path / "mytags"
    custom.mkdir()
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/tags-dir", json={"tags_dir": str(custom)})

    # reloading the dataset re-applies the saved folder
    ybe.STATE["tags_dir"] = None
    load_dataset(client, root)
    assert ybe.STATE["tags_dir"] == str(custom)


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
    assert client.get("/api/tags?key=train/a.jpg").get_json() == {"tags": []}


def test_api_tags_get_parses_existing(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    (root / "tags" / "train").mkdir(parents=True)
    (root / "tags" / "train" / "a.txt").write_text("fire\nsmoke\n\n", encoding="utf-8")
    client = ybe.app.test_client()
    load_dataset(client, root)
    assert client.get("/api/tags?key=train/a.jpg").get_json() == {"tags": ["fire", "smoke"]}


def test_api_tags_post_writes_deduped(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/tags?key=train/a.jpg", json={"tags": ["fire", "", "smoke", "fire"]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] and resp.get_json()["count"] == 2
    written = (root / "tags" / "train" / "a.txt").read_text().splitlines()
    assert written == ["fire", "smoke"]


def test_api_tags_post_readonly_rejected(clean_state, tmp_path):
    ybe.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.post("/api/tags?key=train/a.jpg", json={"tags": ["fire"]}).status_code == 403


def test_api_tags_out_of_range_404(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/tags?key=train/nope.jpg").status_code == 404


# --------------------------------------------------------------------------- #
# routes: user actions
# --------------------------------------------------------------------------- #
def test_api_action_run_unknown_action(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Nope", "target": "train/a.jpg"})
    assert resp.status_code == 400


def test_api_action_run_requires_a_known_target(clean_state, tmp_path):
    write_action(tmp_path, "Echo.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    # no target at all
    assert client.post("/api/actions/run", json={"action": "Echo"}).status_code == 400
    # a target that is not in the current list
    resp = client.post("/api/actions/run", json={"action": "Echo", "target": "train/zzz.jpg"})
    assert resp.status_code == 400
    assert "not in the current list" in resp.get_json()["error"]


def test_api_action_run_targets_named_image_not_position(clean_state, tmp_path):
    # the client names the image it is showing; the server must act on that file
    # even when its own list order/position differs (the bug that archived the
    # wrong image when the client and server lists diverged).
    write_action(tmp_path, "Info.yaml", "steps:\n  - echo {IMAGE_PATH}\n")
    client = ybe.app.test_client()
    root = make_dataset(tmp_path)
    load_dataset(client, root)
    # server list order is train/a, train/b, ...; ask for the *last* one by name
    payload = client.post(
        "/api/actions/run", json={"action": "Info", "target": "test/b.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert payload["stdout"].strip().endswith("images/test/b.jpg")


def test_api_action_run_success(clean_state, tmp_path):
    write_action(tmp_path, "Echo.yaml", "steps:\n  - echo {IMAGE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Echo", "target": "train/a.jpg"})
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
    payload = client.post("/api/actions/run", json={"action": "Fail", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is False
    assert payload["exit_code"] == 1


def test_api_action_run_timeout(clean_state, tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "ACTION_TIMEOUT", 0.2)
    write_action(tmp_path, "Slow.yaml", "steps:\n  - sleep 5\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"action": "Slow", "target": "train/a.jpg"})
    assert resp.status_code == 500
    assert "timed out" in resp.get_json()["error"]


def test_api_action_run_without_after_success_omits_it(clean_state, tmp_path):
    write_action(tmp_path, "Echo.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Echo", "target": "train/a.jpg"}).get_json()
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
    payload = client.post("/api/actions/run", json={"action": "EchoMany", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert "one" in payload["stdout"] and "two" in payload["stdout"]
    # the app action pauses the server-side chain and is handed to the client
    assert payload["client_action"] == "app_refresh_images_list"
    assert payload["uid"]


def test_api_action_run_stops_on_first_failure(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Bad.yaml",
        "steps:\n  - echo ok\n  - false\n  - echo never\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Bad", "target": "train/a.jpg"}).get_json()
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
    payload = client.post("/api/actions/run", json={"action": "Info", "target": "train/b.jpg"}).get_json()
    assert payload["ok"] is True
    assert str(root) in payload["stdout"]
    assert payload["stdout"].splitlines()[-1].strip() == "2"  # 1-based


def test_api_action_run_substitutes_data_yaml_path(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_action(tmp_path, "Yaml.yaml", "steps:\n  - echo {DATA_YAML_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    payload = client.post("/api/actions/run", json={"action": "Yaml", "target": "train/a.jpg"}).get_json()
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
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert "hooked" in payload["stdout"]
    assert payload["client_action"] == "app_refresh_image"


def test_api_action_run_substitutes_app_dir(clean_state, tmp_path):
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo {APP_DIR}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert ybe.BASE_DIR in payload["stdout"]


def test_api_action_run_sets_cwd_to_home(clean_state, tmp_path):
    # every run uses the user root as cwd; steps reach shipped files via {APP_DIR}
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - pwd\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert str(clean_state) in payload["stdout"]
    assert payload["cwd"] == str(clean_state)


def test_api_action_run_substitutes_home_and_script_dirs(clean_state, tmp_path):
    # script dirs are exposed explicitly as placeholders and as YBE_* env vars,
    # and are also reachable relatively (cwd is the home)
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "steps:\n"
        "  - pwd\n"
        "  - echo {HOME_DIR}\n"
        "  - echo {USER_SCRIPT_DIR}\n"
        "  - echo {APP_SCRIPT_DIR}\n"
        "  - echo $YBE_USER_SCRIPT_DIR\n"
        "  - echo $YBE_APP_SCRIPT_DIR\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert ybe.YBX_HOME in payload["stdout"]
    assert ybe.USER_SCRIPT_DIR in payload["stdout"]
    assert ybe.APP_SCRIPT_DIR in payload["stdout"]


def test_run_command_logs_cwd(clean_state, capsys):
    state = {"stdout": [], "stderr": [], "commands": [], "exit_code": 0}
    ybe._run_command(state, "true")
    assert f"cwd={ybe.YBX_HOME}" in capsys.readouterr().err


def test_api_action_run_pipe_path_is_deleted_when_done(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Pipe.yaml",
        "steps:\n  - echo hello > {PIPE_PATH}\n  - cat {PIPE_PATH}\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Pipe", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is True
    assert "{PIPE_PATH}" not in payload["command"]
    assert "hello" in payload["stdout"]
    # the backend owns the run and removes the file once it has finished
    assert ybe.is_pipe_path(payload["pipe_path"])
    assert not Path(payload["pipe_path"]).exists()


def test_api_action_run_keep_pipe_keeps_file(clean_state, tmp_path):
    ybe.STATE["keep_pipe"] = True
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo x > {PIPE_PATH}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Write", "target": "train/a.jpg"}).get_json()
    assert Path(payload["pipe_path"]).is_file()


def test_api_action_run_after_success_action_shares_pipe(clean_state, tmp_path):
    # a server-side after_success action runs in the same execution and sees what
    # the root action wrote to the pipe
    write_action(tmp_path, "Write.yaml", "steps:\n  - echo one > {PIPE_PATH}\n")
    write_action(tmp_path, "Read.yaml", "steps:\n  - cat {PIPE_PATH}\n")
    write_action(tmp_path, "Root.yaml", "after_success:\n  - action_Write\n  - action_Read\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is True
    assert "one" in payload["stdout"]
    assert not Path(payload["pipe_path"]).exists()


def test_api_action_run_pauses_at_client_action(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Root.yaml",
        "steps:\n  - echo root\nafter_success:\n  - app_refresh_image\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    first = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert first["ok"] is True
    assert first["client_action"] == "app_refresh_image"
    assert first["uid"] in ybe.EXECUTIONS
    pipe = first["pipe_path"]
    assert Path(pipe).is_file()
    # the client reports back; the chain has no more entries, so it finishes
    done = client.post(
        "/api/actions/run", json={"uid": first["uid"], "result": {"ok": True}}
    ).get_json()
    assert done["ok"] is True
    assert "client_action" not in done
    assert first["uid"] not in ybe.EXECUTIONS
    assert not Path(pipe).exists()


def test_api_action_run_steps_can_mix_client_action(clean_state, tmp_path):
    write_action(
        tmp_path,
        "Root.yaml",
        "steps:\n  - echo before\n  - app_refresh_image\n  - echo after\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    first = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert first["ok"] is True
    assert first["client_action"] == "app_refresh_image"
    # execution stopped before the step after the client action
    assert "before" in first["stdout"] and "after" not in first["stdout"]
    done = client.post(
        "/api/actions/run", json={"uid": first["uid"], "result": {"ok": True}}
    ).get_json()
    assert done["ok"] is True
    assert "after" in done["stdout"]


def test_api_action_run_steps_can_chain_action(clean_state, tmp_path):
    write_action(tmp_path, "Sub.yaml", "steps:\n  - echo sub\n")
    write_action(tmp_path, "Root.yaml", "steps:\n  - echo root\n  - action_Sub\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is True
    assert "root" in payload["stdout"] and "sub" in payload["stdout"]


def test_api_action_run_bare_action_name_is_a_shell_command(clean_state, tmp_path):
    # without the `action_` prefix a name is not resolved as an action
    write_action(tmp_path, "Sub.yaml", "steps:\n  - echo sub\n")
    write_action(tmp_path, "Root.yaml", "steps:\n  - Sub\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is False
    assert "sub" not in payload["stdout"]


def test_api_action_run_hook_steps_can_include_client_action(clean_state, tmp_path):
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "steps:\n  - echo hooked\n  - app_refresh_image\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    first = client.post(
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert first["ok"] is True
    assert first["client_action"] == "app_refresh_image"
    assert "hooked" in first["stdout"]


def test_api_action_run_preserves_mixed_after_success_order(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    log = root / "order.log"
    write_action(tmp_path, "ServerA.yaml", "steps:\n  - echo A >> {DATASET_PATH}/order.log\n")
    write_action(tmp_path, "ServerB.yaml", "steps:\n  - echo B >> {DATASET_PATH}/order.log\n")
    write_action(
        tmp_path,
        "Root.yaml",
        "after_success:\n  - action_ServerA\n  - app_refresh_image\n  - action_ServerB\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    first = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert first["client_action"] == "app_refresh_image"
    # only the server action before the client action has run so far
    assert log.read_text(encoding="utf-8").split() == ["A"]
    client.post("/api/actions/run", json={"uid": first["uid"], "result": {"ok": True}})
    assert log.read_text(encoding="utf-8").split() == ["A", "B"]


def test_api_action_run_resume_unknown_uid(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/actions/run", json={"uid": "nope", "result": {"ok": True}})
    assert resp.status_code == 400


def test_api_action_run_client_action_failure_aborts(clean_state, tmp_path):
    write_action(tmp_path, "Root.yaml", "after_success:\n  - app_refresh_image\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    first = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    pipe = first["pipe_path"]
    payload = client.post(
        "/api/actions/run",
        json={"uid": first["uid"], "result": {"ok": False, "error": "boom"}},
    ).get_json()
    assert payload["ok"] is False
    assert "boom" in payload["error"]
    assert first["uid"] not in ybe.EXECUTIONS
    assert not Path(pipe).exists()


def test_api_action_run_unknown_after_success_entry(clean_state, tmp_path):
    write_action(tmp_path, "Root.yaml", "steps:\n  - echo hi\nafter_success:\n  - action_Nope\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is False
    assert "unknown action" in payload["error"]
    assert not Path(payload["pipe_path"]).exists()


def test_api_action_run_after_success_accepts_shell_and_action(clean_state, tmp_path):
    write_action(tmp_path, "Sub.yaml", "steps:\n  - echo sub\n")
    write_action(
        tmp_path,
        "Root.yaml",
        "after_success:\n  - echo shell\n  - action_Sub\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is True
    assert "shell" in payload["stdout"] and "sub" in payload["stdout"]


def test_api_action_run_cascade_limit(clean_state, tmp_path):
    for i in range(9):
        body = f"steps:\n  - echo {i}\n"
        if i < 8:
            body += f"after_success:\n  - action_Chain{i + 1}\n"
        write_action(tmp_path, f"Chain{i}.yaml", body)
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post("/api/actions/run", json={"action": "Chain0", "target": "train/a.jpg"}).get_json()
    assert payload["ok"] is False
    assert "cascade exceeded" in payload["error"]


def test_remove_pipe_ignores_foreign_path(clean_state, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    assert ybe.remove_pipe(str(victim)) is False
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
    resp = client.get("/api/image?key=train/a.jpg")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"


# --------------------------------------------------------------------------- #
# filters/ (script-based image-list filters)
# --------------------------------------------------------------------------- #
def test_filter_name_strips_py_suffix():
    assert ybe._filter_name("/d/Odd.py") == "Odd"


def test_load_filters_one_script_per_filter(clean_state):
    write_filter(clean_state, "Odd.py", "print('train/a.jpg')\n")
    write_filter(clean_state, "Even.py", "# nothing\n")
    assert sorted(ybe.load_filters()) == ["Even", "Odd"]


def test_load_filters_user_override_wins(clean_state):
    write_filter(clean_state, "Odd.py", "print('repo')\n", subdir="app-filters")
    write_filter(clean_state, "Odd.py", "print('user')\n")
    assert ybe.load_filters()["Odd"].endswith("filters/Odd.py")


def test_load_filters_ignores_non_py(clean_state):
    (clean_state / "filters").mkdir()
    (clean_state / "filters" / "notes.txt").write_text("x", encoding="utf-8")
    assert ybe.load_filters() == {}


def test_load_filters_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe, "FILTERS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe, "USER_FILTERS_DIR", str(tmp_path / "nope-user"))
    assert ybe.load_filters() == {}


def test_parse_filter_output_maps_paths_dedupes_and_orders(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a", "b"))
    load_into_state(root)
    known = ybe._known_image_paths()
    a = str(root / "images" / "train" / "a.jpg")
    b = str(root / "images" / "train" / "b.jpg")
    c = str(root / "images" / "val" / "a.jpg")
    text = f"{b}\n{c}\n{b}\n\n/unknown/x.jpg\n{a}\n"
    entries, skipped = ybe._parse_filter_output(text, known)
    assert entries == [
        {"split": "train", "name": "b.jpg"},
        {"split": "val", "name": "a.jpg"},
        {"split": "train", "name": "a.jpg"},
    ]
    assert skipped == 1


def test_parse_filter_output_counts_unknown_paths(clean_state):
    entries, skipped = ybe._parse_filter_output("/nope/x.jpg\n", {})
    assert entries == [] and skipped == 1


def test_run_filter_passes_args_and_pipes(clean_state):
    args_log = clean_state / "args.txt"
    write_filter(
        clean_state,
        "Args.py",
        f"import sys\nopen({str(args_log)!r}, 'w').write('|'.join(sys.argv[1:]))\n",
    )
    result = ybe.run_filter("Args", "/d/data.yaml", "train", "in.txt", "out.txt")
    assert result["ok"] is True
    assert args_log.read_text(encoding="utf-8") == "/d/data.yaml|train|in.txt|out.txt"


def test_run_filter_empty_split_for_all_splits(clean_state):
    args_log = clean_state / "args.txt"
    write_filter(
        clean_state,
        "Args.py",
        f"import sys\nopen({str(args_log)!r}, 'w').write('|'.join(sys.argv[1:]))\n",
    )
    assert ybe.run_filter("Args", "/d/data.yaml", "", "in.txt", "out.txt")["ok"] is True
    assert args_log.read_text(encoding="utf-8") == "/d/data.yaml||in.txt|out.txt"


def test_run_filter_unknown(clean_state):
    assert ybe.run_filter("Nope", "", "train", "in", "out")["ok"] is False


def test_run_filter_nonzero_exit_reports_stderr(clean_state):
    write_filter(
        clean_state, "Boom.py", "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n"
    )
    result = ybe.run_filter("Boom", "", "train", "in", "out")
    assert result["ok"] is False and "boom" in result["error"]


def test_run_filter_timeout(clean_state, monkeypatch):
    monkeypatch.setattr(ybe, "FILTER_TIMEOUT", 0.2)
    write_filter(clean_state, "Slow.py", "import time\ntime.sleep(5)\n")
    result = ybe.run_filter("Slow", "", "train", "in", "out")
    assert result["ok"] is False and "timed out" in result["error"]


def test_filter_chain_feeds_output_to_next(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    load_into_state(root)
    second_input = clean_state / "second_input.txt"
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "Record.py", filter_recording_input(second_input))
    result = ybe.run_filter_chain(["OnlyA", "Record"], "train")
    assert result["ok"] is True
    assert [e["name"] for e in result["images"]] == ["a.jpg"]
    # the second filter saw exactly the first filter's output
    lines = second_input.read_text(encoding="utf-8").split()
    assert [Path(p).name for p in lines] == ["a.jpg"]


def test_filter_chain_first_input_is_active_split(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    load_into_state(root)
    seen = clean_state / "seen.txt"
    write_filter(clean_state, "Record.py", filter_recording_input(seen))
    assert ybe.run_filter_chain(["Record"], "train")["ok"] is True
    assert seen.read_text(encoding="utf-8").split() == [
        str(root / "images" / "train" / "a.jpg")
    ]
    assert ybe.run_filter_chain(["Record"], "")["ok"] is True
    assert set(seen.read_text(encoding="utf-8").split()) == {
        str(root / "images" / "train" / "a.jpg"),
        str(root / "images" / "val" / "a.jpg"),
    }


def test_filter_chain_stops_at_first_failure(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    after_log = clean_state / "after.txt"
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    write_filter(clean_state, "Boom.py", "import sys\nsys.exit(4)\n")
    write_filter(clean_state, "After.py", filter_recording_input(after_log))
    result = ybe.run_filter_chain(["Copy", "Boom", "After"], "train")
    assert result["ok"] is False and 'Filter "Boom" failed' in result["error"]
    assert not after_log.exists()


def test_filter_chain_cleans_scratch_dir(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    result = ybe.run_filter_chain(["Copy"], "train")
    assert result["ok"] is True and result["chain_dir"] is None
    assert list(Path(ybe.FILTER_PIPES_DIR).glob("chain_*")) == []


def test_filter_chain_keeps_scratch_dir_when_asked(clean_state, tmp_path):
    ybe.STATE["keep_filter_pipes"] = True
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    result = ybe.run_filter_chain(["Copy"], "train")
    assert result["ok"] is True
    assert Path(result["chain_dir"]).is_dir()
    assert (Path(result["chain_dir"]) / "input_0.txt").is_file()


def test_api_config_reports_filters(clean_state):
    write_filter(clean_state, "Odd.py", "# nothing\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["filters"] == ["Odd"]
    assert cfg["active_filters"] == []


def test_api_filter_set_chain_and_clear(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    client = ybe.app.test_client()
    load_dataset(client, root)

    cfg = client.post("/api/filter", json={"filters": ["OnlyA", "Copy"]}).get_json()
    assert cfg["ok"] is True
    assert cfg["active_filters"] == ["OnlyA", "Copy"]
    assert [e["name"] for e in cfg["images"]] == ["a.jpg"]

    cfg = client.post("/api/filter", json={"filters": []}).get_json()
    assert cfg["active_filters"] == []
    assert len(cfg["images"]) == 2


def test_api_filter_accepts_legacy_single_name(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filter": "OnlyA"}).get_json()
    assert cfg["active_filters"] == ["OnlyA"]
    assert [e["name"] for e in cfg["images"]] == ["a.jpg"]


def test_api_filter_clear_with_legacy_null(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": ["OnlyA"]})
    cfg = client.post("/api/filter", json={"filter": None}).get_json()
    assert cfg["active_filters"] == []


def test_api_filter_requires_dataset(clean_state):
    resp = ybe.app.test_client().post("/api/filter", json={"filters": ["X"]})
    assert resp.status_code == 400
    assert "no dataset" in resp.get_json()["error"]


def test_api_filter_unknown(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/filter", json={"filters": ["Nope"]})
    assert resp.status_code == 400
    assert "unknown filter" in resp.get_json()["error"]


def test_api_filter_can_span_splits_when_all(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": ["Copy"]}).get_json()
    assert [(e["split"], e["name"]) for e in cfg["images"]] == [
        ("train", "a.jpg"),
        ("val", "a.jpg"),
    ]


def test_api_filter_reports_unknown_paths(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(
        clean_state,
        "Sloppy.py",
        "import sys\n"
        "inp, out = sys.argv[3], sys.argv[4]\n"
        "text = open(inp, encoding='utf-8').read()\n"
        "open(out, 'w', encoding='utf-8').write(text + '/nope/missing.jpg\\n')\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": ["Sloppy"]}).get_json()
    assert cfg["active_filters"] == ["Sloppy"]
    assert "ignored" in (cfg["filter_error"] or "")


def test_api_filter_allowed_in_readonly(clean_state, tmp_path):
    ybe.STATE["readonly"] = True
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "Keep.py", FILTER_COPY)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/filter", json={"filters": ["Keep"]})
    assert resp.status_code == 200
    assert resp.get_json()["active_filters"] == ["Keep"]


def test_api_data_clears_active_filters(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "Keep.py", FILTER_COPY)
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": ["Keep"]})
    assert ybe.STATE["active_filters"] == ["Keep"]
    load_dataset(client, root)
    assert ybe.STATE["active_filters"] == []


def test_api_split_reruns_active_chain(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a", "b"))
    write_filter(clean_state, "Copy.py", FILTER_COPY)
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": ["Copy", "OnlyA"]})
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
        "open(sys.argv[4], 'w').write(open(sys.argv[3]).read())\n",
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": ["Pick"]})
    resp = client.post("/api/split", json={"split": "val"})
    assert resp.status_code == 400
    assert ybe.STATE["active_split"] is None  # unchanged
    assert ybe.STATE["active_filters"] == ["Pick"]


def test_api_images_rescan_reruns_chain(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": ["OnlyA"]})
    (root / "images" / "train" / "a.jpg").unlink()
    data = client.post("/api/images/rescan").get_json()
    assert data["active_filters"] == ["OnlyA"]
    assert data["images"] == []


def test_api_image_resolves_by_key_regardless_of_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_filter(clean_state, "OnlyB.py", filter_selecting("b.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": ["OnlyB"]}).get_json()
    assert [e["name"] for e in cfg["images"]] == ["b.jpg"]
    # identity reads are not affected by the filter: both files still resolve
    assert client.get("/api/image?key=train/a.jpg").status_code == 200
    assert client.get("/api/image?key=train/b.jpg").status_code == 200


# --------------------------------------------------------------------------- #
# routes: in-memory image list + backend actions
# --------------------------------------------------------------------------- #
def test_api_images_get_returns_current_list(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    data = client.get("/api/images").get_json()
    assert data["ok"] is True
    assert [e["name"] for e in data["images"]] == ["a.jpg", "b.jpg"]
    # it reads memory, not the disk: a deleted file stays listed until a rescan
    (root / "images" / "train" / "b.jpg").unlink()
    assert len(client.get("/api/images").get_json()["images"]) == 2
    assert len(client.post("/api/images/rescan").get_json()["images"]) == 1


def test_app_reload_images_list_registered():
    assert "app_reload_images_list" in ybe.APP_ACTIONS


def test_backend_rescan_images_action_entry(clean_state, tmp_path):
    # a `backend_*` entry runs inline server-side (no client pause)
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_action(tmp_path, "Rescan.yaml", "after_success:\n  - backend_rescan_images\n")
    client = ybe.app.test_client()
    load_dataset(client, root)
    (root / "images" / "train" / "b.jpg").unlink()
    payload = client.post(
        "/api/actions/run", json={"action": "Rescan", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert "client_action" not in payload
    assert [e["name"] for e in ybe.STATE["images"]] == ["a.jpg"]


def test_backend_unknown_action_entry_errors(clean_state, tmp_path):
    write_action(tmp_path, "Root.yaml", "after_success:\n  - backend_nope\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "Root", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is False
    assert "unknown backend action" in payload["error"]
    assert not Path(payload["pipe_path"]).exists()


# --------------------------------------------------------------------------- #
# per-dataset view persistence
# --------------------------------------------------------------------------- #
def test_view_state_saved_on_split_and_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/split", json={"split": "train"})
    client.post("/api/filter", json={"filters": ["OnlyA"]})
    assert ybe._load_views()[str(root / "data.yaml")] == {
        "split": "train",
        "filters": ["OnlyA"],
        "tags_dir": None,
    }


def test_resume_restores_saved_view(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/split", json={"split": "train"})
    client.post("/api/filter", json={"filters": ["OnlyA"]})
    # simulate a server restart: in-memory state resets, then resume reopens the
    # last dataset (RECENT_FILE persists) and must restore its split/filter chain
    ybe.STATE.clear()
    ybe.STATE.update(DEFAULT_STATE)
    assert ybe._resume_last_dataset() == str(root / "data.yaml")
    assert ybe.STATE["active_split"] == "train"
    assert ybe.STATE["active_filters"] == ["OnlyA"]


def test_restore_view_accepts_legacy_single_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_filter(clean_state, "OnlyA.py", filter_selecting("a.jpg"))
    load_into_state(root)
    ybe._save_view(str(root / "data.yaml"), "train", [])
    views = ybe._load_views()
    views[str(root / "data.yaml")] = {"split": "train", "filter": "OnlyA"}
    Path(ybe.VIEW_FILE).write_text(json.dumps(views), encoding="utf-8")
    ybe._restore_view(str(root / "data.yaml"))
    assert ybe.STATE["active_filters"] == ["OnlyA"]


# --------------------------------------------------------------------------- #
# routes: presence (multi-tab / multi-client warning)
# --------------------------------------------------------------------------- #
def test_presence_single_client(clean_state):
    client = ybe.app.test_client()
    data = client.post("/api/presence", json={"cid": "a"}).get_json()
    assert data == {"ok": True, "count": 1, "others": 0}


def test_presence_counts_multiple_clients(clean_state):
    first = ybe.app.test_client()
    second = ybe.app.test_client()
    first.post("/api/presence", json={"cid": "a"})
    data = second.post("/api/presence", json={"cid": "b"}).get_json()
    assert data["count"] == 2
    assert data["others"] == 1


def test_presence_same_cid_stays_one_client(clean_state):
    client = ybe.app.test_client()
    client.post("/api/presence", json={"cid": "a"})
    data = client.post("/api/presence", json={"cid": "a"}).get_json()
    assert data["count"] == 1


def test_presence_bye_removes_client(clean_state):
    client = ybe.app.test_client()
    client.post("/api/presence", json={"cid": "a"})
    client.post("/api/presence", json={"cid": "b"})
    data = client.post("/api/presence", json={"cid": "a", "bye": True}).get_json()
    assert data["count"] == 1
    assert "a" not in ybe.CLIENTS
    assert "b" in ybe.CLIENTS


def test_presence_prunes_stale_clients(clean_state):
    ybe.CLIENTS["old"] = time.monotonic() - (ybe.PRESENCE_TTL + 1)
    client = ybe.app.test_client()
    data = client.post("/api/presence", json={"cid": "new"}).get_json()
    assert data["count"] == 1
    assert "old" not in ybe.CLIENTS
    assert "new" in ybe.CLIENTS


def test_presence_requires_client_id(clean_state):
    client = ybe.app.test_client()
    resp = client.post("/api/presence", json={})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False

# --------------------------------------------------------------------------- #
# update check
# --------------------------------------------------------------------------- #
def _write_version(root, value):
    (Path(root) / "VERSION").write_text(value + "\n", encoding="utf-8")


def test_read_version(clean_state):
    _write_version(clean_state, "9.9.9")
    assert ybe.read_version() == "9.9.9"


def test_read_version_missing_is_unknown(clean_state):
    assert ybe.read_version() == "unknown"


def test_parse_version_forms():
    assert ybe._parse_version("v2.3.0") == (2, 3, 0)
    assert ybe._parse_version("2.2.0-rc1") == (2, 2, 0)
    assert ybe._parse_version("") is None
    assert ybe._parse_version("abc") is None
    assert ybe._parse_version(None) is None


def test_version_newer_compares_numerically():
    assert ybe._version_newer("2.10.0", "2.9.0") is True
    assert ybe._version_newer("2.2.0", "2.2.0") is False
    assert ybe._version_newer("2.1.0", "2.2.0") is False
    assert ybe._version_newer(None, "2.2.0") is False


def test_check_for_update_writes_cache(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: "2.3.0")
    info = ybe.check_for_update(now=1000)
    assert info["update_available"] is True
    cached = json.loads((clean_state / "update.json").read_text(encoding="utf-8"))
    assert cached["latest_version"] == "2.3.0"
    assert cached["checked_at"] == 1000


def test_check_for_update_uses_fresh_cache(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 1000, "current_version": "2.2.0",
        "latest_version": "2.3.0", "update_available": True,
    }), encoding="utf-8")
    calls = []

    def fake(timeout=None):
        calls.append(1)
        return "9.9.9"

    monkeypatch.setattr(ybe, "fetch_latest_version", fake)
    info = ybe.check_for_update(now=1000 + ybe.UPDATE_CHECK_INTERVAL - 1)
    assert info["latest_version"] == "2.3.0"
    assert calls == []


def test_check_for_update_refetches_after_interval(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 1000, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: "2.4.0")
    info = ybe.check_for_update(now=1000 + ybe.UPDATE_CHECK_INTERVAL + 1)
    assert info["latest_version"] == "2.4.0"


def test_check_for_update_force_bypasses_cache(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 10, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: "2.4.0")
    info = ybe.check_for_update(force=True, now=11)
    assert info["latest_version"] == "2.4.0"


def test_check_for_update_offline_marks_not_available(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: None)
    info = ybe.check_for_update(now=1000)
    assert info["update_available"] is False
    assert info["latest_version"] is None


def test_check_for_update_version_change_refetches(clean_state, monkeypatch):
    _write_version(clean_state, "2.3.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 1000, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: "2.3.0")
    info = ybe.check_for_update(now=1001)
    assert info["update_available"] is False


def test_update_status_reads_cache(clean_state):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 5, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    status = ybe.update_status()
    assert status["update_available"] is True
    assert status["latest_version"] == "2.3.0"


def test_api_config_includes_version_and_update(clean_state):
    _write_version(clean_state, "2.2.0")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["version"] == "2.2.0"
    assert cfg["update"]["update_available"] is False


def test_api_update_check_returns_cached(clean_state):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 5, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    data = ybe.app.test_client().get("/api/update-check").get_json()
    assert data["ok"] is True
    assert data["update"]["latest_version"] == "2.3.0"


def test_api_update_check_post_forces_refresh(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    monkeypatch.setattr(ybe, "fetch_latest_version", lambda timeout=None: "2.5.0")
    data = ybe.app.test_client().post(
        "/api/update-check", json={"force": True}
    ).get_json()
    assert data["update"]["latest_version"] == "2.5.0"


def test_configure_home_repoints_update_file(clean_state, tmp_path):
    target = tmp_path / "elsewhere"
    ybe.configure_home(str(target))
    assert ybe.UPDATE_CHECK_FILE == str(target / ".update_check.json")


# --------------------------------------------------------------------------- #
# logging / daemon
# --------------------------------------------------------------------------- #
def test_presence_filter_drops_heartbeat():
    flt = ybe._SkipPresenceFilter()
    heartbeat = logging.LogRecord(
        "werkzeug", logging.INFO, __file__, 1,
        '127.0.0.1 - - "GET /api/presence HTTP/1.1" 200 -', None, None,
    )
    normal = logging.LogRecord(
        "werkzeug", logging.INFO, __file__, 1,
        '127.0.0.1 - - "GET /api/config HTTP/1.1" 200 -', None, None,
    )
    assert flt.filter(heartbeat) is False
    assert flt.filter(normal) is True


def test_setup_logging_writes_to_file(clean_state, tmp_path):
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        logfile = tmp_path / "ybe.log"
        log = ybe.setup_logging(str(logfile), debug=False)
        assert log.name == "ybe"
        log.info("hello daemon")
        for handler in root.handlers:
            handler.flush()
        assert "hello daemon" in logfile.read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_setup_logging_installs_presence_filter():
    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")
    saved_root = root.handlers[:]
    saved_wz = werkzeug.filters[:]
    saved_level = root.level
    try:
        ybe.setup_logging(None)
        assert any(isinstance(f, ybe._SkipPresenceFilter) for f in werkzeug.filters)
        # configuring twice must not stack duplicate filters
        ybe.setup_logging(None)
        count = sum(1 for f in werkzeug.filters if isinstance(f, ybe._SkipPresenceFilter))
        assert count == 1
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers = saved_root
        root.setLevel(saved_level)
        werkzeug.filters = saved_wz


# --------------------------------------------------------------------------- #
# changelog (app/CHANGES)
# --------------------------------------------------------------------------- #
def test_parse_changes_sections_and_bullets():
    text = (
        "# header comment\n"
        "\n"
        "## 2.8.0\n"
        "- added a thing\n"
        "fixed another thing\n"
        "\n"
        "## 2.7.1\n"
        "- older\n"
    )
    assert ybe.parse_changes(text) == {
        "2.8.0": ["added a thing", "fixed another thing"],
        "2.7.1": ["older"],
    }


def test_load_and_changelog_for(clean_state):
    (clean_state / "CHANGES").write_text(
        "## 2.8.0\n- note one\n- note two\n", encoding="utf-8"
    )
    assert ybe.load_changes()["2.8.0"] == ["note one", "note two"]
    assert ybe.changelog_for("2.8.0") == ["note one", "note two"]
    assert ybe.changelog_for("1.0.0") == []
    assert ybe.changelog_for(None) == []


def test_api_config_includes_changelog(clean_state):
    _write_version(clean_state, "2.8.0")
    (clean_state / "CHANGES").write_text("## 2.8.0\n- shiny\n", encoding="utf-8")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["version"] == "2.8.0"
    assert cfg["changelog"] == ["shiny"]


def test_update_payload_has_no_breaking_fields():
    payload = ybe._update_payload({
        "current_version": "2.7.0",
        "latest_version": "2.8.0",
    })
    assert payload["update_available"] is True
    assert "breaking" not in payload
    assert "breaking_changes" not in payload


def test_fetch_latest_version_picks_highest_of_release_and_tags(monkeypatch):
    def fake_get(url, timeout=None):
        if url.endswith("/releases/latest"):
            return '{"tag_name": "2.5.0"}'
        if url.endswith("/tags"):
            return '[{"name": "2.6.0"}, {"name": "2.5.0"}]'
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ybe, "_http_get_text", fake_get)
    assert ybe.fetch_latest_version() == "2.6.0"


def test_fetch_latest_version_falls_back_to_release_without_tags(monkeypatch):
    def fake_get(url, timeout=None):
        if url.endswith("/releases/latest"):
            return '{"tag_name": "v3.1.0"}'
        if url.endswith("/tags"):
            return "[]"
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ybe, "_http_get_text", fake_get)
    assert ybe.fetch_latest_version() == "3.1.0"
