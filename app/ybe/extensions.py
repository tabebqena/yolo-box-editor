"""User/shipped extension definitions: actions, hooks and filters.

An "extension" is one YAML file: an action (`steps`, optional `after_success`), a
hook (same shape, plus the event it fires on) or a filter (a command pipeline
that narrows the image list, plus optional typed arguments). This module parses
and loads those files, validates filter arguments, and provides the hand-written
writer the in-browser editor uses.

Two rules matter everywhere here:

  - the shipped `app/actions|hooks|filters/` folder is read first and the user's
    `<home>/...` folder second, so a user file with the same name wins;
  - everything is read fresh from disk (there is no cache), so editing a file and
    reloading is enough to see the change.

No function here executes a command — loading only builds plain dicts.
"""

import os
import re

from ybe import config, state
from ybe.packages import extension_sources
from ybe.parsing import (
    _parse_api_version,
    _parse_yaml_names_value,
    _read_text,
    _strip_comment,
    _yaml_scalar,
)


def _placeholder_payload(catalog):
    """`config.ACTION_PLACEHOLDERS` -> the UI shape `{token, description}`."""
    return [
        {"token": "{" + name + "}", "name": name, "description": desc}
        for name, desc in catalog
    ]


def api_version_status(version):
    """Classify a file's `api_version` against `config.EXTENSION_API_VERSION`.

    Returns "current", "outdated" (missing or lower) or "newer" (higher); a
    non-integer value counts as outdated.
    """
    if not isinstance(version, int):
        return "outdated"
    if version < config.EXTENSION_API_VERSION:
        return "outdated"
    if version > config.EXTENSION_API_VERSION:
        return "newer"
    return "current"


def is_hook_name(name):
    """True when `name` looks like a hook name (`on_*`)."""
    return bool(name) and name.startswith(config.HOOK_PREFIX)


def _parse_action_file(text):
    """Parse one action/hook file into a dict of its top-level keys.

    Top-level keys (2-space indentation, whole-line # comments):
        name: Remove            # optional; the file name is used otherwise
        event_name: after_save  # hooks only: fallback event when the file
                                # name does not encode one
        active: false           # hooks only: ignore this file
        steps:
          - rm -f {IMAGE_PATH}
        after_success:
          - app_refresh_images_list
    `steps` and `after_success` may also be a single value on the key line.
    """
    data = {
        "name": None,
        "event_name": None,
        "active": True,
        "api_version": None,
        "steps": [],
        "after_success": [],
    }
    # `section` remembers which list a later `  - item` line belongs to. A new
    # top-level key resets it, so only a `steps:`/`after_success:` header makes
    # the following dash lines append to that list.
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue  # blank or whole-line comment
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            # A top-level `key: value` line (the only keys we understand).
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if key == "name":
                section = None
                if value:
                    data["name"] = _yaml_scalar(value)
            elif key == "api_version":
                section = None
                data["api_version"] = _parse_api_version(value)
            elif key == "event_name":
                section = None
                if value:
                    data["event_name"] = _yaml_scalar(value)
            elif key == "active":
                section = None
                if value:
                    data["active"] = value.lower() not in ("false", "no", "0")
            elif key in ("steps", "after_success"):
                section = data[key]
                if value and value != "[]":
                    section.append(_yaml_scalar(value))  # single value on the key line
            else:
                section = None
        elif section is not None and stripped.startswith("- "):
            section.append(_yaml_scalar(stripped[2:].strip()))
    return data


def _action_files(dirpath):
    """Sorted `.yaml` paths in `dirpath`."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(dirpath, fname)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def _action_name(path, explicit):
    """The action's name: its `name:` key when given, else the file name."""
    if explicit:
        return explicit
    fname = os.path.basename(path)
    return fname[: -len(".yaml")]


def load_actions():
    """Parse the actions/ folders into entries (read fresh).

    One action per `.yaml` file (name from its `name:` key or the file name).
    Returns [{"name": ..., "steps": [...], "after_success": [...]}]; entries with
    neither steps nor after_success are dropped. The shipped app/actions/ folder
    is read first, the user's <home>/actions/ second (it wins on a name clash).
    """
    merged = {}
    for source, dirpath, pkg in extension_sources("action"):
        for path in _action_files(dirpath):
            data = _parse_action_file(_read_text(path))
            name = _action_name(path, data["name"])
            if not name:
                continue
            if data["steps"] or data["after_success"]:
                merged[name] = {
                    "name": name,
                    "steps": data["steps"],
                    "after_success": data["after_success"],
                    "api_version": data["api_version"],
                    "source": source,
                    "package": pkg,
                    "path": path,
                }
    return list(merged.values())


