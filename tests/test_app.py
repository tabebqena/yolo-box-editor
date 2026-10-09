"""Test suite for the yolo-box-editor Flask app (app.py).

Run from the repo root; the app is a single module with no package layout, so
the repo root is added to sys.path here.

The app's own support files (the actions/ folder / shortcuts.txt /
.recent_data_yamls.json) are NEVER touched: fixtures monkeypatch every file
constant to disposable paths under tmp_path, and STATE is reset per test.
"""

import importlib.util
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
    assert ybe.config._resolve_home() == os.path.dirname(ybe.config.BASE_DIR)


def test_home_env_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("YBX_HOME", str(tmp_path / "h"))
    assert ybe.config._resolve_home() == str(tmp_path / "h")


def test_configure_home_repoints_user_dirs(clean_state, tmp_path):
    target = tmp_path / "elsewhere"
    ybe.configure_home(str(target))
    assert ybe.config.YBX_HOME == str(target)
    assert ybe.config.USER_ACTIONS_DIR == str(target / "actions")
    assert ybe.config.USER_SCRIPT_DIR == str(target / "scripts")
    assert ybe.config.CONFIG_FILE == str(target / "config.json")
    assert ybe.config.RECENT_FILE == str(target / ".recent_data_yamls.json")
    assert ybe.config.SETTINGS_FILE == str(target / ".settings.json")
    assert ybe.config.SECRET_KEY_FILE == str(target / ".secret_key")


def test_secret_key_is_created_persisted_and_reused(clean_state):
    key_path = Path(ybe.config.SECRET_KEY_FILE)
    assert not key_path.exists()
    first = ybe.load_or_create_secret_key()
    assert first and key_path.exists()
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"
    assert ybe.load_or_create_secret_key() == first


def test_secret_key_replaces_an_empty_file(clean_state):
    key_path = Path(ybe.config.SECRET_KEY_FILE)
    key_path.write_text("\n", encoding="utf-8")
    key = ybe.load_or_create_secret_key()
    assert key
    assert ybe.load_or_create_secret_key() == key


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
    monkeypatch.setattr(ybe.config, "YBX_HOME", str(tmp_path))
    monkeypatch.setattr(ybe.config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(ybe.config, "RECENT_FILE", str(tmp_path / "recent.json"))
    monkeypatch.setattr(ybe.config, "VIEW_FILE", str(tmp_path / "view.json"))
    monkeypatch.setattr(ybe.config, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(ybe.config, "UPDATE_CHECK_FILE", str(tmp_path / "update.json"))
    monkeypatch.setattr(ybe.config, "VERSION_FILE", str(tmp_path / "VERSION"))
    monkeypatch.setattr(ybe.config, "CHANGES_FILE", str(tmp_path / "CHANGES"))
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "app-actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "app-hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(tmp_path / "app-filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(tmp_path / "filters"))
    monkeypatch.setattr(ybe.config, "WIDGETS_DIR", str(tmp_path / "app-widgets"))
    monkeypatch.setattr(ybe.config, "USER_WIDGETS_DIR", str(tmp_path / "widgets"))
    monkeypatch.setattr(ybe.config, "EXTENSIONS_DIR", str(tmp_path / "app-extensions"))
    monkeypatch.setattr(ybe.config, "USER_EXTENSIONS_DIR", str(tmp_path / "extensions"))
    monkeypatch.setattr(ybe.config, "APP_SCRIPT_DIR", str(tmp_path / "app-scripts"))
    monkeypatch.setattr(ybe.config, "USER_SCRIPT_DIR", str(tmp_path / "scripts"))
    monkeypatch.setattr(ybe.config, "SHORTCUTS_FILE", str(tmp_path / "app-shortcuts.txt"))
    monkeypatch.setattr(ybe.config, "USER_SHORTCUTS_FILE", str(tmp_path / "shortcuts.txt"))
    monkeypatch.setattr(ybe.config, "PIPE_DIR", str(tmp_path / "pipes"))
    monkeypatch.setattr(ybe.config, "FILTER_PIPES_DIR", str(tmp_path / "filter-pipes"))
    monkeypatch.setattr(ybe.config, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(ybe.config, "SECRET_KEY_FILE", str(tmp_path / ".secret_key"))
    monkeypatch.setattr(ybe.state, "USERS", {})
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    ybe.state.EXECUTIONS.clear()
    ybe.state.CLIENTS.clear()
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
    """Write one filter YAML file into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def write_script(root, fname, body, subdir="scripts"):
    """Write one helper script into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


def load_into_state(root):
    """Activate `root`'s dataset in STATE without going through a client."""
    ybe.state.STATE["data_yaml"] = str(Path(root) / "data.yaml")
    ybe.state.STATE["dataset_path"] = str(root)
    ybe.state.STATE["splits"] = ybe.scan_splits()
    ybe.state.STATE["images"] = ybe.scan_images()


def read_config():
    """The unified config dict (missing/invalid file -> empty shape)."""
    try:
        data = json.loads(Path(ybe.config.CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"recent": [], "views": {}, "settings": {}}
    return data


def write_config(**sections):
    """Write sections (recent/views/settings) into the unified config file."""
    cfg = {"recent": [], "views": {}, "settings": {}}
    cfg.update(sections)
    Path(ybe.config.CONFIG_FILE).write_text(json.dumps(cfg), encoding="utf-8")


# Copies the input pipe to the output pipe unchanged (the identity filter).
FILTER_COPY = "import sys\nopen(sys.argv[2], 'w').write(open(sys.argv[1]).read())\n"


def filter_selecting(*names):
    """A filter that keeps only input paths whose file name is in `names`."""
    wanted = ", ".join(repr(n) for n in names)
    return (
        "import os, sys\n"
        "paths = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip()]\n"
        f"wanted = {{{wanted}}}\n"
        "with open(sys.argv[2], 'w', encoding='utf-8') as out:\n"
        "    for p in paths:\n"
        "        if os.path.basename(p) in wanted:\n"
        "            out.write(p + '\\n')\n"
    )


def filter_recording_input(log_path):
    """A filter that copies its input to `log_path` as well as to the output."""
    return (
        "import sys\n"
        f"text = open(sys.argv[1], encoding='utf-8').read()\n"
        f"open({str(log_path)!r}, 'w', encoding='utf-8').write(text)\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(text)\n"
    )


def py_step(script, extra=""):
    """A filter `steps` entry running <USER_SCRIPT_DIR>/<script> on the pipes."""
    cmd = (f'"{sys.executable}" {{USER_SCRIPT_DIR}}/{script} '
           f'{{INPUT_PIPE}} {{OUTPUT_PIPE}}')
    return cmd + (f" {extra}" if extra else "")


def filter_yaml(steps, name=None, description=None, active=None, arguments=None):
    """Build a filters/*.yaml body from simple values.

    `steps` is a string or list of strings; each `arguments` entry is a dict of
    pre-formatted YAML scalars (e.g. {"name": "every", "default": '"2"'}).
    """
    lines = []
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    if active is not None:
        lines.append(f"active: {'true' if active else 'false'}")
    if arguments:
        lines.append("arguments:")
        for arg in arguments:
            first = True
            for key, value in arg.items():
                lines.append(("  - " if first else "    ") + f"{key}: {value}")
                first = False
    lines.append("steps:")
    for step in ([steps] if isinstance(steps, str) else steps):
        lines.append(f"  - {step}")
    return "\n".join(lines) + "\n"



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
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
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
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "whatever.yaml", "name: Custom\nsteps:\n  - echo hi\n")
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert "Custom" in actions and "whatever" not in actions


def test_load_actions_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "Shared.yaml", "steps:\n  - echo repo\n")
    write_action(
        tmp_path, "Shared.yaml", "steps:\n  - echo user\n", subdir="user-actions"
    )
    actions = {a["name"]: a for a in ybe.load_actions()}
    assert actions["Shared"]["steps"] == ["echo user"]


def test_load_actions_override_targets_name_key(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
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
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    write_action(tmp_path, "Empty.yaml", "name: Empty\nafter_success: []\n")
    write_action(tmp_path, "notes.txt", "steps:\n  - echo hi\n")
    assert ybe.load_actions() == []


def test_load_actions_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "nope-user"))
    assert ybe.load_actions() == []


def test_is_hook_name_matches_only_on_prefix():
    assert ybe.is_hook_name("on_after_save")
    assert ybe.is_hook_name("on_box_created")
    assert ybe.is_hook_name("on_prev")
    assert ybe.is_hook_name("on_next")
    assert ybe.is_hook_name("on_before_prev")
    assert ybe.is_hook_name("on_before_next")
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
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo saved\n")
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]
    assert hooks[0]["event"] == "after_save"
    assert hooks[0]["steps"] == ["echo saved"]


def test_load_hooks_before_navigation_events(tmp_path, monkeypatch):
    assert "before_prev" in ybe.config.HOOK_EVENTS
    assert "before_next" in ybe.config.HOOK_EVENTS
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_before_prev.yaml", "steps:\n  - echo prev\n")
    write_hook(tmp_path, "on_before_next.yaml", "steps:\n  - echo next\n")
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_before_next", "on_before_prev"]
    assert [h["event"] for h in hooks] == ["before_next", "before_prev"]


def test_load_hooks_event_name_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(
        tmp_path, "whatever.yaml", "event_name: after_save\nsteps:\n  - echo hi\n"
    )
    hooks, errors = ybe.load_hooks()
    assert errors == []
    assert [h["name"] for h in hooks] == ["on_after_save"]


def test_load_hooks_known_filename_wins_over_event_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(
        tmp_path,
        "on_after_save.yaml",
        "event_name: before_save\nsteps:\n  - echo hi\n",
    )
    hooks, _ = ybe.load_hooks()
    assert hooks[0]["event"] == "after_save"


def test_load_hooks_inactive_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_after_save.yaml", "active: false\nsteps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_unknown_event_with_steps_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "on_nope.yaml", "steps:\n  - echo hi\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == []
    assert len(errors) == 1 and "on_nope.yaml" in errors[0]


def test_load_hooks_empty_template_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    write_hook(tmp_path, "example.yaml", "# comments only, no steps\n")
    hooks, errors = ybe.load_hooks()
    assert hooks == [] and errors == []


def test_load_hooks_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
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
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "nope-user"))
    assert ybe.load_hooks() == ([], [])


def test_load_shortcuts_merges_and_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe.config, "USER_SHORTCUTS_FILE", str(tmp_path / "s-user.txt"))
    (tmp_path / "s.txt").write_text("app_next <D> repo\napp_undo <Z> undo\n",
                                    encoding="utf-8")
    (tmp_path / "s-user.txt").write_text("app_next <F> user\n", encoding="utf-8")
    shortcuts = ybe.load_shortcuts()
    assert shortcuts["app_next"]["shortcut"] == "F"
    assert shortcuts["app_undo"]["label"] == "undo"


def test_modifier_only_shortcut_is_valid_app_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "SHORTCUTS_FILE", str(tmp_path / "s.txt"))
    monkeypatch.setattr(ybe.config, "USER_SHORTCUTS_FILE", str(tmp_path / "s-user.txt"))
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
    (tmp_path / "s.txt").write_text(
        "app_force_draw <Ctrl> hold + drag\napp_fix_box <F> fix\n",
        encoding="utf-8",
    )
    app, user, errors = ybe.split_shortcuts(ybe.load_shortcuts())
    assert errors == []
    assert user == {}
    assert app["app_force_draw"]["shortcut"] == "Ctrl"
    assert "app_fix_box" in app
    assert "app_fix_box" in ybe.config.APP_ACTIONS
    assert "app_force_draw" in ybe.config.APP_ACTIONS


def test_app_actions_include_hook_only_client_actions():
    # client-only names called from a step / after_success, not bound to keys
    for name in (
        "app_select_next_box",
        "app_select_prev_box",
        "app_copy_labels_from_prev",
    ):
        assert name in ybe.config.APP_ACTIONS


def test_refresh_image_actions_are_builtin():
    for name in (
        "app_refresh_image",
        "app_refresh_image_labels",
        "app_refresh_image_all",
    ):
        assert name in ybe.config.APP_ACTIONS
        assert ybe._resolve_entry(name, {}) == ("app", name)


