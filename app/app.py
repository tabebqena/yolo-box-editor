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
"""

import argparse
import os
import sys

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
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USER,
    _prompt_password,
    _valid_username,
    auth_enabled,
    ensure_default_admin,
    load_users,
    set_user,
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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="serve as a read-only viewer (no saving labels)",
    )
    parser.add_argument(
        "--create-user",
        metavar="NAME",
        help="create a user (or reset a password) in the user store, prompting "
        "for the password, then exit",
    )
    parser.add_argument(
        "--list-users",
        action="store_true",
        help="list registered users, then exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log verbose messages to the browser console (see /api/config)",
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
        help="disable the Werkzeug auto-reloader (used by daemon mode)",
    )
    args = parser.parse_args()

    if args.home:
        configure_home(args.home)
    ensure_user_dirs()

    app.secret_key = load_or_create_secret_key()

    log = setup_logging(args.log_file, args.debug)
    log.info(
        "yolo-box-editor %s | user dir: %s (override with --home)", read_version(), config.YBX_HOME
    )

    state.STATE["readonly"] = args.readonly
    state.STATE["debug"] = args.debug
    state.STATE["keep_pipe"] = args.keep_pipe
    state.STATE["keep_filter_pipes"] = args.keep_filter_pipes
    state.STATE["no_update_check"] = args.no_update_check

    load_users()
    if ensure_default_admin():
        log.warning(
            "no users found: created the default account %r (password %r) — "
            "change it from the UI or with --create-user",
            DEFAULT_ADMIN_USER,
            DEFAULT_ADMIN_PASSWORD,
        )

    # Admin commands manage the user store and exit before the server starts.
    if args.list_users:
        for name in sorted(state.USERS):
            print(name)
        if not state.USERS:
            print(f"(no users registered in {config.USERS_FILE})")
        return

    if args.create_user:
        username = args.create_user
        if not _valid_username(username):
            parser.error("--create-user NAME must be non-empty and contain no ':'")
        password = _prompt_password()
        if password is None:
            sys.exit(1)
        try:
            action = set_user(username, password)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"{action} user {username!r} in {config.USERS_FILE}")
        return

    start_update_checker()

    if args.data:
        _load_dataset(args.data)
        _push_recent(state.STATE["data_yaml"])
    elif not args.no_resume:
        _resume_last_dataset()

    log.info("serving on http://%s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=True, use_reloader=not args.no_reload)


if __name__ == "__main__":
    main()