def _hook_event(path, data):
    """The event a hook file fires: `on_<event>.yaml` first, then `event_name:`.

    Returns None when neither the file name nor the `event_name:` key names a
    known app event.
    """
    fname = os.path.basename(path)
    stem = fname[: -len(".yaml")]
    if is_hook_name(stem):
        event = stem[len(config.HOOK_PREFIX):]
        if event in config.HOOK_EVENTS:
            return event
    key_event = (data.get("event_name") or "").strip()
    if key_event in config.HOOK_EVENTS:
        return key_event
    return None


def load_hooks():
    """Parse the hooks/ directory into (hooks, errors) (read fresh).

    One hook per `.yaml` file; its name is the canonical `on_<event>` and the
    event comes from the file name or the `event_name:` key. `active: false`
    hooks are skipped. Templates (files with neither `steps` nor
    `after_success`, e.g. hooks/example.yaml) are ignored silently; a file that
    does define steps but names no known event is reported in `errors`. The
    shipped app/hooks/ folder is read first, the user's <home>/hooks/ second (it
    wins on an event clash).
    """
    merged = {}
    errors = []
    for source, dirpath, pkg in extension_sources("hook"):
        for path in _action_files(dirpath):
            data = _parse_action_file(_read_text(path))
            event = _hook_event(path, data)
            has_body = bool(data["steps"] or data["after_success"])
            if event is None:
                if has_body:
                    errors.append(
                        f"'hooks/{os.path.basename(path)}': no app event — name it "
                        f"on_<event>.yaml or set event_name: (known: "
                        f"{', '.join(config.HOOK_EVENTS)})"
                    )
                continue
            if not data["active"] or not has_body:
                continue
            name = config.HOOK_PREFIX + event
            merged[name] = {
                "name": name,
                "event": event,
                "steps": data["steps"],
                "after_success": data["after_success"],
                "api_version": data["api_version"],
                "source": source,
                "package": pkg,
                "path": path,
            }
    return list(merged.values()), errors


# --------------------------------------------------------------------------- #
# filters/ (one YAML file per filter; narrows the loaded image list)
# --------------------------------------------------------------------------- #
# Placeholders a filter argument may never shadow (defined by the app).
FILTER_RESERVED_PLACEHOLDERS = {
    "DATASET_PATH",
    "DATA_YAML_PATH",
    "APP_DIR",
    "HOME_DIR",
    "APP_SCRIPT_DIR",
    "USER_SCRIPT_DIR",
    "PYTHON",
    "SPLIT",
    "INPUT_PIPE",
    "OUTPUT_PIPE",
    "TAGS_DIR",
}
# A filter argument name; its in-place placeholder is the upper-cased name.
_FILTER_ARG_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Dynamic option tokens: expand to the loaded dataset's class / tag names.
FILTER_CLASS_NAMES_TOKEN = "{DATASET_CLASS_NAMES}"
FILTER_TAG_NAMES_TOKEN = "{DATASET_TAG_NAMES}"


def resolve_filter_options(options, classes, tags=None):
    """Expand dynamic option tokens (e.g. `{DATASET_CLASS_NAMES}`, `{DATASET_TAG_NAMES}`).

    Non-token options are kept as-is; a token expands in place (deduplicated).
    Used both to fill the UI dropdown and to validate a submitted value.
    """
    if not options:
        return options
    resolved = []
    for opt in options:
        if opt == FILTER_CLASS_NAMES_TOKEN:
            values = classes
        elif opt == FILTER_TAG_NAMES_TOKEN:
            values = tags or []
        else:
            values = [opt]
        for value in values:
            if value and value not in resolved:
                resolved.append(value)
    return resolved


def _set_filter_arg_field(arg, key, value):
    """Set one argument field; return True while a block `options:` list may follow."""
    value = _strip_comment(value)
    if key == "name":
        arg["name"] = _yaml_scalar(value)
    elif key == "required":
        arg["required"] = value.lower() not in ("false", "no", "0", "")
    elif key == "default":
        arg["default"] = _yaml_scalar(value) if value else None
    elif key == "options":
        if value.startswith("["):
            arg["options"] = _parse_yaml_names_value(value)
        elif value:
            arg["options"] = [_yaml_scalar(p) for p in value.split(",") if p.strip()]
        else:
            arg["options"] = []
            return True
    return False