def test_app_help_action_is_builtin():
    assert "app_help" in ybe.config.APP_ACTIONS


def test_isolate_box_action_is_builtin_and_shipped():
    assert "app_isolate_box" in ybe.config.APP_ACTIONS
    base = Path(ybe.config.BASE_DIR)
    text = (base / "shortcuts.txt").read_text(encoding="utf-8")
    assert "app_isolate_box" in text
    assert "<I>" in text


def test_keyboard_box_actions_are_builtin_and_shipped():
    for name in (
        "app_focus_canvas",
        "app_select_all",
        "app_widen_left",
        "app_widen_right",
        "app_widen_up",
        "app_widen_down",
        "app_narrow_left",
        "app_narrow_right",
        "app_narrow_up",
        "app_narrow_down",
    ):
        assert name in ybe.config.APP_ACTIONS
    base = Path(ybe.config.BASE_DIR)
    text = (base / "shortcuts.txt").read_text(encoding="utf-8")
    assert "app_select_all" in text and "<Ctrl+A>" in text
    assert "app_focus_canvas" in text and "<Space>" in text
    assert "<Ctrl+ArrowLeft>" in text and "<Ctrl+Shift+ArrowLeft>" in text


def test_mousefree_box_actions_are_builtin_and_shipped():
    # Creating a box (N) and moving it (Alt+arrow) without a mouse.
    for name in (
        "app_new_box",
        "app_move_left",
        "app_move_right",
        "app_move_up",
        "app_move_down",
    ):
        assert name in ybe.config.APP_ACTIONS
    base = Path(ybe.config.BASE_DIR)
    text = (base / "shortcuts.txt").read_text(encoding="utf-8")
    assert "app_new_box" in text and "<N>" in text
    assert "app_move_left" in text and "<Alt+ArrowLeft>" in text
    assert "app_move_down" in text and "<Alt+ArrowDown>" in text


def test_help_content_and_shipped_shortcut_ship():
    base = Path(ybe.config.BASE_DIR)
    # The shipped binding: F1 opens help.
    text = (base / "shortcuts.txt").read_text(encoding="utf-8")
    assert "app_help" in text
    assert "F1" in text
    # The tutorial + How-to fragments and the module ship with the app.
    for name in ("beginner.html", "intermediate.html", "expert.html", "howto.html"):
        assert (base / "static" / "help" / name).is_file()
    assert (base / "static" / "js" / "help.js").is_file()
    html = (base / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="helpModal"' in html
    assert 'id="helpBtn"' in html
    assert "help.js" in html
    # ...and the Flask static route serves them.
    client = ybe.app.test_client()
    assert client.get("/static/help/beginner.html").status_code == 200
    assert client.get("/static/js/help.js").status_code == 200


def test_split_shortcuts_partitions_and_reports_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(tmp_path / "user-actions"))
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(tmp_path / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(tmp_path / "user-hooks"))
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


def test_load_shortcuts_from_reads_one_file(clean_state):
    path = clean_state / "one.txt"
    path.write_text("app_next <N> next\n# comment\nbogus line\n",
                    encoding="utf-8")
    parsed = ybe.load_shortcuts_from(str(path))
    assert parsed == {"app_next": {"shortcut": "N", "label": "next"}}


def test_write_user_shortcuts_preserves_comments_and_upserts(clean_state):
    path = Path(ybe.config.USER_SHORTCUTS_FILE)
    path.write_text("# my remaps\napp_next <D> next\n\napp_undo <U> undo\n",
                    encoding="utf-8")
    ybe.write_user_shortcuts({"app_next": "Ctrl+N"}, [])
    text = path.read_text(encoding="utf-8")
    assert "# my remaps" in text
    assert "app_next <Ctrl+N> next" in text  # label kept, key replaced
    assert "app_undo <U> undo" in text
    assert ybe.load_shortcuts()["app_next"]["shortcut"] == "Ctrl+N"


def test_write_user_shortcuts_appends_and_resets(clean_state):
    path = Path(ybe.config.USER_SHORTCUTS_FILE)
    path.write_text("# keep\napp_next <D> next\n", encoding="utf-8")
    ybe.write_user_shortcuts({"app_save": "Ctrl+S"}, ["app_next"])
    text = path.read_text(encoding="utf-8")
    assert "# keep" in text
    assert "app_next" not in text
    assert "app_save <Ctrl+S>" in text
    assert ybe.user_shortcut_names() == {"app_save"}


def test_api_config_exposes_shortcut_defaults(clean_state):
    Path(ybe.config.SHORTCUTS_FILE).write_text("app_next <ArrowRight> next\n",
                                        encoding="utf-8")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["shortcut_defaults"]["app_next"]["shortcut"] == "ArrowRight"
    assert cfg["user_shortcut_names"] == []


def test_api_shortcuts_saves_override(clean_state):
    client = ybe.app.test_client()
    resp = client.post("/api/shortcuts", json={"set": {"app_next": "Ctrl+N"}})
    assert resp.status_code == 200
    cfg = resp.get_json()
    assert cfg["ok"] is True
    assert cfg["shortcuts"]["app_next"]["shortcut"] == "Ctrl+N"
    assert cfg["user_shortcut_names"] == ["app_next"]
    assert "app_next <Ctrl+N>" in Path(ybe.config.USER_SHORTCUTS_FILE).read_text(
        encoding="utf-8")


def test_api_shortcuts_resets_override(clean_state):
    ybe.write_user_shortcuts({"app_next": "Ctrl+N"}, [])
    client = ybe.app.test_client()
    cfg = client.post("/api/shortcuts", json={"reset": ["app_next"]}).get_json()
    assert cfg["ok"] is True
    assert "app_next" not in cfg["shortcuts"]  # no shipped default in the test
    assert cfg["user_shortcut_names"] == []


def test_api_shortcuts_readonly_rejected(clean_state):
    ybe.state.STATE["readonly"] = True
    client = ybe.app.test_client()
    resp = client.post("/api/shortcuts", json={"set": {"app_next": "N"}})
    assert resp.status_code == 403


def test_api_shortcuts_rejects_unknown_name(clean_state):
    resp = ybe.app.test_client().post("/api/shortcuts",
                                      json={"set": {"Nope": "N"}})
    assert resp.status_code == 400
    assert "unknown" in resp.get_json()["error"]


def test_api_shortcuts_rejects_invalid_value(clean_state):
    resp = ybe.app.test_client().post("/api/shortcuts",
                                      json={"set": {"app_next": "<bad>"}})
    assert resp.status_code == 400


def test_recent_cap_and_order(clean_state):
    assert ybe._load_recent() == []
    for i in range(12):
        ybe._push_recent(f"/d/{i}.yaml")
    recents = ybe._load_recent()
    assert len(recents) <= ybe.config.MAX_RECENT
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
    assert ybe.state.STATE["data_yaml"] == str(root / "data.yaml")
    assert [s["name"] for s in ybe.state.STATE["splits"]] == ["train", "val", "test"]
    assert ybe.state.STATE["images"]


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
    assert ybe.state.STATE["data_yaml"] == str(second / "data.yaml")


def test_resume_last_dataset_skips_missing_files(clean_state, tmp_path):
    good = make_dataset(tmp_path / "good")
    ybe._push_recent(str(good / "data.yaml"))
    ybe._push_recent(str(tmp_path / "gone" / "data.yaml"))
    assert ybe._resume_last_dataset() == str(good / "data.yaml")


def test_resume_last_dataset_none_clears_state(clean_state):
    ybe.state.STATE["data_yaml"] = "/stale/data.yaml"
    ybe.state.STATE["splits"] = [{"name": "train"}]
    ybe.state.STATE["images"] = [{"split": "train", "name": "a.jpg"}]
    assert ybe._resume_last_dataset() is None
    assert ybe.state.STATE["data_yaml"] is None
    assert ybe.state.STATE["splits"] == []
    assert ybe.state.STATE["images"] == []



# --------------------------------------------------------------------------- #
# dataset scanning
# --------------------------------------------------------------------------- #
def test_scan_splits_builds_splits(clean_state, tmp_path):
    root = make_dataset(tmp_path, names=("fire", "smoke"))
    clean_state_path = str(root / "data.yaml")
    ybe.state.STATE["data_yaml"] = clean_state_path
    splits = ybe.scan_splits()
    assert [s["name"] for s in splits] == ["train", "val", "test"]
    assert splits[0]["images_dir"].endswith("images/train")
    assert splits[0]["labels_dir"].endswith("labels/train")
    assert ybe.state.STATE["classes"] == ["fire", "smoke"]


