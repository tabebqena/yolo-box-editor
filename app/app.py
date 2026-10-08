#!/usr/bin/env python3
"""YOLO labelling app served by Flask.

Usage:
    python app/app.py --data /path/to/data.yaml
    python app/app.py --data /path/to/data.yaml --readonly   # viewer only

The data.yaml file can also be set from the web interface.

Expected data.yaml layout:

    path: /path/to/dataset_root      # optional; defaults to the data.yaml dir
    train: images/train
    val: images/val
    test: images/test                # optional

    nc: 3
    names: ['cat', 'dog', 'bird']    # one-line list, or a block form

For each split (train/val/test) the labels folder is the corresponding folder
with the `images` path segment replaced by `labels`
(e.g. `images/train` -> `labels/train`).

This file is only the command-line entry point. It parses the flags, points the
user folder at `--home`, loads the persistent secret key and the login store, and
then hands control to the Flask app in `ybe.server`. All the actual HTTP routes
live there.

The `from ybe import ...` block below is deliberate: it re-exports the helpers
that tests and any embedder reach through this module (`from app import ...`), so
those names stay importable from `app.py` even though their code lives in the
`ybe` package.
"""

import argparse
import os

# Re-exports only (see the note above): everything below is defined in `ybe`.
from ybe.parsing import (
    _extract_yaml_block,
    _is_toplevel_list_item,
    _line_comment,
    _normalize_tags,
    _parse_api_version,
    _parse_data_yaml,
    _parse_version,
    _parse_yaml_names_value,
    _read_tag_lines,
    _read_text,
    _read_text_lines,
    _read_yaml_names,
    _strip_comment,
    _toplevel_list_names,
    _version_newer,
    _yaml_scalar,
    parse_shortcut_line,
)

from ybe import auth, config, state, update
from ybe.auth import (
    _prompt_password,
    _valid_username,
    auth_enabled,
    create_user,
    delete_user,
    load_users,
    set_user,
    update_user,
    verify_user,
)
from ybe.commands import (
    BACKEND_ACTIONS,
    _advance_execution,
    _rescan_images,
    _resolve_entry,
    _run_command,
    begin_execution,
    finish_execution,
)
from ybe.config import configure_home, ensure_user_dirs
from ybe.dataset import (
    _current_images,
    _entry_by_key,
    _image_index,
    _labels_dir_for,
    _load_dataset,
    _parse_label_file,
    _split_by_name,
    _tags_dir_for,
    is_image,
    label_path,
    read_classes,
    scan_images,
    scan_splits,
    tag_path,
)
from ybe.filters import (
    _clear_filter,
    _known_image_paths,
    _normalize_filter_chain,
    _parse_filter_output,
    apply_filters,
    run_filter,
    run_filter_chain,
)
from ybe.extensions import (
    FILTER_CLASS_NAMES_TOKEN,
    FILTER_TAG_NAMES_TOKEN,
    _bump_api_version_text,
    _clean_extension_entries,
    _clean_filter_arguments,
    _dump_action_file,
    _dump_filter_file,
    _extension_file_payload,
    _extension_user_dir,
    _parse_action_file,
    _parse_extension_text,
    _parse_filter_file,
    _placeholder_payload,
    _safe_extension_name,
    api_version_status,
    effective_filter_arguments,
    extension_file_for,
    is_hook_name,
    load_actions,
    load_filters,
    load_hooks,
    resolve_filter_options,
)
from ybe.logging_setup import _SkipPresenceFilter, setup_logging
from ybe.secret_key import load_or_create_secret_key
from ybe.pipes import (
    _subprocess_env,
    build_command,
    create_pipe,
    is_pipe_path,
    remove_pipe,
)
from ybe.shortcuts import (
    _valid_shortcut,
    load_shortcuts,
    load_shortcuts_from,
    split_shortcuts,
    user_shortcut_names,
    write_user_shortcuts,
)
from ybe.tags import (
    read_tags_yaml,
    register_available_tags,
    save_tags_yaml,
    tags_yaml_path,
    write_image_tags,
)
from ybe.userconfig import (
    DISABLED_KIND_KEYS,
    _disabled_extensions,
    _load_recent,
    _load_settings,
    _load_views,
    _push_recent,
    _restore_tags_dir,
    _restore_view,
    _save_view,
    _set_extension_disabled,
    _update_settings,
)
from ybe.update import (
    _http_get_text,
    _update_payload,
    changelog_for,
    check_for_update,
    fetch_latest_version,
    load_changes,
    parse_changes,
    read_version,
    start_update_checker,
    update_status,
)
from ybe.server import app