def _parse_filter_file(text):
    """Parse one filter YAML file into a dict of its keys.

    Format (2-space indentation, whole-line # comments):
        name: Keep every N-th   # optional; the file name is used otherwise
        description: ...        # optional
        active: true            # optional; false hides the filter
        arguments:              # optional list of dicts
          - name: every         # -> the in-place placeholder {EVERY}
            required: false
            default: "2"
            options: ["2", "3"]  # inline list, or a block of `- item` lines
        steps:                  # one shell command per entry
          - python {APP_SCRIPT_DIR}/x.py ... {EVERY}
    `steps` may also be a single value on the key line.
    """
    data = {"name": None, "description": None, "active": True,
            "api_version": None, "arguments": [], "steps": []}
    # `mode` is the list we are currently filling ("steps" / "arguments"), reset
    # by every top-level key. Within "arguments", `current` is the argument dict
    # being built, and `options_pending` is True while a `- item` line should be
    # collected as an option of that argument rather than start a new argument.
    mode, current, arg_indent, options_pending = None, None, None, False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            mode, current, arg_indent, options_pending = None, None, None, False
            if key == "name":
                if value:
                    data["name"] = _yaml_scalar(value)
            elif key == "api_version":
                data["api_version"] = _parse_api_version(value)
            elif key == "description":
                if value:
                    data["description"] = _yaml_scalar(value)
            elif key == "active":
                if value:
                    data["active"] = value.lower() not in ("false", "no", "0")
            elif key == "arguments":
                mode = "arguments"
            elif key == "steps":
                mode = "steps"
                if value and value != "[]":
                    data["steps"].append(_yaml_scalar(value))
            continue
        if mode == "steps":
            if stripped.startswith("- "):
                data["steps"].append(_yaml_scalar(stripped[2:].strip()))
        elif mode == "arguments":
            # A dash at the arguments' own indent level starts the next argument.
            if stripped.startswith("- ") and (arg_indent is None or indent <= arg_indent):
                if arg_indent is None:
                    arg_indent = indent  # remember the first argument's indent
                current = {"name": None, "required": False,
                           "default": None, "options": None}
                data["arguments"].append(current)
                options_pending = False
                rest = stripped[2:].strip()
                if ":" in rest:  # `- name: every`
                    field, _, value = rest.partition(":")
                    options_pending = _set_filter_arg_field(current, field.strip(), value.strip())
            elif current is not None:
                if options_pending and stripped.startswith("- "):
                    # block form:  options:  then  - "2"  /  - "3"
                    current["options"].append(_yaml_scalar(stripped[2:].strip()))
                elif ":" in stripped:
                    field, _, value = stripped.partition(":")
                    options_pending = _set_filter_arg_field(current, field.strip(), value.strip())
    return data


def _validate_filter_arguments(fname, filter_name, raw_args):
    """Normalize a filter's `arguments`; return (arguments, errors).

    An invalid name or a collision with a reserved placeholder drops the whole
    filter: the caller reports every error and skips it.
    """
    arguments, errors, seen = [], [], set()
    for raw in raw_args:
        arg_name = (raw.get("name") or "").strip()
        if not arg_name:
            errors.append(f"'filters/{fname}': filter \"{filter_name}\": an argument has no name")
            return [], errors
        if not _FILTER_ARG_NAME_RE.match(arg_name):
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": invalid argument name "
                f"\"{arg_name}\" (letters, digits and _ only; cannot start with a digit)")
            return [], errors
        if arg_name.upper() in FILTER_RESERVED_PLACEHOLDERS:
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": argument \"{arg_name}\" "
                f"collides with the reserved placeholder {{{arg_name.upper()}}}")
            return [], errors
        if arg_name in seen:
            errors.append(
                f"'filters/{fname}': filter \"{filter_name}\": duplicate argument \"{arg_name}\"")
            return [], errors
        seen.add(arg_name)
        arguments.append({
            "name": arg_name,
            "required": bool(raw.get("required")),
            "default": raw.get("default"),
            "options": raw.get("options"),
        })
    return arguments, errors


