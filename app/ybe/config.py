"""Shipped/user path resolution plus catalog and tuning constants.

Everything here is a module-level value the tests may redirect, so callers must
read it as `config.NAME` rather than importing the name directly: that way
`monkeypatch.setattr(ybe.config, "NAME", ...)` reaches every caller.
"""

import os
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the shipped app/ directory


def _resolve_home():
    """The user folder: `--home` (applied later) > $YBX_HOME > parent of app.py.

    The parent of `app.py` is the user root in both an installed copy
    (`<root>/app/app.py`) and a git clone (`<repo>/app/app.py`), so both behave
    identically without extra flags.
    """
    env = os.environ.get("YBX_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(BASE_DIR)


YBX_HOME = _resolve_home()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# Built-in, shipped files (inside app/); replaced wholesale on upgrade.
ACTIONS_DIR = os.path.join(BASE_DIR, "actions")  # one YAML file per action
HOOKS_DIR = os.path.join(BASE_DIR, "hooks")  # one YAML file per event hook
FILTERS_DIR = os.path.join(BASE_DIR, "filters")  # one YAML file per filter
WIDGETS_DIR = os.path.join(BASE_DIR, "widgets")  # one YAML file per custom widget
EXTENSIONS_DIR = os.path.join(BASE_DIR, "extensions")  # one folder per extension package
APP_SCRIPT_DIR = os.path.join(BASE_DIR, "scripts")  # shipped helper programs
SHORTCUTS_FILE = os.path.join(BASE_DIR, "shortcuts.txt")
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")  # shipped app version
CHANGES_FILE = os.path.join(BASE_DIR, "CHANGES")  # per-version "what's new" notes

# User files (inside YBX_HOME); read after the built-ins and win on a clash.
USER_ACTIONS_DIR = os.path.join(YBX_HOME, "actions")
USER_HOOKS_DIR = os.path.join(YBX_HOME, "hooks")
USER_FILTERS_DIR = os.path.join(YBX_HOME, "filters")
USER_WIDGETS_DIR = os.path.join(YBX_HOME, "widgets")
USER_EXTENSIONS_DIR = os.path.join(YBX_HOME, "extensions")
USER_SCRIPT_DIR = os.path.join(YBX_HOME, "scripts")
USER_SHORTCUTS_FILE = os.path.join(YBX_HOME, "shortcuts.txt")
# One JSON file holds all per-user config: recent datasets, per-dataset views
# (split/filter/disabled + last image) and cross-browser UI settings. It
# sits in YBX_HOME, outside `app/`, so app updates never touch it.
CONFIG_FILE = os.path.join(YBX_HOME, "config.json")
# The update-check cache is a throwaway background result, so it stays its own
# file; `_load_update_cache` / `check_for_update` own it.
UPDATE_CHECK_FILE = os.path.join(YBX_HOME, ".update_check.json")
# Legacy per-purpose files, read once to migrate into CONFIG_FILE and then
# removed. Kept as module constants so tests can redirect them.
RECENT_FILE = os.path.join(YBX_HOME, ".recent_data_yamls.json")
VIEW_FILE = os.path.join(YBX_HOME, ".view_state.json")  # active split/filter per dataset
SETTINGS_FILE = os.path.join(YBX_HOME, ".settings.json")  # cross-browser UI prefs
# Login accounts: {"version": 1, "users": {"name": "<password_hash>"}}. Login is
# opt-in: an empty/absent store means no login, and any entry turns it on. The
# file is owner-only (0600) because it holds password hashes. Managed with the
# `ybe users` command (there is no default account).
USERS_FILE = os.path.join(YBX_HOME, "users.json")
# The Flask session-signing key, generated once and reused across restarts (and
# app updates) so a signed-in browser stays signed in. Owner-only (0600) because
# anyone who reads it can forge a session. Lives in YBX_HOME, outside `app/`.
SECRET_KEY_FILE = os.path.join(YBX_HOME, ".secret_key")

# Update check: compare the shipped VERSION with the newest GitHub one. A check
# is skipped while the cache is fresh (< UPDATE_CHECK_INTERVAL) and the running
# version is unchanged; the start thread polls, so the network is only hit after
# the interval has passed.
UPDATE_REPO = "tabebqena/yolo-box-editor"
UPDATE_API = f"https://api.github.com/repos/{UPDATE_REPO}"
UPDATE_RAW = f"https://raw.githubusercontent.com/{UPDATE_REPO}"
UPDATE_CHECK_INTERVAL = 7 * 24 * 60 * 60  # re-check at most once a week
UPDATE_POLL_INTERVAL = 6 * 60 * 60  # how often the start thread wakes up
UPDATE_CHECK_TIMEOUT = 5  # seconds per network request

# Per-run {PIPE_PATH} files live in the system temp dir (never in the repo).
PIPE_DIR = os.path.join(tempfile.gettempdir(), "yolo-box-editor-pipes")
# Per-run filter-chain scratch dirs (input/output pipes) live here too.
FILTER_PIPES_DIR = os.path.join(tempfile.gettempdir(), "yolo-box-editor-filter-pipes")


def configure_home(path):
    """Point the user folders at `path` (the `--home` override)."""
    global YBX_HOME, USER_ACTIONS_DIR, USER_HOOKS_DIR, USER_FILTERS_DIR
    global USER_WIDGETS_DIR, USER_EXTENSIONS_DIR
    global USER_SCRIPT_DIR, USER_SHORTCUTS_FILE, RECENT_FILE, VIEW_FILE
    global SETTINGS_FILE, UPDATE_CHECK_FILE, CONFIG_FILE, USERS_FILE
    global SECRET_KEY_FILE
    YBX_HOME = os.path.abspath(os.path.expanduser(path))
    USER_ACTIONS_DIR = os.path.join(YBX_HOME, "actions")
    USER_HOOKS_DIR = os.path.join(YBX_HOME, "hooks")
    USER_FILTERS_DIR = os.path.join(YBX_HOME, "filters")
    USER_WIDGETS_DIR = os.path.join(YBX_HOME, "widgets")
    USER_EXTENSIONS_DIR = os.path.join(YBX_HOME, "extensions")
    USER_SCRIPT_DIR = os.path.join(YBX_HOME, "scripts")
    USER_SHORTCUTS_FILE = os.path.join(YBX_HOME, "shortcuts.txt")
    CONFIG_FILE = os.path.join(YBX_HOME, "config.json")
    RECENT_FILE = os.path.join(YBX_HOME, ".recent_data_yamls.json")
    VIEW_FILE = os.path.join(YBX_HOME, ".view_state.json")
    SETTINGS_FILE = os.path.join(YBX_HOME, ".settings.json")
    UPDATE_CHECK_FILE = os.path.join(YBX_HOME, ".update_check.json")
    USERS_FILE = os.path.join(YBX_HOME, "users.json")
    SECRET_KEY_FILE = os.path.join(YBX_HOME, ".secret_key")


def ensure_user_dirs():
    """Create the user folders when missing, so the home is usable right away."""
    for dirpath in (
        USER_ACTIONS_DIR, USER_HOOKS_DIR, USER_FILTERS_DIR,
        USER_WIDGETS_DIR, USER_EXTENSIONS_DIR, USER_SCRIPT_DIR,
    ):
        try:
            os.makedirs(dirpath, exist_ok=True)
        except OSError:
            pass


# Built-in app actions; may be rebound in shortcuts.txt but cannot be renamed.
APP_ACTIONS = {
    "app_prev",
    "app_next",
    "app_del",
    "app_drop",
    "app_save",
    "app_undo",
    "app_redo",
    "app_ch_box",
    "app_sel_box",
    "app_sel_points",
    "app_escape",
    "app_show_hide",
    "app_box_details",
    "app_isolate_box",
    "app_focus_canvas",
    "app_select_all",
    "app_fix_box",
    # Keyboard box creation and whole-box moves (mouse-free editing).
    "app_new_box",
    "app_move_left",
    "app_move_right",
    "app_move_up",
    "app_move_down",
    # Keyboard border editing: widen (Ctrl+arrow) / narrow (Ctrl+Shift+arrow).
    "app_widen_left",
    "app_widen_right",
    "app_widen_up",
    "app_widen_down",
    "app_narrow_left",
    "app_narrow_right",
    "app_narrow_up",
    "app_narrow_down",
    "app_force_draw",
    "app_refresh_images_list",
    "app_reload_images_list",
    "app_refresh_image",
    "app_refresh_image_labels",
    "app_refresh_image_all",
    "app_help",
    # Client-only actions meant to be called from an action/hook `steps` or
    # `after_success` (not bound to keys by default).
    "app_select_next_box",
    "app_select_prev_box",
    "app_copy_labels_from_prev",
}

# Server-side built-in actions (name -> callable) usable as a `steps` /
# `after_success` entry. They run inline on the backend, unlike `app_*` which
# pauses for the UI, so an action can ask the server to change its own state
# (e.g. re-scan the image folders) even when no browser is driving the run.
# Defined here so `_resolve_entry` / `_advance_execution` can see it; the actual
# callables are registered next to `_rescan_images` below.
BACKEND_ACTION_NAMES = {"backend_rescan_images"}

# Shipped "tip of the day" ideas, shown once per day (per browser). The browser
# remembers which it has seen so a new one appears each day until they cycle.
TIPS = [
    "Draw a box by dragging on the image; press Esc to drop a box you just drew by mistake.",
    "Select a box, then Tab cycles through its class and cx/cy/w/h fields; Esc leaves the row.",
    "Shift selects the next box, resuming from the last one you had active.",
    "Settings → Layout lets every widget and panel float or dock to any edge.",
    "Drag a floating window by its title bar; the L/T/R/B buttons dock it to an edge.",
    "Resize the side, dock and bottom panels by dragging their divider — the size is remembered.",
    "Filters (Settings → Filters) narrow the image list; stack up to eight of them top to bottom.",
    "Actions and hooks live in your user folder; a hook runs on events like on_after_save.",
    "Turn on Auto-save (Settings → General) so Prev/Next never asks you to save.",
    "Read-only mode (--readonly) is a safe way to browse a dataset without changing labels.",
    "Save (S) writes only when there are changes; Undo (Z) and Redo (Y) cover every edit.",
    "After an external tool edits the current image, use app_refresh_image to reload it in place.",
    "Paste the path to your data.yaml in Settings → Dataset, or use the Recent… dropdown.",
    "Click a box on the image to select it; its row in the Boxes list becomes editable.",
    "Type a number in the counter and press Enter to jump straight to that image.",
    "The split dropdown switches between train / val / test, or shows all of them together.",
    "Your last image is remembered per split, so switching back to a split returns you to it.",
    "Read-only mode is a safe way to look around: it never writes labels or tags.",
    "Every shortcut can be changed in shortcuts.txt — no code editing needed.",
    "Settings → Updates checks GitHub and tells you when a newer version is available.",
    "The ⚙ button opens Settings; Esc closes any dialog.",
    "Your UI settings are saved on the server too, so a new browser starts with your layout.",
    "Hooks run on events like on_after_save; see docs/actions-and-hooks.md for examples.",
]

MAX_RECENT = 10
ACTION_TIMEOUT = 120  # seconds
FILTER_TIMEOUT = 120  # seconds
MAX_CASCADE_DEPTH = 8  # max actions run by one execution (root + after_success)
# In a steps/after_success entry, another action is named `action_<Name>` so a
# bare action name can never be confused with a shell command.
ACTION_REF_PREFIX = "action_"
# An extension-defined app action is named `<extension_id>.<name>` in steps and
# events (e.g. `tags.clear_tags`). The prefix keeps it distinct from core `app_*`.
EXTENSION_ACTION_PREFIX = "ext."
# Every extension HTTP route is mounted under this prefix plus the package's own
# unique prefix (`/api/extension/<prefix><rule>`), so package rules never collide
# with each other or with the core `/api/*` routes.
EXTENSION_ROUTE_PREFIX = "/api/extension"
# Cap on how many times a lifecycle event may recursively trigger another
# app action before the host refuses (see js/plugin_api.js).
MAX_EVENT_DEPTH = 8

# Event hooks live in the hooks/ folder and fire on app events (never from a
# toolbar button or a shortcut). A hook file is named `on_<event>.yaml`; when the
# file name does not resolve to a known event, its `event_name:` key is used.
HOOK_PREFIX = "on_"
HOOK_EVENTS = (
    "images_list_loaded",
    "image_loaded",
    "before_prev",
    "before_next",
    "prev",
    "next",
    "before_save",
    "after_save",
    "box_created",
    "box_deleted",
    "box_edited",
)

# The extension YAML format version. Bump it only when the action/hook/filter/
# widget/package file format changes: the UI compares a file's `api_version:`
# against this to flag files that predate (or postdate) the format it understands.
# v2 added custom widgets; v3 added extension packages; v4 added sandboxed UI
# panels (`ui:` in an extension manifest); v5 added backend plugins
# (`backend:`) and extension-defined app actions (`app_actions:`).
EXTENSION_API_VERSION = 5
# What each extension format version added. This is the declared semantics list
# the app keeps so a future release can support or drop a version on purpose
# (see `ybe/compat.py`).
EXTENSION_API_HISTORY = (
    (1, "original actions/hooks/filters"),
    (2, "custom widgets"),
    (3, "extension packages"),
    (4, "sandboxed UI panels (ui:)"),
    (5, "backend plugins (backend:) and app_actions"),
)
# Versions the app no longer parses at all. Empty now; a future release adds one
# here to drop support explicitly (files are then always skipped).
EXTENSION_API_DROPPED = ()
# The app is only responsible for the newest N extension format versions. Older
# files (or files with no `api_version`) are skipped with an explaining error
# unless the user forces parsing (`--allow-old-extensions`).
EXTENSION_API_SUPPORT_WINDOW = 3
ALLOW_OLD_EXTENSIONS = False  # set by --allow-old-extensions

# The UI-panel plugin API version. Separate from EXTENSION_API_VERSION because a
# panel's JavaScript talks to the app through `YBE`, whose shape evolves on its
# own schedule. A package declares it as `ui.api_version:`; the UI compares it
# against this to block panels written for a newer API. v2 added `YBE.call`
# (package backend capabilities) and the `before_/after_app_action` event bus;
# v3 added `YBE.state.getConfig()` and the `YBE.api` request proxy.
PLUGIN_API_VERSION = 3
# What each plugin (YBE) API version added, and any versions dropped. A panel
# declaring `ui.api_version:` newer than PLUGIN_API_VERSION is not loaded.
PLUGIN_API_HISTORY = (
    (1, "initial YBE bridge (state reads, box edits, events)"),
    (2, "YBE.call (backend capabilities) and the app-action event bus"),
    (3, "YBE.state.getConfig and the YBE.api request proxy"),
)
PLUGIN_API_DROPPED = ()

# Placeholder catalogs offered by the UI's click-to-insert palette. Keep them in
# sync with the values built in `api_action_run` and `_filter_placeholder_values`
# (and with the tables in docs/actions-and-hooks.md and docs/filters.md).
ACTION_PLACEHOLDERS = (
    ("IMAGE_PATH", "path of the current image"),
    ("LABEL_PATH", "path of the current image's label file (may not exist yet)"),
    ("DATASET_PATH", "root path of the loaded dataset"),
    ("DATA_YAML_PATH", "path of the loaded data.yaml"),
    ("IMAGE_INDEX", "1-based position of the current image in the list"),
    ("APP_DIR", "the shipped code folder (app/)"),
    ("HOME_DIR", "your user folder (the working directory of every run)"),
    ("APP_SCRIPT_DIR", "the shipped helper scripts (app/scripts/)"),
    ("USER_SCRIPT_DIR", "your helper scripts (<home>/scripts/)"),
    ("PYTHON", "the Python interpreter running the app"),
    ("PIPE_PATH", "the per-run scratch file shared by the run's steps"),
)
FILTER_PLACEHOLDERS = (
    ("DATA_YAML_PATH", "path of the loaded data.yaml"),
    ("DATASET_PATH", "root path of the loaded dataset"),
    ("SPLIT", "active split (train/val/test) or empty on All splits"),
    ("INPUT_PIPE", "file with the candidate image paths (one per line)"),
    ("OUTPUT_PIPE", "file to write the kept image paths to"),
    ("APP_DIR", "the shipped code folder (app/)"),
    ("HOME_DIR", "your user folder (the working directory of every run)"),
    ("APP_SCRIPT_DIR", "the shipped helper scripts (app/scripts/)"),
    ("USER_SCRIPT_DIR", "your helper scripts (<home>/scripts/)"),
    ("PYTHON", "the Python interpreter running the app"),
)