# --------------------------------------------------------------------------- #
# dataset resume
# --------------------------------------------------------------------------- #
def _resume_last_dataset():
    """Activate the most recent still-existing data.yaml; None when there is none.

    Used at startup when `--data` is omitted, so a plain `python app.py` returns
    to the dataset last opened (the newest entry of `.recent_data_yamls.json`).
    """
    for path in _load_recent():
        if os.path.isfile(path) and _load_dataset(path):
            _restore_view(state.STATE["data_yaml"])
            return path
    state.STATE["data_yaml"] = None
    state.STATE["splits"] = []
    state.STATE["images"] = []
    return None


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="YOLO labelling app (Flask)")
    parser.add_argument("--data", help="path to data.yaml")
    parser.add_argument(
        "--home",
        help="folder holding your actions/ hooks/ filters/ scripts/ (default: "
        "$YBX_HOME, else the parent of app.py)",
    )
    parser.add_argument(
        "--allow-root",
        action="store_true",
        help="allow running as root (not recommended: written files become "
        "root-owned and the debug server runs with root privileges)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="serve as a read-only viewer (no saving labels)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log verbose messages to the browser console (see /api/config)",
    )
    parser.add_argument(
        "--flask-debug",
        action="store_true",
        help="enable the Werkzeug interactive debugger and auto-reloader "
        "(development only; never expose it on a public host)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="start on the settings screen instead of reopening the last dataset",
    )
    parser.add_argument(
        "--keep-pipe",
        action="store_true",
        help="keep the {PIPE_PATH} file after each action/hook run instead of deleting it",
    )
    parser.add_argument(
        "--keep-filter-pipes",
        action="store_true",
        help="keep the filter-chain input/output pipe files instead of deleting them",
    )
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="do not check GitHub for a newer version",
    )
    parser.add_argument(
        "--log-file",
        help="write logs to this file instead of stderr (used by daemon mode)",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="disable the auto-reloader (only relevant with --flask-debug)",
    )
    args = parser.parse_args()

    # Refuse to run as root by default. Written files become root-owned (and,
    # being 0600, unreadable by the normal user), sudo resets $YBX_HOME, and the
    # debug=True Werkzeug console would execute code with root privileges.
    # Containers commonly run as root, so this is an explicit opt-out, not a
    # hard block.
    is_root = getattr(os, "geteuid", lambda: -1)() == 0
    if is_root and not args.allow_root:
        parser.error(
            "refusing to run as root; pass --allow-root to override "
            "(written files would be root-owned and the debug server would run as root)"
        )

    # Resolve the user folder first: everything below reads/writes paths derived
    # from it, and the folders must exist before the first read.
    if args.home:
        configure_home(args.home)
    ensure_user_dirs()

    # The session key must be loaded before the first request; it is created once
    # and then reused across restarts and app updates.
    app.secret_key = load_or_create_secret_key()

    log = setup_logging(args.log_file, args.debug)
    log.info(
        "yolo-box-editor %s | user dir: %s (override with --home)", read_version(), config.YBX_HOME
    )
    if is_root:
        log.warning("running as root (--allow-root): files written will be owned by root")
    if args.flask_debug and args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "--flask-debug is on with host %s: the interactive debugger can run "
            "arbitrary code and must never be reachable from an untrusted network",
            args.host,
        )

    # Copy the run-wide toggles into the shared state the routes read.
    state.STATE["readonly"] = args.readonly
    state.STATE["debug"] = args.debug
    state.STATE["keep_pipe"] = args.keep_pipe
    state.STATE["keep_filter_pipes"] = args.keep_filter_pipes
    state.STATE["no_update_check"] = args.no_update_check

    # Load the login store. An empty store means no login (the local default);
    # register an account with `ybe users --create NAME` to turn the login gate
    # on (`ybe users` lists them, and those commands work while the app runs).
    load_users()

    # Background update check (a no-op with --no-update-check).
    start_update_checker()

    # Open the requested dataset, else resume the most recent one (unless the
    # user asked to start on the Settings screen).
    if args.data:
        _load_dataset(args.data)
        _push_recent(state.STATE["data_yaml"])
    elif not args.no_resume:
        _resume_last_dataset()

    log.info("serving on http://%s:%s", args.host, args.port)
    # The interactive debugger can execute code with the app's privileges, so it
    # stays off for normal use and only turns on with --flask-debug (development).
    app.run(
        host=args.host,
        port=args.port,
        debug=args.flask_debug,
        use_reloader=args.flask_debug and not args.no_reload,
    )


if __name__ == "__main__":
    main()