def _filter_files(dirpath):
    """Sorted `.yaml` paths in `dirpath`."""
    if not os.path.isdir(dirpath):
        return []
    paths = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".yaml"):
            continue
        path = os.path.join(dirpath, fname)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def load_filters():
    """Parse the filters/ folders into (filters, errors) (read fresh).

    One filter per `.yaml` file; its name is the `name:` key, else the file name.
    `active: false` and files with no `steps` are skipped. An argument that is
    invalid or shadows a reserved placeholder drops the filter and is reported in
    `errors`. The shipped app/filters/ folder is read first, the user's
    <home>/filters/ second (it wins on a name clash).
    """
    merged, errors = {}, []
    for source, dirpath, pkg in extension_sources("filter"):
        for path in _filter_files(dirpath):
            data = _parse_filter_file(_read_text(path))
            fname = os.path.basename(path)
            name = (data["name"] or "").strip() or fname[: -len(".yaml")]
            if not name or not data["active"] or not data["steps"]:
                continue
            arguments, arg_errors = _validate_filter_arguments(fname, name, data["arguments"])
            if arg_errors:
                errors.extend(arg_errors)
                continue
            merged[name] = {
                "name": name,
                "description": (data["description"] or "").strip(),
                "arguments": arguments,
                "steps": data["steps"],
                "api_version": data["api_version"],
                "source": source,
                "package": pkg,
                "path": path,
            }
    return merged, errors


def effective_filter_arguments(flt, arguments):
    """The filter's arguments as `{name: value}`, user values over defaults.

    Every declared argument gets a value (its default when none was given); a
    missing default becomes an empty string.
    """
    provided = arguments if isinstance(arguments, dict) else {}
    effective = {}
    for arg in flt["arguments"]:
        value = provided.get(arg["name"])
        if value is None or (isinstance(value, str) and not value.strip()):
            value = arg.get("default")
        effective[arg["name"]] = "" if value is None else str(value)
    return effective


# --------------------------------------------------------------------------- #
# extension authoring (Settings > Actions / Hooks / Filters)
#
# The web editor writes user YAML in exactly the shape the parsers above read.
# A small hand-written writer is used (no PyYAML) so the runtime dependency stays
# Flask only; `_dump_action_file` / `_dump_filter_file` round-trip through
# `_parse_action_file` / `_parse_filter_file` (covered by tests).
# --------------------------------------------------------------------------- #
_EXTENSION_BAD_FILENAME = set('/\\<>:"|?*')
_EXTENSION_RESERVED_PREFIXES = ("app_", "backend_", "action_", "on_")


def _safe_extension_name(name):
    """A file-stem for a user action/filter name, or None when unsafe.

    Allows spaces, letters, digits, `.`, `_` and `-`; rejects path separators,
    control characters, the reserved action prefixes and a leading dot.
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or name in (".", "..") or len(name) > 80:
        return None
    if name.startswith(".") or name.startswith(_EXTENSION_RESERVED_PREFIXES):
        return None
    if any(ch in _EXTENSION_BAD_FILENAME or ord(ch) < 32 for ch in name):
        return None
    return name


def _yaml_quote(value):
    """Wrap a scalar in double quotes (round-trips through `_yaml_scalar`)."""
    return '"' + value + '"'


def _clean_extension_entries(raw):
    """Validate a `steps` / `after_success` list -> (entries, error).

    Each entry is a non-empty single-line string, stored verbatim (a shell
    command or an action reference).
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "steps must be a list"
    entries = []
    for item in raw:
        if not isinstance(item, str):
            return None, "each step must be text"
        text = item.strip()
        if not text:
            continue
        if any(ord(ch) < 32 for ch in text):
            return None, "a step contains a newline or control character"
        entries.append(text)
    return entries, None


def _clean_filter_arguments(raw):
    """Validate submitted filter arguments -> (arguments, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "arguments must be a list"
    cleaned, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "each argument must be an object"
        name = str(item.get("name") or "").strip()
        if not name:
            return None, "every argument needs a name"
        if not _FILTER_ARG_NAME_RE.match(name):
            return None, (
                f'invalid argument name "{name}" (letters, digits and _ only; '
                "cannot start with a digit)")
        if name.upper() in FILTER_RESERVED_PLACEHOLDERS:
            return None, f'argument "{name}" collides with {{{name.upper()}}}'
        if name in seen:
            return None, f'duplicate argument "{name}"'
        seen.add(name)
        default = item.get("default")
        if default is not None:
            default = str(default)
            if any(ord(ch) < 32 for ch in default) or "#" in default:
                return None, f'argument "{name}": default cannot contain # or newlines'
            if default == "":
                default = None
        options = item.get("options")
        if options is not None:
            if not isinstance(options, list):
                return None, f'argument "{name}": options must be a list'
            clean_options = []
            for opt in options:
                opt = str(opt).strip()
                if not opt:
                    continue
                if "," in opt or "#" in opt or any(ord(ch) < 32 for ch in opt):
                    return None, (
                        f'argument "{name}": an option cannot contain , # or newlines')
                if opt not in clean_options:
                    clean_options.append(opt)
            options = clean_options or None
        cleaned.append({
            "name": name,
            "required": bool(item.get("required")),
            "default": default,
            "options": options,
        })
    return cleaned, None


def _dump_action_file(steps, after_success, active=True,
                      api_version=config.EXTENSION_API_VERSION):
    """Serialize a `steps`/`after_success` file in the parser's own format."""
    lines = [f"api_version: {api_version}"]
    if not active:
        lines.append("active: false")
    for key, entries in (("steps", steps), ("after_success", after_success)):
        if entries:
            lines.append(f"{key}:")
            lines.extend("  - " + entry for entry in entries)
    return "\n".join(lines) + "\n"


