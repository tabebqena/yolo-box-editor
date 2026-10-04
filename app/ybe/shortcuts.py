"""Keyboard-shortcut bindings: shipped defaults + user overrides.

`shortcuts.txt` lines are `ACTION_NAME <KEY> label`; the user copy is read after
the shipped one and wins per name. Writing only touches the user file.
"""

import os

from ybe import config
from ybe.extensions import load_actions, load_hooks
from ybe.parsing import _read_text, _read_text_lines, parse_shortcut_line


def load_shortcuts_from(path):
    """Parse one shortcuts.txt file into {name: {shortcut, label}} (read fresh)."""
    shortcuts = {}
    for raw in _read_text_lines(path):
        parsed = parse_shortcut_line(raw)
        if parsed is None:
            continue
        name, shortcut, label = parsed
        shortcuts[name] = {"shortcut": shortcut, "label": label}
    return shortcuts


def load_shortcuts():
    """Parse the shipped + user shortcuts.txt into {name: {shortcut, label}} (read fresh)."""
    shortcuts = load_shortcuts_from(config.SHORTCUTS_FILE)
    shortcuts.update(load_shortcuts_from(config.USER_SHORTCUTS_FILE))
    return shortcuts


def user_shortcut_names():
    """Names the user's shortcuts.txt overrides (read fresh)."""
    return set(load_shortcuts_from(config.USER_SHORTCUTS_FILE))


def _valid_shortcut(value):
    """A storable shortcut token, or None when it cannot be written safely."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(ch in value for ch in "<>\r\n"):
        return None
    return value


def write_user_shortcuts(sets, resets):
    """Upsert/remove shortcut overrides in the user shortcuts.txt.

    `sets` maps name -> shortcut; `resets` is an iterable of names whose override
    line is dropped (falling back to the shipped binding). Comments, blank lines
    and untouched entries are preserved. Returns the file path.
    """
    sets = dict(sets or {})
    resets = set(resets or [])
    merged = load_shortcuts()
    lines = _read_text(config.USER_SHORTCUTS_FILE).splitlines()

    out, written = [], set()
    for raw in lines:
        parsed = parse_shortcut_line(raw)
        if parsed is None:
            out.append(raw)
            continue
        name, _shortcut, label = parsed
        if name in resets:
            continue
        if name in sets:
            out.append(f"{name} <{sets[name]}> {label}".rstrip())
            written.add(name)
            continue
        out.append(raw)
    for name, shortcut in sets.items():
        if name in written:
            continue
        label = (merged.get(name) or {}).get("label", "")
        out.append(f"{name} <{shortcut}> {label}".rstrip())

    text = "\n".join(out)
    if text:
        text += "\n"
    os.makedirs(os.path.dirname(config.USER_SHORTCUTS_FILE) or ".", exist_ok=True)
    with open(config.USER_SHORTCUTS_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return config.USER_SHORTCUTS_FILE


def split_shortcuts(shortcuts):
    """Split raw shortcuts into (app, user) maps, collecting unknown names as errors."""
    user_names = {a["name"] for a in load_actions()}
    hook_names = {h["name"] for h in load_hooks()[0]}
    app, user, errors = {}, {}, []
    for name, info in shortcuts.items():
        if name in config.APP_ACTIONS:
            app[name] = info
        elif name in hook_names:
            errors.append(
                f"'shortcuts.txt': '{name}' is an event hook; hooks cannot be bound"
            )
        elif name in user_names:
            user[name] = info
        else:
            errors.append(
                f"'shortcuts.txt': unknown action '{name}' "
                f"(not an app action and not defined in the actions/ folder)"
            )
    return app, user, errors