def test_scan_splits_skips_missing_images_dir(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",))
    ybe.state.STATE["data_yaml"] = str(root / "data.yaml")
    splits = ybe.scan_splits()
    assert [s["name"] for s in splits] == ["train"]


def test_scan_splits_empty_without_data_yaml(clean_state):
    assert ybe.scan_splits() == []


def test_scan_images_sorted_and_filtered(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("b", "a"))
    ybe.state.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.state.STATE["splits"] = ybe.scan_splits()
    images = ybe.scan_images()
    assert [e["name"] for e in images] == ["a.jpg", "b.jpg"]
    assert all(e["split"] == "train" for e in images)


def test_read_classes_fallback_from_label_files(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",), names=())
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text("3 0.5 0.5 0.2 0.2\n",
                                                     encoding="utf-8")
    ybe.state.STATE["data_yaml"] = str(root / "data.yaml")
    ybe.state.STATE["splits"] = ybe.scan_splits()
    ybe.state.STATE["images"] = ybe.scan_images()
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
    assert "id=\"shortcutEditBtn\"" in html
    assert "id=\"shortcutSaveBtn\"" in html
    assert "id=\"shortcutCancelBtn\"" in html
    assert "id=\"autoSaveSw\"" in html
    assert "id=\"filterPanelBody\"" in html
    assert "id=\"filterPanelApply\"" in html
    assert "id=\"filterAddBtn\"" in html
    assert "class=\"sub-tabs\"" in html
    assert "data-sub=\"chain\"" in html
    assert "data-sub=\"create\"" in html
    assert "data-sub=\"library\"" in html
    assert "data-sub=\"existing\"" in html
    assert "id=\"filterDefs\"" in html
    assert "id=\"actionDefs\"" in html
    assert "id=\"hookDefs\"" in html
    assert "id=\"boxFloat\"" in html
    assert "id=\"navFloat\"" in html
    assert "id=\"saveFloat\"" in html
    assert "id=\"actionsFloat\"" in html
    assert "id=\"dockSide\"" in html
    assert "id=\"dockBottom\"" in html
    assert "id=\"panelSideSel\"" in html
    assert "id=\"boxesDockSel\"" in html
    assert "id=\"actionsDockSel\"" in html
    assert "id=\"navDockSel\"" in html
    assert "id=\"saveDockSel\"" in html
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
    Path(ybe.config.CONFIG_FILE).write_text(
        json.dumps({"settings": {"autoSave": "1", "ybe_panel_side": "left"}}),
        encoding="utf-8",
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


# --------------------------------------------------------------------------- #
# unified config file (recent + views + settings in one place)
# --------------------------------------------------------------------------- #
def test_config_file_holds_recent_views_and_settings(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    ybe._push_recent(str(root / "data.yaml"))
    load_into_state(root)
    ybe._save_view(str(root / "data.yaml"), "train", [{"name": "OnlyA"}])
    ybe._update_settings({"autoSave": "1"})

    cfg = read_config()
    assert cfg["recent"] == [str(root / "data.yaml")]
    assert cfg["views"][str(root / "data.yaml")]["split"] == "train"
    assert cfg["settings"] == {"autoSave": "1"}
    # one file, and the legacy per-purpose files are not created
    assert Path(ybe.config.CONFIG_FILE).is_file()
    assert not Path(ybe.config.RECENT_FILE).exists()
    assert not Path(ybe.config.VIEW_FILE).exists()
    assert not Path(ybe.config.SETTINGS_FILE).exists()


def test_legacy_files_migrate_into_config(clean_state):
    Path(ybe.config.RECENT_FILE).write_text(json.dumps(["/d/a.yaml"]), encoding="utf-8")
    Path(ybe.config.VIEW_FILE).write_text(
        json.dumps({"/d/a.yaml": {"split": "train"}}), encoding="utf-8"
    )
    Path(ybe.config.SETTINGS_FILE).write_text(json.dumps({"autoSave": "1"}), encoding="utf-8")

    assert ybe._load_recent() == ["/d/a.yaml"]
    assert ybe._load_views()["/d/a.yaml"]["split"] == "train"
    assert ybe._load_settings() == {"autoSave": "1"}
    assert read_config()["views"]["/d/a.yaml"]["split"] == "train"
    # the old files are removed once their contents are in config.json
    assert not Path(ybe.config.RECENT_FILE).exists()
    assert not Path(ybe.config.VIEW_FILE).exists()
    assert not Path(ybe.config.SETTINGS_FILE).exists()


def test_corrupt_config_is_not_overwritten(clean_state):
    Path(ybe.config.CONFIG_FILE).write_text("{ not json", encoding="utf-8")
    assert ybe._load_recent() == []
    assert Path(ybe.config.CONFIG_FILE).read_text(encoding="utf-8") == "{ not json"


def test_settings_mirror_last_image_cross_browser(clean_state):
    last = json.dumps({
        "dataYaml": "/d/data.yaml",
        "bySplit": {"train": "0000016.jpg"},
        "last": {"split": "train", "name": "0000016.jpg"},
    })
    client = ybe.app.test_client()
    client.post("/api/settings", json={"settings": {"ybe_last_image": last}})
    # a fresh browser gets it back from /api/config
    cfg = client.get("/api/config").get_json()
    assert cfg["settings"]["ybe_last_image"] == last


def test_api_config_reports_debug_flag(clean_state):
    ybe.state.STATE["debug"] = True
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


def test_api_annotations_get_empty_without_file(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/annotations?key=train/a.jpg").get_json() == {
        "boxes": []}


def test_api_annotations_get_parses_existing(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text(
        "1 0.5 0.25 0.2 0.4\nbad line\n", encoding="utf-8"
    )
    client = ybe.app.test_client()
    load_dataset(client, root)
    data = client.get("/api/annotations?key=train/a.jpg").get_json()
    assert data["boxes"] == [{"class": 1, "cx": 0.5, "cy": 0.25, "w": 0.2, "h": 0.4}]


def test_api_annotations_post_writes_clamped(clean_state, tmp_path):
    root = make_dataset(tmp_path)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/annotations?key=train/a.jpg", json={"boxes": [
        {"class": 2, "cx": -1.0, "cy": 0.5, "w": 2.0, "h": 0.1},
        {"class": -3, "cx": 0.4, "cy": 0.4, "w": 0.2, "h": 0.2},
    ]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] and resp.get_json()["count"] == 2
    written = (root / "labels" / "train" / "a.txt").read_text().splitlines()
    assert written[0].startswith("2 0.000000 0.500000 1.000000 0.100000")
    assert written[1].startswith("0 0.400000 0.400000")


def test_api_annotations_post_invalid_box(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/annotations?key=train/a.jpg", json={"boxes": [{"class": "x", "cx": 0, "cy": 0, "w": 0, "h": 0}]})
    assert resp.status_code == 400


def test_api_annotations_post_readonly_rejected(clean_state, tmp_path, monkeypatch):
    ybe.state.STATE["readonly"] = True
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    cfg = client.get("/api/config").get_json()
    assert cfg["readonly"] is True
    resp = client.post("/api/annotations?key=train/a.jpg", json={"boxes": []})
    assert resp.status_code == 403


def test_api_annotations_out_of_range_404(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.get("/api/annotations?key=train/nope.jpg").status_code == 404


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
    monkeypatch.setattr(ybe.config, "ACTION_TIMEOUT", 0.2)
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


@pytest.mark.parametrize(
    "name",
    [
        "app_select_next_box",
        "app_select_prev_box",
        "app_copy_labels_from_prev",
    ],
)
def test_api_action_run_accepts_new_client_actions(clean_state, tmp_path, name):
    write_action(tmp_path, "NewClients.yaml", f"after_success:\n  - {name}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "NewClients", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert payload["client_action"] == name


def test_api_action_run_substitutes_app_dir(clean_state, tmp_path):
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo {APP_DIR}\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    payload = client.post(
        "/api/actions/run", json={"action": "on_after_save", "target": "train/a.jpg"}
    ).get_json()
    assert payload["ok"] is True
    assert ybe.config.BASE_DIR in payload["stdout"]


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
    assert ybe.config.YBX_HOME in payload["stdout"]
    assert ybe.config.USER_SCRIPT_DIR in payload["stdout"]
    assert ybe.config.APP_SCRIPT_DIR in payload["stdout"]


def test_run_command_logs_cwd(clean_state, capsys):
    state = {"stdout": [], "stderr": [], "commands": [], "exit_code": 0}
    ybe._run_command(state, "true")
    assert f"cwd={ybe.config.YBX_HOME}" in capsys.readouterr().err


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
    ybe.state.STATE["keep_pipe"] = True
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
    assert first["uid"] in ybe.state.EXECUTIONS
    pipe = first["pipe_path"]
    assert Path(pipe).is_file()
    # the client reports back; the chain has no more entries, so it finishes
    done = client.post(
        "/api/actions/run", json={"uid": first["uid"], "result": {"ok": True}}
    ).get_json()
    assert done["ok"] is True
    assert "client_action" not in done
    assert first["uid"] not in ybe.state.EXECUTIONS
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
    assert first["uid"] not in ybe.state.EXECUTIONS
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
# filters/ (YAML-defined image-list filters)
# --------------------------------------------------------------------------- #
def test_load_filters_one_yaml_per_filter(clean_state):
    write_filter(clean_state, "Odd.yaml", filter_yaml(py_step("copy.py"), name="Odd"))
    write_filter(clean_state, "Even.yaml", filter_yaml(py_step("copy.py"), name="Even"))
    filters, errors = ybe.load_filters()
    assert sorted(filters) == ["Even", "Odd"]
    assert errors == []


def test_load_filters_name_key_wins(clean_state):
    write_filter(clean_state, "File.yaml",
                 filter_yaml(py_step("copy.py"), name="Nice"))
    assert list(ybe.load_filters()[0]) == ["Nice"]


def test_load_filters_defaults_to_file_name(clean_state):
    write_filter(clean_state, "Odd.yaml", filter_yaml(py_step("copy.py")))
    assert list(ybe.load_filters()[0]) == ["Odd"]


def test_load_filters_user_override_wins(clean_state):
    write_filter(clean_state, "Odd.yaml",
                 filter_yaml(py_step("copy.py"), name="Odd", description="repo"),
                 subdir="app-filters")
    write_filter(clean_state, "Odd.yaml",
                 filter_yaml(py_step("copy.py"), name="Odd", description="user"))
    assert ybe.load_filters()[0]["Odd"]["description"] == "user"


def test_load_filters_ignores_non_yaml(clean_state):
    (clean_state / "filters").mkdir()
    (clean_state / "filters" / "notes.txt").write_text("x", encoding="utf-8")
    assert ybe.load_filters()[0] == {}


def test_load_filters_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(tmp_path / "nope-user"))
    assert ybe.load_filters() == ({}, [])


def test_load_filters_skips_inactive(clean_state):
    write_filter(clean_state, "Off.yaml",
                 filter_yaml(py_step("copy.py"), active=False))
    assert ybe.load_filters()[0] == {}


def test_load_filters_skips_template_without_steps(clean_state):
    write_filter(clean_state, "Tpl.yaml", "# just comments\nname: Template\n")
    assert ybe.load_filters()[0] == {}


def test_load_filters_parses_arguments(clean_state):
    body = (
        "name: Args\n"
        "description: demo\n"
        "arguments:\n"
        "  - name: every\n"
        "    required: true\n"
        '    default: "2"\n'
        '    options: ["2", "3"]\n'
        "  - name: reverse\n"
        "    options:\n"
        "      - false\n"
        "      - true\n"
        "steps:\n"
        "  - echo hi\n"
    )
    write_filter(clean_state, "Args.yaml", body)
    flt = ybe.load_filters()[0]["Args"]
    assert flt["description"] == "demo"
    assert flt["arguments"] == [
        {"name": "every", "required": True, "default": "2", "options": ["2", "3"]},
        {"name": "reverse", "required": False, "default": None,
         "options": ["false", "true"]},
    ]


def test_load_filters_rejects_invalid_argument_name(clean_state):
    write_filter(clean_state, "Bad.yaml",
                 filter_yaml("echo hi", name="Bad", arguments=[{"name": "1bad"}]))
    filters, errors = ybe.load_filters()
    assert filters == {}
    assert len(errors) == 1 and "invalid argument name" in errors[0]


def test_load_filters_rejects_reserved_placeholder(clean_state):
    write_filter(clean_state, "Bad.yaml",
                 filter_yaml("echo hi", name="Bad", arguments=[{"name": "app_dir"}]))
    filters, errors = ybe.load_filters()
    assert filters == {}
    assert "reserved placeholder" in errors[0]


def test_load_filters_rejects_duplicate_argument(clean_state):
    write_filter(clean_state, "Bad.yaml",
                 filter_yaml("echo hi", name="Bad",
                             arguments=[{"name": "x"}, {"name": "x"}]))
    filters, errors = ybe.load_filters()
    assert filters == {}
    assert "duplicate argument" in errors[0]


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


def test_effective_filter_arguments_merges_defaults():
    flt = {"arguments": [
        {"name": "a", "required": False, "default": "1", "options": None},
        {"name": "b", "required": False, "default": None, "options": None},
    ]}
    assert ybe.effective_filter_arguments(flt, {"a": "9"}) == {"a": "9", "b": ""}
    assert ybe.effective_filter_arguments(flt, {}) == {"a": "1", "b": ""}


def test_normalize_filter_chain_fills_args_and_checks_required(clean_state):
    write_filter(clean_state, "Args.yaml",
                 filter_yaml("echo hi", name="Args",
                             arguments=[{"name": "n", "required": True}]))
    chain, error = ybe._normalize_filter_chain(
        [{"name": "Args", "arguments": {"n": "3"}}])
    assert error is None
    assert chain == [{"name": "Args", "arguments": {"n": "3"}}]
    _, error = ybe._normalize_filter_chain([{"name": "Args", "arguments": {}}])
    assert "is required" in error


def test_load_filters_parses_class_names_token(clean_state):
    body = (
        "name: ByClass\n"
        "arguments:\n"
        "  - name: class_name\n"
        "    options: {DATASET_CLASS_NAMES}\n"
        "steps:\n"
        "  - echo {CLASS_NAME}\n"
    )
    write_filter(clean_state, "ByClass.yaml", body)
    arg = ybe.load_filters()[0]["ByClass"]["arguments"][0]
    assert arg["options"] == [ybe.FILTER_CLASS_NAMES_TOKEN]


def test_resolve_filter_options_expands_class_names():
    token = ybe.FILTER_CLASS_NAMES_TOKEN
    assert ybe.resolve_filter_options([token], ["fire", "smoke"]) == ["fire", "smoke"]
    assert ybe.resolve_filter_options(["a", token], ["a", "b"]) == ["a", "b"]
    assert ybe.resolve_filter_options(None, ["x"]) is None


def test_normalize_filter_chain_rejects_value_outside_options(clean_state):
    write_filter(clean_state, "ByClass.yaml",
                 filter_yaml("echo hi", name="ByClass",
                             arguments=[{"name": "c", "options": "[alpha, beta]"}]))
    ybe.state.STATE["classes"] = ["alpha", "beta"]
    _, error = ybe._normalize_filter_chain(
        [{"name": "ByClass", "arguments": {"c": "gamma"}}])
    assert "must be one of" in error
    chain, error = ybe._normalize_filter_chain(
        [{"name": "ByClass", "arguments": {"c": "beta"}}])
    assert error is None and chain[0]["arguments"]["c"] == "beta"


def test_shipped_class_filters_use_class_token(monkeypatch):
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(Path(ybe.config.BASE_DIR) / "filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(Path(ybe.config.BASE_DIR) / "nope"))
    filters, errors = ybe.load_filters()
    assert errors == []
    for name in ("Contains class", "Does not contain class"):
        arg = filters[name]["arguments"][0]
        assert arg["name"] == "class_name"
        assert arg["required"] is True
        assert arg["options"] == [ybe.FILTER_CLASS_NAMES_TOKEN]


def test_class_filter_script_contains_and_not_contains(clean_state, tmp_path, monkeypatch):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b", "c"))
    labels = root / "labels" / "train"
    labels.mkdir(parents=True, exist_ok=True)
    (labels / "a.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    (labels / "b.txt").write_text("1 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    load_into_state(root)
    ybe.state.STATE["classes"] = ["fire", "smoke"]
    monkeypatch.setattr(ybe.config, "USER_SCRIPT_DIR", str(Path(ybe.config.BASE_DIR) / "scripts"))

    def class_step(extra):
        return (f'"{sys.executable}" {{USER_SCRIPT_DIR}}/class_filter.py '
                f'{{DATA_YAML_PATH}} {{SPLIT}} {{INPUT_PIPE}} {{OUTPUT_PIPE}} {extra}')

    write_filter(clean_state, "Contains.yaml",
                 filter_yaml(class_step("--class {CLASS_NAME}"),
                             name="Contains",
                             arguments=[{"name": "class_name", "required": True,
                                         "options": ybe.FILTER_CLASS_NAMES_TOKEN}]))
    write_filter(clean_state, "NotContains.yaml",
                 filter_yaml(class_step("--class {CLASS_NAME} --invert"),
                             name="NotContains",
                             arguments=[{"name": "class_name", "required": True,
                                         "options": ybe.FILTER_CLASS_NAMES_TOKEN}]))
    chain, error = ybe._normalize_filter_chain(
        [{"name": "Contains", "arguments": {"class_name": "fire"}}])
    assert error is None
    result = ybe.run_filter_chain(chain, "train")
    assert result["ok"] and [e["name"] for e in result["images"]] == ["a.jpg"]

    result = ybe.run_filter_chain(
        [{"name": "NotContains", "arguments": {"class_name": "fire"}}], "train")
    assert result["ok"] and [e["name"] for e in result["images"]] == ["b.jpg", "c.jpg"]


def _load_package_script(name):
    """Import a tags-extension helper by path (not on sys.path)."""
    path = Path(ybe.config.BASE_DIR) / "extensions" / "tags" / "scripts" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tag_image_swaps_only_the_images_segment(tmp_path):
    mod = _load_package_script("tag_image.py")
    image = tmp_path / "images_backup" / "dataset" / "images" / "train" / "a.jpg"
    # a folder named `images_backup` must be left alone; only the `images` segment
    # is swapped, matching the app's own rule.
    assert mod.tag_file_path(str(image), "") == str(
        tmp_path / "images_backup" / "dataset" / "tags" / "train" / "a.txt")


def test_tag_image_uses_custom_tags_dir(tmp_path):
    mod = _load_package_script("tag_image.py")
    image = tmp_path / "dataset" / "images" / "train" / "a.jpg"
    custom = tmp_path / "mytags" / "train"
    assert mod.tag_file_path(str(image), str(custom)) == str(custom / "a.txt")


def test_run_filter_substitutes_placeholders_and_args(clean_state):
    log = clean_state / "args.txt"
    write_script(clean_state, "log.py",
                 f"import sys\nopen({str(log)!r}, 'w').write('|'.join(sys.argv[1:]))\n")
    write_filter(clean_state, "Args.yaml",
                 filter_yaml(py_step("log.py", extra="{DATA_YAML_PATH} {SPLIT} {EVERY}"),
                             name="Args", arguments=[{"name": "every", "default": '"7"'}]))
    result = ybe.run_filter("Args", "/d/data.yaml", "train", "in.txt", "out.txt",
                            {"every": "3"})
    assert result["ok"] is True
    assert log.read_text(encoding="utf-8") == "in.txt|out.txt|/d/data.yaml|train|3"


def test_run_filter_python_placeholder_runs(clean_state):
    log = clean_state / "exe.txt"
    write_script(clean_state, "log.py",
                 f"import sys\nopen({str(log)!r}, 'w').write(sys.executable)\n")
    write_filter(clean_state, "Py.yaml",
                 filter_yaml("{PYTHON} {USER_SCRIPT_DIR}/log.py {INPUT_PIPE} {OUTPUT_PIPE}",
                             name="Py"))
    assert ybe.run_filter("Py", "", "train", "in", "out")["ok"] is True
    assert Path(log.read_text(encoding="utf-8")).resolve() == Path(sys.executable).resolve()


def test_run_filter_uses_argument_default(clean_state):
    log = clean_state / "args.txt"
    write_script(clean_state, "log.py",
                 f"import sys\nopen({str(log)!r}, 'w').write('|'.join(sys.argv[1:]))\n")
    write_filter(clean_state, "Args.yaml",
                 filter_yaml(py_step("log.py", extra="{EVERY}"), name="Args",
                             arguments=[{"name": "every", "default": '"7"'}]))
    assert ybe.run_filter("Args", "", "", "in.txt", "out.txt", {})["ok"] is True
    assert log.read_text(encoding="utf-8").endswith("|7")


def test_run_filter_empty_split_for_all_splits(clean_state):
    log = clean_state / "split.txt"
    write_script(clean_state, "log.py",
                 f"import sys\nopen({str(log)!r}, 'w').write(sys.argv[3])\n")
    write_filter(clean_state, "Args.yaml",
                 filter_yaml(py_step("log.py", extra="{SPLIT}"), name="Args"))
    assert ybe.run_filter("Args", "", "", "in.txt", "out.txt")["ok"] is True
    assert log.read_text(encoding="utf-8") == ""


def test_run_filter_unknown(clean_state):
    assert ybe.run_filter("Nope", "", "train", "in", "out")["ok"] is False


def test_run_filter_nonzero_exit_reports_stderr(clean_state):
    write_script(clean_state, "boom.py",
                 "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
    write_filter(clean_state, "Boom.yaml", filter_yaml(py_step("boom.py"), name="Boom"))
    result = ybe.run_filter("Boom", "", "train", "in", "out")
    assert result["ok"] is False and "boom" in result["error"]


def test_run_filter_timeout(clean_state, monkeypatch):
    monkeypatch.setattr(ybe.config, "FILTER_TIMEOUT", 0.2)
    write_script(clean_state, "slow.py", "import time\ntime.sleep(5)\n")
    write_filter(clean_state, "Slow.yaml", filter_yaml(py_step("slow.py"), name="Slow"))
    result = ybe.run_filter("Slow", "", "train", "in", "out")
    assert result["ok"] is False and "timed out" in result["error"]


def test_filter_multiple_steps_share_pipes(clean_state):
    log = clean_state / "args.txt"
    write_script(clean_state, "log.py",
                 f"import sys\nopen({str(log)!r}, 'a').write('|'.join(sys.argv[1:]) + '\\n')\n")
    write_filter(clean_state, "Two.yaml",
                 filter_yaml([py_step("log.py"), py_step("log.py")], name="Two"))
    assert ybe.run_filter("Two", "", "train", "in.txt", "out.txt")["ok"] is True
    assert log.read_text(encoding="utf-8").splitlines() == [
        "in.txt|out.txt", "in.txt|out.txt"]


def test_filter_chain_feeds_output_to_next(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    load_into_state(root)
    second_input = clean_state / "second_input.txt"
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_script(clean_state, "record.py", filter_recording_input(second_input))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    write_filter(clean_state, "Record.yaml", filter_yaml(py_step("record.py"), name="Record"))
    result = ybe.run_filter_chain(
        [{"name": "OnlyA", "arguments": {}}, {"name": "Record", "arguments": {}}],
        "train")
    assert result["ok"] is True
    assert [e["name"] for e in result["images"]] == ["a.jpg"]
    # the second filter saw exactly the first filter's output
    lines = second_input.read_text(encoding="utf-8").split()
    assert [Path(p).name for p in lines] == ["a.jpg"]


def test_filter_chain_first_input_is_active_split(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    load_into_state(root)
    seen = clean_state / "seen.txt"
    write_script(clean_state, "record.py", filter_recording_input(seen))
    write_filter(clean_state, "Record.yaml", filter_yaml(py_step("record.py"), name="Record"))
    assert ybe.run_filter_chain([{"name": "Record"}], "train")["ok"] is True
    assert seen.read_text(encoding="utf-8").split() == [
        str(root / "images" / "train" / "a.jpg")
    ]
    assert ybe.run_filter_chain([{"name": "Record"}], "")["ok"] is True
    assert set(seen.read_text(encoding="utf-8").split()) == {
        str(root / "images" / "train" / "a.jpg"),
        str(root / "images" / "val" / "a.jpg"),
    }


def test_filter_chain_stops_at_first_failure(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    after_log = clean_state / "after.txt"
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_script(clean_state, "boom.py", "import sys\nsys.exit(4)\n")
    write_script(clean_state, "record.py", filter_recording_input(after_log))
    write_filter(clean_state, "Copy.yaml", filter_yaml(py_step("copy.py"), name="Copy"))
    write_filter(clean_state, "Boom.yaml", filter_yaml(py_step("boom.py"), name="Boom"))
    write_filter(clean_state, "After.yaml", filter_yaml(py_step("record.py"), name="After"))
    result = ybe.run_filter_chain(
        [{"name": "Copy"}, {"name": "Boom"}, {"name": "After"}], "train")
    assert result["ok"] is False and 'Filter "Boom" failed' in result["error"]
    assert not after_log.exists()


def test_filter_chain_cleans_scratch_dir(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Copy.yaml", filter_yaml(py_step("copy.py"), name="Copy"))
    result = ybe.run_filter_chain([{"name": "Copy"}], "train")
    assert result["ok"] is True and result["chain_dir"] is None
    assert list(Path(ybe.config.FILTER_PIPES_DIR).glob("chain_*")) == []


def test_filter_chain_keeps_scratch_dir_when_asked(clean_state, tmp_path):
    ybe.state.STATE["keep_filter_pipes"] = True
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    load_into_state(root)
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Copy.yaml", filter_yaml(py_step("copy.py"), name="Copy"))
    result = ybe.run_filter_chain([{"name": "Copy"}], "train")
    assert result["ok"] is True
    assert Path(result["chain_dir"]).is_dir()
    assert (Path(result["chain_dir"]) / "input_0.txt").is_file()


def test_api_config_reports_filters(clean_state):
    write_filter(clean_state, "Odd.yaml",
                 filter_yaml("echo hi", name="Odd", description="d",
                             arguments=[{"name": "n", "required": True, "default": '"1"'}]))
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["filters"] == [{
        "name": "Odd", "description": "d",
        "arguments": [{"name": "n", "required": True, "default": "1", "options": None}],
    }]
    assert cfg["active_filters"] == []
    assert cfg["filter_errors"] == []


def test_api_config_reports_filter_errors(clean_state):
    write_filter(clean_state, "Bad.yaml",
                 filter_yaml("echo hi", name="Bad", arguments=[{"name": "1x"}]))
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["filters"] == []
    assert len(cfg["filter_errors"]) == 1


def test_api_filter_set_chain_with_arguments_and_clear(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    write_filter(clean_state, "Copy.yaml",
                 filter_yaml(py_step("copy.py"), name="Copy",
                             arguments=[{"name": "n", "default": '"1"'}]))
    client = ybe.app.test_client()
    load_dataset(client, root)

    cfg = client.post("/api/filter", json={"filters": [
        {"name": "OnlyA"}, {"name": "Copy", "arguments": {"n": "5"}},
    ]}).get_json()
    assert cfg["ok"] is True
    assert cfg["active_filters"] == [
        {"name": "OnlyA", "arguments": {}},
        {"name": "Copy", "arguments": {"n": "5"}},
    ]
    assert [e["name"] for e in cfg["images"]] == ["a.jpg"]

    cfg = client.post("/api/filter", json={"filters": []}).get_json()
    assert cfg["active_filters"] == []
    assert len(cfg["images"]) == 2


def test_api_filter_requires_required_argument(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Req.yaml",
                 filter_yaml(py_step("copy.py"), name="Req",
                             arguments=[{"name": "n", "required": True}]))
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/filter", json={"filters": [{"name": "Req"}]})
    assert resp.status_code == 400
    assert "is required" in resp.get_json()["error"]


def test_api_filter_accepts_legacy_single_name(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filter": "OnlyA"}).get_json()
    assert cfg["active_filters"] == [{"name": "OnlyA", "arguments": {}}]
    assert [e["name"] for e in cfg["images"]] == ["a.jpg"]


def test_api_filter_accepts_legacy_name_list(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": ["OnlyA"]}).get_json()
    assert cfg["active_filters"] == [{"name": "OnlyA", "arguments": {}}]


def test_api_filter_clear_with_legacy_null(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": [{"name": "OnlyA"}]})
    cfg = client.post("/api/filter", json={"filter": None}).get_json()
    assert cfg["active_filters"] == []


def test_api_filter_requires_dataset(clean_state):
    resp = ybe.app.test_client().post("/api/filter", json={"filters": ["X"]})
    assert resp.status_code == 400
    assert "no dataset" in resp.get_json()["error"]


def test_api_filter_unknown(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/filter", json={"filters": [{"name": "Nope"}]})
    assert resp.status_code == 400
    assert "unknown filter" in resp.get_json()["error"]


def test_api_filter_rejects_inactive(clean_state, tmp_path):
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Off.yaml",
                 filter_yaml(py_step("copy.py"), name="Off", active=False))
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    resp = client.post("/api/filter", json={"filters": [{"name": "Off"}]})
    assert resp.status_code == 400
    assert "unknown filter" in resp.get_json()["error"]


def test_api_filter_can_span_splits_when_all(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Copy.yaml", filter_yaml(py_step("copy.py"), name="Copy"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": [{"name": "Copy"}]}).get_json()
    assert [(e["split"], e["name"]) for e in cfg["images"]] == [
        ("train", "a.jpg"),
        ("val", "a.jpg"),
    ]


def test_api_filter_reports_unknown_paths(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(
        clean_state, "sloppy.py",
        "import sys\n"
        "text = open(sys.argv[1], encoding='utf-8').read()\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(text + '/nope/missing.jpg\\n')\n",
    )
    write_filter(clean_state, "Sloppy.yaml", filter_yaml(py_step("sloppy.py"), name="Sloppy"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": [{"name": "Sloppy"}]}).get_json()
    assert cfg["active_filters"] == [{"name": "Sloppy", "arguments": {}}]
    assert "ignored" in (cfg["filter_error"] or "")


def test_api_filter_allowed_in_readonly(clean_state, tmp_path):
    ybe.state.STATE["readonly"] = True
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Keep.yaml", filter_yaml(py_step("copy.py"), name="Keep"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/filter", json={"filters": [{"name": "Keep"}]})
    assert resp.status_code == 200
    assert resp.get_json()["active_filters"] == [{"name": "Keep", "arguments": {}}]


def test_api_data_clears_active_filters(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_filter(clean_state, "Keep.yaml", filter_yaml(py_step("copy.py"), name="Keep"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": [{"name": "Keep"}]})
    assert ybe.state.STATE["active_filters"] == [{"name": "Keep", "arguments": {}}]
    load_dataset(client, root)
    assert ybe.state.STATE["active_filters"] == []


def test_api_split_reruns_active_chain(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a", "b"))
    write_script(clean_state, "copy.py", FILTER_COPY)
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "Copy.yaml", filter_yaml(py_step("copy.py"), name="Copy"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": [{"name": "Copy"}, {"name": "OnlyA"}]})
    cfg = client.post("/api/split", json={"split": "val"}).get_json()
    assert cfg["ok"] is True and cfg["active_split"] == "val"
    assert cfg["images"] == [{"split": "val", "name": "a.jpg"}]


def test_api_split_filter_failure_keeps_state(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train", "val"), images=("a",))
    write_script(
        clean_state, "pick.py",
        "import sys\n"
        "if sys.argv[3] == 'val':\n"
        "    sys.exit(1)\n"
        "open(sys.argv[2], 'w').write(open(sys.argv[1]).read())\n",
    )
    write_filter(clean_state, "Pick.yaml",
                 filter_yaml(py_step("pick.py", extra="{SPLIT}"), name="Pick"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": [{"name": "Pick"}]})
    resp = client.post("/api/split", json={"split": "val"})
    assert resp.status_code == 400
    assert ybe.state.STATE["active_split"] is None  # unchanged
    assert ybe.state.STATE["active_filters"] == [{"name": "Pick", "arguments": {}}]


def test_api_images_rescan_reruns_chain(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/filter", json={"filters": [{"name": "OnlyA"}]})
    (root / "images" / "train" / "a.jpg").unlink()
    data = client.post("/api/images/rescan").get_json()
    assert data["active_filters"] == [{"name": "OnlyA", "arguments": {}}]
    assert data["images"] == []


def test_api_image_resolves_by_key_regardless_of_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a", "b"))
    write_script(clean_state, "only_b.py", filter_selecting("b.jpg"))
    write_filter(clean_state, "OnlyB.yaml", filter_yaml(py_step("only_b.py"), name="OnlyB"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    cfg = client.post("/api/filter", json={"filters": [{"name": "OnlyB"}]}).get_json()
    assert [e["name"] for e in cfg["images"]] == ["b.jpg"]
    # identity reads are not affected by the filter: both files still resolve
    assert client.get("/api/image?key=train/a.jpg").status_code == 200
    assert client.get("/api/image?key=train/b.jpg").status_code == 200


# --------------------------------------------------------------------------- #
# per-dataset view persistence
# --------------------------------------------------------------------------- #
def test_view_state_saved_on_split_and_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/split", json={"split": "train"})
    client.post("/api/filter", json={"filters": [{"name": "OnlyA"}]})
    assert ybe._load_views()[str(root / "data.yaml")] == {
        "split": "train",
        "filters": [{"name": "OnlyA", "arguments": {}}],
    }


def test_resume_restores_saved_view(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    client = ybe.app.test_client()
    load_dataset(client, root)
    client.post("/api/split", json={"split": "train"})
    client.post("/api/filter", json={"filters": [{"name": "OnlyA"}]})
    # simulate a server restart: in-memory state resets, then resume reopens the
    # last dataset (RECENT_FILE persists) and must restore its split/filter chain
    ybe.state.STATE.clear()
    ybe.state.STATE.update(DEFAULT_STATE)
    assert ybe._resume_last_dataset() == str(root / "data.yaml")
    assert ybe.state.STATE["active_split"] == "train"
    assert ybe.state.STATE["active_filters"] == [{"name": "OnlyA", "arguments": {}}]


def test_restore_view_accepts_legacy_single_filter(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    load_into_state(root)
    ybe._save_view(str(root / "data.yaml"), "train", [])
    views = ybe._load_views()
    views[str(root / "data.yaml")] = {"split": "train", "filter": "OnlyA"}
    write_config(views=views)
    ybe._restore_view(str(root / "data.yaml"))
    assert ybe.state.STATE["active_filters"] == [{"name": "OnlyA", "arguments": {}}]


def test_restore_view_accepts_legacy_name_list(clean_state, tmp_path):
    root = make_dataset(tmp_path, splits=("train",), images=("a",))
    write_script(clean_state, "only_a.py", filter_selecting("a.jpg"))
    write_filter(clean_state, "OnlyA.yaml", filter_yaml(py_step("only_a.py"), name="OnlyA"))
    load_into_state(root)
    ybe._save_view(str(root / "data.yaml"), "train", [])
    views = ybe._load_views()
    views[str(root / "data.yaml")] = {"split": "train", "filters": ["OnlyA"]}
    write_config(views=views)
    ybe._restore_view(str(root / "data.yaml"))
    assert ybe.state.STATE["active_filters"] == [{"name": "OnlyA", "arguments": {}}]


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
    assert "a" not in ybe.state.CLIENTS
    assert "b" in ybe.state.CLIENTS


def test_presence_prunes_stale_clients(clean_state):
    ybe.state.CLIENTS["old"] = time.monotonic() - (ybe.state.PRESENCE_TTL + 1)
    client = ybe.app.test_client()
    data = client.post("/api/presence", json={"cid": "new"}).get_json()
    assert data["count"] == 1
    assert "old" not in ybe.state.CLIENTS
    assert "new" in ybe.state.CLIENTS


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
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: "2.3.0")
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

    monkeypatch.setattr(ybe.update, "fetch_latest_version", fake)
    info = ybe.check_for_update(now=1000 + ybe.config.UPDATE_CHECK_INTERVAL - 1)
    assert info["latest_version"] == "2.3.0"
    assert calls == []


def test_check_for_update_refetches_after_interval(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 1000, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: "2.4.0")
    info = ybe.check_for_update(now=1000 + ybe.config.UPDATE_CHECK_INTERVAL + 1)
    assert info["latest_version"] == "2.4.0"


def test_check_for_update_force_bypasses_cache(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 10, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: "2.4.0")
    info = ybe.check_for_update(force=True, now=11)
    assert info["latest_version"] == "2.4.0"


def test_check_for_update_offline_marks_not_available(clean_state, monkeypatch):
    _write_version(clean_state, "2.2.0")
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: None)
    info = ybe.check_for_update(now=1000)
    assert info["update_available"] is False
    assert info["latest_version"] is None


def test_check_for_update_version_change_refetches(clean_state, monkeypatch):
    _write_version(clean_state, "2.3.0")
    (clean_state / "update.json").write_text(json.dumps({
        "checked_at": 1000, "current_version": "2.2.0", "latest_version": "2.3.0",
    }), encoding="utf-8")
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: "2.3.0")
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
    monkeypatch.setattr(ybe.update, "fetch_latest_version", lambda timeout=None: "2.5.0")
    data = ybe.app.test_client().post(
        "/api/update-check", json={"force": True}
    ).get_json()
    assert data["update"]["latest_version"] == "2.5.0"


def test_configure_home_repoints_update_file(clean_state, tmp_path):
    target = tmp_path / "elsewhere"
    ybe.configure_home(str(target))
    assert ybe.config.UPDATE_CHECK_FILE == str(target / ".update_check.json")


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

    monkeypatch.setattr(ybe.update, "_http_get_text", fake_get)
    assert ybe.fetch_latest_version() == "2.6.0"


def test_fetch_latest_version_falls_back_to_release_without_tags(monkeypatch):
    def fake_get(url, timeout=None):
        if url.endswith("/releases/latest"):
            return '{"tag_name": "v3.1.0"}'
        if url.endswith("/tags"):
            return "[]"
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ybe.update, "_http_get_text", fake_get)
    assert ybe.fetch_latest_version() == "3.1.0"


# --------------------------------------------------------------------------- #
# extension api_version + authoring (Settings > Actions / Hooks / Filters)
# --------------------------------------------------------------------------- #
def test_parse_action_file_reads_api_version():
    parsed = ybe._parse_action_file("api_version: 1\nsteps:\n  - echo hi\n")
    assert parsed["api_version"] == 1
    assert ybe._parse_action_file("steps:\n  - echo hi\n")["api_version"] is None
    assert ybe._parse_action_file("api_version: abc\nsteps:\n  - x\n")["api_version"] is None


def test_parse_filter_file_reads_api_version():
    parsed = ybe._parse_filter_file("api_version: 2\nsteps:\n  - echo hi\n")
    assert parsed["api_version"] == 2
    assert ybe._parse_filter_file("steps:\n  - echo hi\n")["api_version"] is None


def test_api_version_status():
    assert ybe.api_version_status(None) == "outdated"
    assert ybe.api_version_status("1") == "outdated"
    assert ybe.api_version_status(0) == "outdated"
    assert ybe.api_version_status(ybe.config.EXTENSION_API_VERSION) == "current"
    assert ybe.api_version_status(ybe.config.EXTENSION_API_VERSION + 1) == "newer"


def test_unversioned_files_still_load(clean_state):
    # No api_version = the original format: read best-effort.
    write_action(clean_state, "Old.yaml", "steps:\n  - echo hi\n")
    assert "Old" in [a["name"] for a in ybe.load_actions()]
    assert ybe.load_actions_report()[1] == []


def test_too_old_versions_are_skipped_unless_forced(clean_state, monkeypatch):
    window = ybe.config.EXTENSION_API_SUPPORT_WINDOW
    too_old = max(1, ybe.config.EXTENSION_API_VERSION - window)
    write_action(clean_state, "Ancient.yaml",
                 f"api_version: {too_old}\nname: Ancient\nsteps:\n  - echo hi\n")
    actions, errors = ybe.load_actions_report()
    assert "Ancient" not in [a["name"] for a in actions]
    assert any("--allow-old-extensions" in e for e in errors)

    # forcing reads it
    monkeypatch.setattr(ybe.config, "ALLOW_OLD_EXTENSIONS", True)
    actions, errors = ybe.load_actions_report()
    assert "Ancient" in [a["name"] for a in actions]
    assert errors == []


def test_newer_extension_files_are_skipped_with_an_error(clean_state):
    nxt = ybe.config.EXTENSION_API_VERSION + 1
    write_action(clean_state, "Future.yaml",
                 f"api_version: {nxt}\nname: Future\nsteps:\n  - echo hi\n")
    write_hook(clean_state, "on_after_save.yaml",
               f"api_version: {nxt}\nsteps:\n  - echo hi\n")
    write_filter(clean_state, "FutureF.yaml",
                 f"api_version: {nxt}\nname: FutureF\nsteps:\n  - echo hi\n")
    write_widget(clean_state, "future.yaml",
                 f"api_version: {nxt}\nname: FutureW\ntitle: W\ncontrols:\n"
                 "  - type: button\n    label: Go\n    steps:\n      - echo hi\n")

    actions, action_errors = ybe.load_actions_report()
    assert "Future" not in [a["name"] for a in actions]
    assert any("written for extension format" in e for e in action_errors)

    hooks, hook_errors = ybe.load_hooks()
    assert all(h["name"] != "on_after_save" for h in hooks)
    assert any("written for extension format" in e for e in hook_errors)

    filters, filter_errors = ybe.load_filters()
    assert "FutureF" not in filters
    assert any("written for extension format" in e for e in filter_errors)

    widgets, widget_errors = ybe.load_widgets()
    assert "FutureW" not in widgets
    assert any("written for extension format" in e for e in widget_errors)

    # ...but the raw editor can still resolve it, so it can explain the error.
    found = ybe.extension_file_for("action", "Future")
    assert found is not None and found["api_version"] == nxt
    assert ybe.api_version_status(found["api_version"]) == "newer"


def test_old_tag_references_are_reported(clean_state):
    write_action(clean_state, "OldTag.yaml",
                 "name: OldTag\nsteps:\n  - echo hi\n"
                 "after_success:\n  - app_refresh_image_tags\n")
    _, action_errors = ybe.load_actions_report()
    assert any("app_refresh_image_tags" in e and "ext.tags.refresh_image_tags" in e
               for e in action_errors)

    write_hook(clean_state, "on_after_save.yaml", "steps:\n  - app_clear_tags\n")
    _, hook_errors = ybe.load_hooks()
    assert any("app_clear_tags" in e for e in hook_errors)

    write_filter(clean_state, "OldTagF.yaml",
                 "name: OldTagF\narguments:\n  - name: tag_name\n"
                 "    options: {DATASET_TAG_NAMES}\nsteps:\n  - echo {TAGS_DIR}\n")
    _, filter_errors = ybe.load_filters()
    assert any("{TAGS_DIR}" in e for e in filter_errors)
    assert any("{DATASET_TAG_NAMES}" in e for e in filter_errors)


def test_unknown_app_action_is_reported_at_load(clean_state):
    write_action(clean_state, "Typo.yaml",
                 "name: Typo\nsteps:\n  - echo hi\nafter_success:\n  - app_nope\n")
    _, errors = ybe.load_actions_report()
    assert any("app_nope" in e for e in errors)


def test_shipped_extensions_have_no_compat_errors(clean_state, monkeypatch):
    # The shipped files must not trip the removed-reference checks.
    base = Path(ybe.config.BASE_DIR)
    monkeypatch.setattr(ybe.config, "ACTIONS_DIR", str(base / "actions"))
    monkeypatch.setattr(ybe.config, "USER_ACTIONS_DIR", str(base / "nope-actions"))
    monkeypatch.setattr(ybe.config, "FILTERS_DIR", str(base / "filters"))
    monkeypatch.setattr(ybe.config, "USER_FILTERS_DIR", str(base / "nope-filters"))
    monkeypatch.setattr(ybe.config, "HOOKS_DIR", str(base / "hooks"))
    monkeypatch.setattr(ybe.config, "USER_HOOKS_DIR", str(base / "nope-hooks"))
    assert ybe.load_actions_report()[1] == []
    assert ybe.load_filters()[1] == []
    assert ybe.load_hooks()[1] == []


def test_newer_package_is_skipped_with_an_error(clean_state):
    nxt = ybe.config.EXTENSION_API_VERSION + 1
    write_package(clean_state, "future", f"api_version: {nxt}\nname: Future\n")
    pkgs, errors = ybe.load_packages()
    assert all(p["id"] != "future" for p in pkgs)
    assert any("written for extension format" in e for e in errors)


def test_api_config_reports_version_errors(clean_state):
    nxt = ybe.config.EXTENSION_API_VERSION + 1
    write_action(clean_state, "Future.yaml",
                 f"api_version: {nxt}\nname: Future\nsteps:\n  - echo hi\n")
    write_package(clean_state, "future", f"api_version: {nxt}\nname: Future\n")
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert any("written for extension format" in e for e in cfg["action_errors"])
    assert any("written for extension format" in e for e in cfg["package_errors"])


def test_dump_action_file_round_trips():
    text = ybe._dump_action_file(["rm {IMAGE_PATH}"], ["app_refresh_image"])
    parsed = ybe._parse_action_file(text)
    assert parsed["api_version"] == ybe.config.EXTENSION_API_VERSION
    assert parsed["steps"] == ["rm {IMAGE_PATH}"]
    assert parsed["after_success"] == ["app_refresh_image"]

    inactive = ybe._parse_action_file(ybe._dump_action_file(["echo hi"], [], active=False))
    assert inactive["active"] is False


def test_dump_filter_file_round_trips():
    text = ybe._dump_filter_file("demo: x", True, [
        {"name": "every", "required": False, "default": "2", "options": ["2", "3"]},
        {"name": "reverse", "required": True, "default": None, "options": None},
    ], ["echo {EVERY}"])
    parsed = ybe._parse_filter_file(text)
    assert parsed["api_version"] == ybe.config.EXTENSION_API_VERSION
    assert parsed["description"] == "demo: x"
    assert parsed["arguments"] == [
        {"name": "every", "required": False, "default": "2", "options": ["2", "3"]},
        {"name": "reverse", "required": True, "default": None, "options": None},
    ]
    assert parsed["steps"] == ["echo {EVERY}"]


def test_safe_extension_name():
    assert ybe._safe_extension_name("Remove box") == "Remove box"
    for bad in ("", "   ", ".hidden", "..", "a/b", "a\\b", "x" * 81,
                "app_x", "backend_x", "action_x", "on_x"):
        assert ybe._safe_extension_name(bad) is None


def test_bump_api_version_text_preserves_comments():
    bumped = ybe._bump_api_version_text("# note\nname: x\nsteps:\n  - a\n")
    assert bumped.startswith(f"# note\napi_version: {ybe.config.EXTENSION_API_VERSION}\n")
    replaced = ybe._bump_api_version_text("api_version: 9\nsteps:\n  - a\n")
    assert f"api_version: {ybe.config.EXTENSION_API_VERSION}" in replaced
    assert "api_version: 9" not in replaced


def test_api_action_save_writes_user_file(clean_state):
    cfg = ybe.app.test_client().post("/api/actions/save", json={
        "name": "Remove box",
        "steps": ["rm {IMAGE_PATH}"],
        "after_success": ["app_refresh_image"],
    }).get_json()
    assert cfg["ok"] is True
    path = Path(clean_state) / "actions" / "Remove box.yaml"
    assert path.is_file()
    assert [a["name"] for a in ybe.load_actions()] == ["Remove box"]
    assert cfg["action_defs"][0]["source"] == "user"
    assert cfg["action_defs"][0]["status"] == "current"
    assert f"api_version: {ybe.config.EXTENSION_API_VERSION}" in path.read_text(encoding="utf-8")


def test_api_action_save_rejects_bad_name_and_empty(clean_state):
    client = ybe.app.test_client()
    assert client.post("/api/actions/save",
                       json={"name": "app_x", "steps": ["echo"]}).status_code == 400
    assert client.post("/api/actions/save",
                       json={"name": "X", "steps": [], "after_success": []}).status_code == 400
    assert client.post("/api/actions/save",
                       json={"name": "../evil", "steps": ["echo"]}).status_code == 400


def test_api_action_save_overwrite_conflict(clean_state):
    client = ybe.app.test_client()
    body = {"name": "X", "steps": ["echo one"]}
    assert client.post("/api/actions/save", json=body).status_code == 200
    assert client.post("/api/actions/save", json=body).status_code == 409
    assert client.post("/api/actions/save", json={**body, "overwrite": True}).status_code == 200


def test_api_action_save_readonly(clean_state):
    ybe.state.STATE["readonly"] = True
    resp = ybe.app.test_client().post(
        "/api/actions/save", json={"name": "X", "steps": ["echo"]})
    assert resp.status_code == 403


def test_api_hook_save_writes_hook(clean_state):
    cfg = ybe.app.test_client().post("/api/hooks/save", json={
        "event": "after_save", "steps": ["echo saved"], "active": True,
    }).get_json()
    assert cfg["ok"] is True
    assert (Path(clean_state) / "hooks" / "on_after_save.yaml").is_file()
    assert cfg["hook_defs"][0]["event"] == "after_save"
    assert cfg["hook_defs"][0]["status"] == "current"


def test_api_hook_save_rejects_unknown_event(clean_state):
    resp = ybe.app.test_client().post(
        "/api/hooks/save", json={"event": "nope", "steps": ["echo"]})
    assert resp.status_code == 400


def test_api_extension_disabled_toggles_action_per_dataset(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    root = make_dataset(tmp_path)
    load_dataset(client, root)
    cfg = client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    }).get_json()
    assert cfg["ok"] is True
    assert "Remove" not in cfg["actions"]
    assert {d["name"]: d["enabled"] for d in cfg["action_defs"]}["Remove"] is False
    views = read_config()["views"]
    assert views[str(root / "data.yaml")]["disabled"]["actions"] == ["Remove"]

    cfg = client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": False,
    }).get_json()
    assert "Remove" in cfg["actions"]
    assert {d["name"]: d["enabled"] for d in cfg["action_defs"]}["Remove"] is True


def test_api_extension_disabled_toggles_hook(clean_state, tmp_path):
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    cfg = client.post("/api/extensions/disabled", json={
        "kind": "hook", "name": "on_after_save", "disabled": True,
    }).get_json()
    assert "on_after_save" not in cfg["hooks"]
    assert {d["name"]: d["enabled"] for d in cfg["hook_defs"]}["on_after_save"] is False


def test_api_extension_delete_clears_disabled_flag(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    root = make_dataset(tmp_path)
    load_dataset(client, root)
    client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    })
    resp = client.post("/api/extensions/delete",
                       json={"kind": "action", "name": "Remove"})
    assert resp.status_code == 200
    views = read_config()["views"]
    assert views[str(root / "data.yaml")]["disabled"]["actions"] == []


def test_api_action_run_refuses_disabled_action(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    })
    resp = client.post("/api/actions/run",
                       json={"action": "Remove", "target": "train/a.jpg"})
    assert resp.status_code == 400
    assert "disabled" in resp.get_json()["error"]


def test_api_action_run_refuses_disabled_hook(clean_state, tmp_path):
    write_hook(tmp_path, "on_after_save.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    client.post("/api/extensions/disabled", json={
        "kind": "hook", "name": "on_after_save", "disabled": True,
    })
    resp = client.post("/api/actions/run",
                       json={"action": "on_after_save", "target": "train/a.jpg"})
    assert resp.status_code == 400
    assert "disabled" in resp.get_json()["error"]


def test_api_extension_disabled_requires_dataset(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    resp = ybe.app.test_client().post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    })
    assert resp.status_code == 400


def test_api_extension_disabled_validates_kind_and_name(clean_state, tmp_path):
    client = ybe.app.test_client()
    load_dataset(client, make_dataset(tmp_path))
    assert client.post("/api/extensions/disabled", json={
        "kind": "filter", "name": "x", "disabled": True,
    }).status_code == 400
    assert client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Nope", "disabled": True,
    }).status_code == 404


def test_api_extension_disabled_is_per_dataset(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    root_a = make_dataset(tmp_path / "a")
    load_dataset(client, root_a)
    client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    })
    root_b = make_dataset(tmp_path / "b")
    cfg = client.post("/api/data",
                      json={"data_yaml": str(root_b / "data.yaml")}).get_json()
    assert "Remove" in cfg["actions"]


def test_save_view_preserves_disabled_extensions(clean_state, tmp_path):
    write_action(tmp_path, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    root = make_dataset(tmp_path)
    load_dataset(client, root)
    client.post("/api/extensions/disabled", json={
        "kind": "action", "name": "Remove", "disabled": True,
    })
    ybe._save_view(str(root / "data.yaml"), "train", [])
    views = read_config()["views"]
    assert views[str(root / "data.yaml")]["disabled"]["actions"] == ["Remove"]


def test_api_filter_save_writes_filter(clean_state):
    cfg = ybe.app.test_client().post("/api/filters/save", json={
        "name": "Keep every",
        "description": "demo",
        "active": True,
        "arguments": [{"name": "every", "required": True,
                       "default": "2", "options": ["2", "3"]}],
        "steps": ["echo {EVERY}"],
    }).get_json()
    assert cfg["ok"] is True
    assert (Path(clean_state) / "filters" / "Keep every.yaml").is_file()
    flt = ybe.load_filters()[0]["Keep every"]
    assert flt["arguments"][0]["name"] == "every"
    assert cfg["filter_defs"][0]["status"] == "current"


def test_api_filter_save_rejects_reserved_argument_and_empty(clean_state):
    client = ybe.app.test_client()
    assert client.post("/api/filters/save", json={
        "name": "X", "steps": ["echo"], "arguments": [{"name": "app_dir"}],
    }).status_code == 400
    assert client.post("/api/filters/save",
                       json={"name": "X", "steps": []}).status_code == 400


def test_api_config_exposes_extension_builder_data(clean_state):
    write_action(clean_state, "Remove.yaml", "steps:\n  - echo hi\n")
    write_hook(clean_state, "on_after_save.yaml", "steps:\n  - echo hi\n")
    write_filter(clean_state, "Odd.yaml", filter_yaml("echo hi", name="Odd"))
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert cfg["extension_api_version"] == ybe.config.EXTENSION_API_VERSION
    assert "IMAGE_PATH" in {p["name"] for p in cfg["placeholders"]["action"]}
    assert "INPUT_PIPE" in {p["name"] for p in cfg["placeholders"]["filter"]}
    assert cfg["hook_events"] == list(ybe.config.HOOK_EVENTS)
    assert "app_save" in cfg["app_actions"]
    assert "backend_rescan_images" in cfg["backend_actions"]

    action = {d["name"]: d for d in cfg["action_defs"]}["Remove"]
    assert action["status"] == "outdated" and action["source"] == "user"
    assert action["steps"] == ["echo hi"]
    assert "api_version" in cfg["hook_defs"][0]
    assert cfg["filter_defs"][0]["source"] == "user"


def test_api_extension_file_get_and_writable(clean_state):
    write_action(clean_state, "Remove.yaml", "steps:\n  - echo hi\n")
    data = ybe.app.test_client().get(
        "/api/extensions/file?kind=action&name=Remove").get_json()
    assert data["ok"] and data["source"] == "user" and data["writable"] is True
    assert data["status"] == "outdated"
    assert "echo hi" in data["text"]


def test_api_extension_file_get_shipped_is_not_writable(clean_state):
    write_action(clean_state, "Keep.yaml", "steps:\n  - echo hi\n", subdir="app-actions")
    data = ybe.app.test_client().get(
        "/api/extensions/file?kind=action&name=Keep").get_json()
    assert data["source"] == "shipped" and data["writable"] is False


def test_api_extension_file_get_unknown_404(clean_state):
    assert ybe.app.test_client().get(
        "/api/extensions/file?kind=action&name=Nope").status_code == 404


def test_api_extension_file_save_bumps_and_preserves_comments(clean_state):
    path = Path(clean_state) / "actions" / "Remove.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# keep me\nname: Remove\nsteps:\n  - echo hi\n", encoding="utf-8")
    data = ybe.app.test_client().post("/api/extensions/file", json={
        "kind": "action", "name": "Remove", "text": path.read_text(encoding="utf-8"),
    }).get_json()
    assert data["ok"] and data["status"] == "current"
    assert data["api_version"] == ybe.config.EXTENSION_API_VERSION
    written = path.read_text(encoding="utf-8")
    assert "# keep me" in written
    assert f"api_version: {ybe.config.EXTENSION_API_VERSION}" in written


def test_api_extension_file_save_shipped_creates_user_override(clean_state):
    write_action(clean_state, "Keep.yaml", "steps:\n  - echo shipped\n", subdir="app-actions")
    data = ybe.app.test_client().post("/api/extensions/file", json={
        "kind": "action", "name": "Keep", "text": "steps:\n  - echo edited\n",
    }).get_json()
    assert data["ok"] and data["source"] == "user"
    assert (Path(clean_state) / "actions" / "Keep.yaml").is_file()
    assert ybe.load_actions()[0]["steps"] == ["echo edited"]


def test_api_extension_file_save_rejects_empty_and_newer(clean_state):
    write_action(clean_state, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    assert client.post("/api/extensions/file", json={
        "kind": "action", "name": "Remove", "text": "# only a comment\n",
    }).status_code == 400

    write_action(clean_state, "Future.yaml",
                 f"api_version: {ybe.config.EXTENSION_API_VERSION + 1}\nsteps:\n  - echo hi\n")
    assert client.post("/api/extensions/file", json={
        "kind": "action", "name": "Future", "text": "steps:\n  - echo hi\n",
    }).status_code == 400
    assert client.get(
        "/api/extensions/file?kind=action&name=Future").status_code == 400


def test_api_extension_file_save_readonly(clean_state):
    ybe.state.STATE["readonly"] = True
    resp = ybe.app.test_client().post("/api/extensions/file", json={
        "kind": "action", "name": "X", "text": "steps:\n  - a\n"})
    assert resp.status_code == 403


def test_api_extension_delete_user_only(clean_state):
    write_action(clean_state, "Remove.yaml", "steps:\n  - echo hi\n")
    client = ybe.app.test_client()
    cfg = client.post("/api/extensions/delete",
                      json={"kind": "action", "name": "Remove"}).get_json()
    assert cfg["ok"] is True
    assert not (Path(clean_state) / "actions" / "Remove.yaml").exists()
    assert ybe.load_actions() == []


def test_api_extension_delete_refuses_shipped(clean_state):
    write_action(clean_state, "Keep.yaml", "steps:\n  - echo hi\n", subdir="app-actions")
    resp = ybe.app.test_client().post(
        "/api/extensions/delete", json={"kind": "action", "name": "Keep"})
    assert resp.status_code == 400
    assert (Path(clean_state) / "app-actions" / "Keep.yaml").is_file()


# --------------------------------------------------------------------------- #
# optional login (persistent user store)
# --------------------------------------------------------------------------- #
def test_auth_off_when_store_empty(clean_state):
    client = ybe.app.test_client()
    info = client.get("/api/session").get_json()
    assert info["auth_required"] is False
    assert info["authenticated"] is True
    assert client.get("/api/config").status_code == 200


def test_auth_on_when_store_has_user(clean_state):
    ybe.set_user("alice", "s3cret")
    client = ybe.app.test_client()
    assert client.get("/api/config").status_code == 401
    info = client.get("/api/session").get_json()
    assert info["auth_required"] is True and info["authenticated"] is False
    # The SPA shell loads so the login form can be rendered.
    assert client.get("/").status_code == 200


def test_password_is_stored_hashed(clean_state):
    ybe.set_user("alice", "s3cret")
    raw = Path(ybe.config.USERS_FILE).read_text(encoding="utf-8")
    assert "s3cret" not in raw
    assert json.loads(raw)["users"]["alice"] != "s3cret"
    assert ybe.verify_user("alice", "s3cret")
    assert not ybe.verify_user("alice", "wrong")


def test_login_logout_roundtrip(clean_state):
    ybe.set_user("alice", "s3cret")
    client = ybe.app.test_client()
    assert client.post(
        "/api/login", json={"username": "alice", "password": "nope"}
    ).status_code == 401
    assert client.get("/api/config").status_code == 401

    good = client.post(
        "/api/login", json={"username": "alice", "password": "s3cret"})
    assert good.status_code == 200 and good.get_json()["ok"] is True
    assert client.get("/api/config").get_json()["auth"] == {
        "required": True, "username": "alice"}

    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/config").status_code == 401


def test_login_rejects_unknown_user(clean_state):
    ybe.set_user("alice", "s3cret")
    resp = ybe.app.test_client().post(
        "/api/login", json={"username": "bob", "password": "s3cret"})
    assert resp.status_code == 401


def test_set_user_updates_password(clean_state):
    assert ybe.set_user("alice", "first") == "created"
    assert ybe.set_user("alice", "second") == "updated"
    assert ybe.verify_user("alice", "second")
    assert not ybe.verify_user("alice", "first")


def test_create_user_rejects_existing_name(clean_state):
    assert ybe.create_user("alice", "first") == "created"
    with pytest.raises(ValueError):
        ybe.create_user("alice", "second")
    # The original password is untouched.
    assert ybe.verify_user("alice", "first")


def test_update_user_requires_existing(clean_state):
    with pytest.raises(KeyError):
        ybe.update_user("alice", "pw")
    ybe.create_user("alice", "first")
    assert ybe.update_user("alice", "second") == "updated"
    assert ybe.verify_user("alice", "second")


def test_delete_user_requires_existing(clean_state):
    with pytest.raises(KeyError):
        ybe.delete_user("alice")
    ybe.create_user("alice", "pw")
    assert ybe.delete_user("alice") == "deleted"
    ybe.state.USERS = {}
    ybe.load_users()
    assert not ybe.auth_enabled()


def test_users_persist_across_reload(clean_state):
    ybe.set_user("alice", "s3cret")
    ybe.state.USERS = {}  # simulate a fresh process
    ybe.load_users()
    assert ybe.auth_enabled()
    assert ybe.verify_user("alice", "s3cret")


def test_load_users_tolerates_corrupt_file(clean_state):
    Path(ybe.config.USERS_FILE).write_text("{ not json", encoding="utf-8")
    ybe.state.USERS = {"stale": "x"}
    ybe.load_users()
    assert ybe.state.USERS == {}


def test_users_file_is_owner_only(clean_state):
    ybe.set_user("alice", "s3cret")
    assert os.stat(ybe.config.USERS_FILE).st_mode & 0o777 == 0o600


def test_session_invalid_after_user_removed(clean_state):
    ybe.set_user("alice", "s3cret")
    ybe.set_user("bob", "hunter2")  # keep the store non-empty
    client = ybe.app.test_client()
    client.post("/api/login", json={"username": "alice", "password": "s3cret"})
    assert client.get("/api/config").status_code == 200
    del ybe.state.USERS["alice"]
    assert client.get("/api/config").status_code == 401


def test_login_is_noop_when_auth_off(clean_state):
    resp = ybe.app.test_client().post(
        "/api/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 200
    assert resp.get_json()["auth_required"] is False


def test_fresh_home_has_no_login(clean_state):
    # A brand-new install ships no account: login is off until one is added.
    assert not ybe.auth_enabled()
    assert not Path(ybe.config.USERS_FILE).exists()
    assert ybe.app.test_client().get("/api/config").status_code == 200


def test_change_password(clean_state):
    ybe.set_user("alice", "old")
    client = ybe.app.test_client()
    client.post("/api/login", json={"username": "alice", "password": "old"})
    # Wrong current password is refused.
    assert client.post("/api/password", json={
        "current_password": "nope", "new_password": "new"}).status_code == 403
    assert ybe.verify_user("alice", "old")

    resp = client.post("/api/password", json={
        "current_password": "old", "new_password": "new"})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert ybe.verify_user("alice", "new")
    assert not ybe.verify_user("alice", "old")


def test_change_password_requires_login(clean_state):
    ybe.set_user("alice", "old")
    resp = ybe.app.test_client().post("/api/password", json={
        "current_password": "old", "new_password": "new"})
    assert resp.status_code == 401


def test_change_password_rejects_empty(clean_state):
    ybe.set_user("alice", "old")
    client = ybe.app.test_client()
    client.post("/api/login", json={"username": "alice", "password": "old"})
    assert client.post("/api/password", json={
        "current_password": "old", "new_password": ""}).status_code == 400


def test_valid_username_rules():
    assert ybe._valid_username("alice")
    assert not ybe._valid_username("")
    assert not ybe._valid_username("a:b")
    assert not ybe._valid_username("a\nb")


def test_prompt_password_reads_twice(monkeypatch):
    replies = iter(["secret", "secret"])
    monkeypatch.setattr(ybe.auth.getpass, "getpass", lambda prompt="": next(replies))
    assert ybe._prompt_password() == "secret"


def test_prompt_password_mismatch(monkeypatch):
    replies = iter(["secret", "other"])
    monkeypatch.setattr(ybe.auth.getpass, "getpass", lambda prompt="": next(replies))
    assert ybe._prompt_password() is None


def test_prompt_password_empty(monkeypatch):
    replies = iter(["", ""])
    monkeypatch.setattr(ybe.auth.getpass, "getpass", lambda prompt="": next(replies))
    assert ybe._prompt_password() is None


def test_prompt_password_cancelled(monkeypatch):
    def boom(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(ybe.auth.getpass, "getpass", boom)
    assert ybe._prompt_password() is None



# --------------------------------------------------------------------------- #
# custom widgets
# --------------------------------------------------------------------------- #
def write_widget(root, fname, body, subdir="widgets"):
    """Write one custom-widget YAML into <root>/<subdir> (created on demand)."""
    d = Path(root) / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body, encoding="utf-8")


WIDGET_YAML = """\
api_version: 5
name: Tools
title: Tools
controls:
  - type: button
    label: Refresh
    steps:
      - app_refresh_images_list
  - type: select
    id: mode
    label: Mode
    options: [fast, safe]
    default: safe
  - type: checkbox
    id: dry_run
    label: Dry run
    default: true
  - type: input
    id: suffix
    label: Suffix
    default: ""
"""


def test_load_widgets_parses_controls(clean_state):
    write_widget(clean_state, "tools.yaml", WIDGET_YAML)
    widgets, errors = ybe.load_widgets()
    assert errors == []
    w = widgets["Tools"]
    assert [c["type"] for c in w["controls"]] == ["button", "select", "checkbox", "input"]
    assert w["controls"][0]["steps"] == ["app_refresh_images_list"]
    assert w["controls"][1]["default"] == "safe"
    assert w["controls"][2]["default"] is True


def test_load_widgets_rejects_unknown_control(clean_state):
    write_widget(clean_state, "bad.yaml", "controls:\n  - type: slider\n    id: x\n")
    widgets, errors = ybe.load_widgets()
    assert widgets == {}
    assert errors and "slider" in errors[0]


def test_widget_select_default_falls_back(clean_state):
    write_widget(clean_state, "w.yaml",
                 "name: W\ncontrols:\n  - type: select\n    id: m\n"
                 "    options: [a, b]\n    default: z\n")
    widgets, _ = ybe.load_widgets()
    assert widgets["W"]["controls"][0]["default"] == "a"


def test_sanitize_widget_values(clean_state):
    values, error = ybe.sanitize_widget_values({"mode": "fast", "dry_run": "1"})
    assert error is None
    assert values == {"WIDGET_MODE": "fast", "WIDGET_DRY_RUN": "1"}
    assert ybe.sanitize_widget_values({"bad id": "x"})[1]


def test_api_config_includes_widget_defs(clean_state):
    write_widget(clean_state, "tools.yaml", WIDGET_YAML)
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert [d["name"] for d in cfg["widget_defs"]] == ["Tools"]
    assert cfg["widget_defs"][0]["status"] == "current"
    assert cfg["widget_errors"] == []


def test_widget_run_injects_values(clean_state):
    write_widget(clean_state, "tools.yaml", WIDGET_YAML)
    root = make_dataset(clean_state)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/widgets/run", json={
        "widget": "Tools", "control": 0, "target": "train/a.jpg",
        "values": {"mode": "fast", "dry_run": "1", "suffix": "x"},
    })
    data = resp.get_json()
    assert data["ok"] is True
    assert data["client_action"] == "app_refresh_images_list"
    run = ybe.state.EXECUTIONS[data["uid"]]
    assert run["values"]["WIDGET_MODE"] == "fast"
    assert run["values"]["WIDGET_DRY_RUN"] == "1"
    assert run["values"]["WIDGET_SUFFIX"] == "x"
    done = client.post("/api/actions/run",
                       json={"uid": data["uid"], "result": {"ok": True}})
    assert done.get_json()["ok"] is True


def test_widget_run_rejects_non_button(clean_state):
    write_widget(clean_state, "tools.yaml", WIDGET_YAML)
    root = make_dataset(clean_state)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/widgets/run", json={
        "widget": "Tools", "control": 1, "target": "train/a.jpg", "values": {},
    })
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# extension packages
# --------------------------------------------------------------------------- #
def write_package(root, pid, manifest, parts=None):
    """Write an extension package (<root>/extensions/<pid>/) with optional parts."""
    base = Path(root) / "extensions" / pid
    base.mkdir(parents=True, exist_ok=True)
    (base / "extension.yaml").write_text(manifest, encoding="utf-8")
    for sub, fname, body in (parts or []):
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text(body, encoding="utf-8")
    return base


PKG_MANIFEST = """\
api_version: 5
name: My Pack
description: demo
version: 1.0.0
author: me
active: true
settings:
  title: Pack settings
  controls:
    - type: checkbox
      id: verbose
      label: Verbose
      default: false
    - type: button
      label: Refresh
      steps:
        - app_refresh_images_list
"""

PACK_ACTION = "name: Pack action\nsteps:\n  - echo hi\n"


def test_load_packages_discovers_parts(clean_state):
    write_package(clean_state, "mypack", PKG_MANIFEST, [
        ("actions", "pack_action.yaml", PACK_ACTION),
        ("hooks", "on_after_save.yaml", "steps:\n  - echo hi\n"),
        ("widgets", "pack_widget.yaml",
         "name: Pack widget\ncontrols:\n  - type: button\n    label: B\n    steps:\n      - echo hi\n"),
    ])
    pkgs, errors = ybe.load_packages()
    assert errors == []
    assert [p["id"] for p in pkgs] == ["mypack"]
    assert pkgs[0]["settings"]["controls"][0]["id"] == "verbose"
    assert push_set(pkgs[0]["parts"]) == {"action", "hook", "widget"}


def push_set(parts):
    return set(parts)


def test_package_parts_load_into_extensions(clean_state):
    write_package(clean_state, "mypack", PKG_MANIFEST,
                  [("actions", "pack_action.yaml", PACK_ACTION)])
    entry = next(a for a in ybe.load_actions() if a["name"] == "Pack action")
    assert entry["package"] == "mypack"


def test_flat_file_wins_over_package_file(clean_state):
    write_package(clean_state, "mypack", PKG_MANIFEST,
                  [("actions", "same.yaml", "name: Same\nsteps:\n  - echo package\n")])
    write_action(clean_state, "same.yaml", "name: Same\nsteps:\n  - echo flat\n")
    entry = next(a for a in ybe.load_actions() if a["name"] == "Same")
    assert entry["steps"] == ["echo flat"]


def test_inactive_package_parts_are_not_loaded(clean_state):
    write_package(clean_state, "mypack",
                  PKG_MANIFEST.replace("active: true", "active: false"),
                  [("actions", "pack_action.yaml", PACK_ACTION)])
    assert all(a["name"] != "Pack action" for a in ybe.load_actions())
    pkgs, _ = ybe.load_packages()
    assert pkgs[0]["active"] is False


def test_api_config_includes_extension_packages(clean_state):
    write_package(clean_state, "mypack", PKG_MANIFEST)
    cfg = ybe.app.test_client().get("/api/config").get_json()
    assert [p["id"] for p in cfg["extension_packages"]] == ["mypack"]
    assert cfg["extension_packages"][0]["source"] == "user"
    assert cfg["package_errors"] == []


def test_extensions_run_package_settings(clean_state):
    write_package(clean_state, "mypack", PKG_MANIFEST)
    root = make_dataset(clean_state)
    client = ybe.app.test_client()
    load_dataset(client, root)
    resp = client.post("/api/extensions/run", json={
        "package": "mypack", "control": 1, "target": "train/a.jpg", "values": {"verbose": "1"},
    })
    data = resp.get_json()
    assert data["ok"] is True
    assert data["client_action"] == "app_refresh_images_list"
    assert ybe.state.EXECUTIONS[data["uid"]]["values"]["WIDGET_VERBOSE"] == "1"


# --------------------------------------------------------------------------- #
# sandboxed UI panels (plugin API)
# --------------------------------------------------------------------------- #
PANEL_JS = "window.YBE.state.getTags().then(function (t) { document.title = t.join(); });\n"

UI_MANIFEST = """\
api_version: 5
name: My Pack
description: demo
version: 1.0.0
active: true
ui:
  api_version: 3
  title: My Panel
  script: panel.js
  location: right
  height: 200
"""


def test_plugin_api_status():
    cur = ybe.config.PLUGIN_API_VERSION
    assert ybe.plugin_api_status(cur) == "current"
    assert ybe.plugin_api_status(cur + 1) == "newer"
    assert ybe.plugin_api_status(0) == "outdated"
    assert ybe.plugin_api_status(None) == "outdated"


def test_load_packages_parses_ui(clean_state):
    write_package(clean_state, "mypack", UI_MANIFEST, [("", "panel.js", PANEL_JS)])
    pkgs, errors = ybe.load_packages()
    assert errors == []
    ui = pkgs[0]["ui"]
    assert ui["api_version"] == 3
    assert ui["title"] == "My Panel"
    assert ui["script"] == "panel.js"
    assert ui["location"] == "right"
    assert ui["height"] == 200


def test_package_script_path_rejects_traversal(clean_state):
    manifest = UI_MANIFEST.replace("script: panel.js", "script: ../evil.js")
    write_package(clean_state, "mypack", manifest, [("", "panel.js", PANEL_JS)])
    pkgs, _ = ybe.load_packages()
    assert ybe.package_script_path(pkgs[0]) is None


def test_package_script_path_resolves(clean_state):
    write_package(clean_state, "mypack", UI_MANIFEST, [("", "panel.js", PANEL_JS)])
    pkgs, _ = ybe.load_packages()
    path = ybe.package_script_path(pkgs[0])
    assert path and path.endswith("panel.js") and os.path.isfile(path)


def test_api_config_includes_panel_ui(clean_state):
    write_package(clean_state, "mypack", UI_MANIFEST, [("", "panel.js", PANEL_JS)])
    cfg = ybe.app.test_client().get("/api/config").get_json()
    ui = cfg["extension_packages"][0]["ui"]
    assert ui["script"] == "panel.js" and ui["status"] == "current"
    assert cfg["plugin_api_version"] == ybe.config.PLUGIN_API_VERSION


def test_extension_script_route_serves_text(clean_state):
    write_package(clean_state, "mypack", UI_MANIFEST, [("", "panel.js", PANEL_JS)])
    resp = ybe.app.test_client().get("/api/extensions/script?package=mypack")
    assert resp.status_code == 200
    assert b"YBE" in resp.data
    assert resp.headers["Content-Type"].startswith("text/javascript")


def test_extension_script_route_rejects_inactive_and_unknown(clean_state):
    write_package(clean_state, "mypack",
                  UI_MANIFEST.replace("active: true", "active: false"),
                  [("", "panel.js", PANEL_JS)])
    client = ybe.app.test_client()
    assert client.get("/api/extensions/script?package=mypack").status_code == 404
    assert client.get("/api/extensions/script?package=nope").status_code == 404