def _dump_filter_file(description, active, arguments, steps,
                      api_version=config.EXTENSION_API_VERSION):
    """Serialize a filter file in the parser's own format."""
    lines = [f"api_version: {api_version}"]
    if description:
        lines.append("description: " + _yaml_quote(description))
    if not active:
        lines.append("active: false")
    if arguments:
        lines.append("arguments:")
        for arg in arguments:
            lines.append("  - name: " + arg["name"])
            if arg.get("required"):
                lines.append("    required: true")
            default = arg.get("default")
            if default is not None and str(default) != "":
                lines.append("    default: " + _yaml_quote(str(default)))
            options = arg.get("options")
            if options:
                rendered = ", ".join(_yaml_quote(str(o)) for o in options)
                lines.append(f"    options: [{rendered}]")
    if steps:
        lines.append("steps:")
        lines.extend("  - " + entry for entry in steps)
    return "\n".join(lines) + "\n"


def _bump_api_version_text(text, version=config.EXTENSION_API_VERSION):
    """Return `text` with its top-level `api_version:` set to `version`.

    Comments and every other line are preserved; when the key is absent it is
    inserted after the leading comment/blank block.
    """
    lines = text.splitlines()
    pattern = re.compile(r"^api_version\s*:")
    # Update the key in place when it exists (every other line is preserved).
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"api_version: {version}"
            return "\n".join(lines) + "\n"
    # Otherwise insert it after the leading comment/blank block, so the file's
    # header comment stays at the very top.
    insert_at = 0
    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if stripped and not stripped.startswith("#"):
            break
        insert_at += 1
    lines.insert(insert_at, f"api_version: {version}")
    return "\n".join(lines) + "\n"


def _parse_extension_text(kind, text):
    """Parse raw editor text with the parser for `kind`."""
    if kind in ("action", "hook"):
        return _parse_action_file(text)
    if kind == "widget":
        from ybe.widgets import _parse_widget_file
        return _parse_widget_file(text)
    return _parse_filter_file(text)


def _usable_extension_text(kind, parsed):
    """Whether parsed text defines a usable extension of `kind`."""
    if kind == "filter":
        return bool(parsed.get("steps"))
    if kind == "widget":
        from ybe.widgets import _validate_widget
        return _validate_widget("widget.yaml", parsed)[0] is not None
    return bool(parsed.get("steps") or parsed.get("after_success"))


def _extension_user_dir(kind):
    """The user folder a kind is written to (None for an unknown kind)."""
    return {
        "action": config.USER_ACTIONS_DIR,
        "hook": config.USER_HOOKS_DIR,
        "filter": config.USER_FILTERS_DIR,
        "widget": config.USER_WIDGETS_DIR,
    }.get(kind)


def extension_file_for(kind, name):
    """Resolve a loaded extension to its winning file, or None.

    Returns `{kind, name, path, source, api_version}`; `source` is "shipped" or
    "user". Only extensions the loaders accept (with a body) are resolvable.
    """
    entry = None
    if kind == "action":
        entry = next((a for a in load_actions() if a["name"] == name), None)
    elif kind == "hook":
        entry = next((h for h in load_hooks()[0] if h["name"] == name), None)
    elif kind == "filter":
        entry = load_filters()[0].get(name)
    elif kind == "widget":
        from ybe.widgets import widget_file_for
        return widget_file_for(name)
    if entry is None:
        return None
    return {
        "kind": kind,
        "name": name,
        "path": entry["path"],
        "source": entry["source"],
        "package": entry.get("package"),
        "api_version": entry.get("api_version"),
    }


def _extension_file_payload(found, text):
    """The UI shape for the raw YAML editor."""
    return {
        "ok": True,
        "kind": found["kind"],
        "name": found["name"],
        "source": found["source"],
        "path": found["path"],
        "api_version": found["api_version"],
        "status": api_version_status(found["api_version"]),
        "writable": found["source"] == "user" and not state.STATE["readonly"],
        "text": text,
    }
