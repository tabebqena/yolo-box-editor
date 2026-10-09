"""User/shipped custom widgets: YAML files that render a small control panel.

A widget is one YAML file with a list of `controls` (buttons, selects,
checkboxes and text inputs). A button runs an action (by name) or an inline
`steps` / `after_success` list; the other controls are state only and their
values are passed to the button's action as `WIDGET_<ID>` placeholders.

Like the action/hook/filter loaders, the shipped `app/widgets/` folder is read
first and the user's `<home>/widgets/` second (the user file wins on a name
clash), and every file is read fresh from disk (no cache). No function here runs
anything — loading only builds plain dicts.
"""

import os
import re

from ybe import config
from ybe.packages import extension_sources
from ybe.parsing import (
    _parse_api_version,
    _parse_yaml_names_value,
    _read_text,
    _strip_comment,
    _yaml_scalar,
)

# The controls a widget may contain.
WIDGET_CONTROL_TYPES = ("button", "select", "checkbox", "input")
# A control id (become the {WIDGET_<ID>} placeholder, upper-cased).
_WIDGET_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _set_control_field(ctrl, key, value):
    """Set one control field; return the nested list a later `- item` fills.

    Returns "options", "steps" or "after_success" for a block list, else None.
    """
    value = _strip_comment(value)
    if key == "type":
        ctrl["type"] = _yaml_scalar(value)
    elif key == "id":
        ctrl["id"] = _yaml_scalar(value)
    elif key == "label":
        ctrl["label"] = _yaml_scalar(value)
    elif key == "action":
        ctrl["action"] = _yaml_scalar(value)
    elif key == "placeholder":
        ctrl["placeholder"] = _yaml_scalar(value)
    elif key == "default":
        ctrl["default"] = _yaml_scalar(value) if value else ""
    elif key in ("options", "steps", "after_success"):
        if key == "options":
            if value.startswith("["):
                ctrl["options"] = _parse_yaml_names_value(value)
                return None
            if value:
                ctrl["options"] = [_yaml_scalar(p) for p in value.split(",") if p.strip()]
                return None
            ctrl["options"] = []
        else:
            if value and value != "[]":
                ctrl[key].append(_yaml_scalar(value))
        return key
    return None


def _parse_widget_file(text):
    """Parse one widget YAML file into a dict of its keys.

    Format (2-space indentation, whole-line # comments):
        api_version: 3
        name: My Tools            # optional; the file name is used otherwise
        title: My Tools           # optional; shown in the frame header
        controls:
          - type: button
            label: Clean
            action: MyAction       # a named action ...
          - type: button
            label: Inline
            steps:                 # ... or inline steps / after_success
              - echo {WIDGET_MODE}
          - type: select
            id: mode
            label: Mode
            options: [fast, safe]  # inline or a block of `- item` lines
            default: safe
          - type: checkbox
            id: dry_run
            label: Dry run
            default: true
          - type: input
            id: suffix
            label: Suffix
            placeholder: _v2
            default: ""
    """
    data = {"name": None, "title": None, "description": None, "active": True,
            "api_version": None, "controls": []}
    mode, current, ctrl_indent, sub = None, None, None, None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            mode, current, ctrl_indent, sub = None, None, None, None
            if key == "name":
                if value:
                    data["name"] = _yaml_scalar(value)
            elif key == "api_version":
                data["api_version"] = _parse_api_version(value)
            elif key in ("title", "description"):
                if value:
                    data[key] = _yaml_scalar(value)
            elif key == "active":
                if value:
                    data["active"] = value.lower() not in ("false", "no", "0")
            elif key == "controls":
                mode = "controls"
            continue
        if mode != "controls":
            continue
        if stripped.startswith("- ") and (ctrl_indent is None or indent <= ctrl_indent):
            if ctrl_indent is None:
                ctrl_indent = indent  # remember the first control's indent
            current = {"type": None, "id": None, "label": None, "action": None,
                       "placeholder": None, "default": None, "options": None,
                       "steps": [], "after_success": []}
            data["controls"].append(current)
            sub = None
            rest = stripped[2:].strip()
            if ":" in rest:
                field, _, value = rest.partition(":")
                sub = _set_control_field(current, field.strip(), value.strip())
            continue
        if current is None:
            continue
        if sub in ("options", "steps", "after_success") and stripped.startswith("- "):
            item = _yaml_scalar(stripped[2:].strip())
            if sub == "options":
                current["options"].append(item)
            else:
                current[sub].append(item)
            continue
        if ":" in stripped:
            field, _, value = stripped.partition(":")
            sub = _set_control_field(current, field.strip(), value.strip())
    return data


def _truthy(value, default=False):
    """Coerce a scalar to a bool; `default` when it is None/empty."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "no", "0", "off")


def _validate_widget(fname, data):
    """Normalize a parsed widget; return (widget, errors).

    A single bad control drops the whole widget (like a bad filter argument), so
    the caller reports the error and the widget is not offered.
    """
    errors = []
    name = (data.get("name") or "").strip() or fname[: -len(".yaml")]
    controls, seen = [], set()
    for raw in data.get("controls") or []:
        ctype = (raw.get("type") or "").strip().lower()
        if ctype not in WIDGET_CONTROL_TYPES:
            errors.append(f"'widgets/{fname}': widget \"{name}\": unknown control "
                          f"type \"{raw.get('type')}\" (use button, select, checkbox or input)")
            return None, errors
        ctrl_id = (raw.get("id") or "").strip()
        if ctype != "button":
            if not ctrl_id:
                errors.append(f"'widgets/{fname}': widget \"{name}\": a {ctype} control needs an id")
                return None, errors
            if not _WIDGET_ID_RE.match(ctrl_id):
                errors.append(f"'widgets/{fname}': widget \"{name}\": invalid control id "
                              f"\"{ctrl_id}\" (letters, digits and _ only; cannot start with a digit)")
                return None, errors
            if ctrl_id in seen:
                errors.append(f"'widgets/{fname}': widget \"{name}\": duplicate control id \"{ctrl_id}\"")
                return None, errors
            seen.add(ctrl_id)

        label = (raw.get("label") or "").strip()
        if ctype == "button":
            action = (raw.get("action") or "").strip() or None
            steps = [s for s in (raw.get("steps") or []) if str(s).strip()]
            after = [s for s in (raw.get("after_success") or []) if str(s).strip()]
            if not action and not steps and not after:
                errors.append(f"'widgets/{fname}': widget \"{name}\": a button needs an "
                              f"action or steps")
                return None, errors
            controls.append({"type": "button", "label": label or action or "Run",
                             "action": action, "steps": steps, "after_success": after})
        elif ctype == "select":
            options = [str(o) for o in (raw.get("options") or []) if str(o).strip()]
            if not options:
                errors.append(f"'widgets/{fname}': widget \"{name}\": select \"{ctrl_id}\" "
                              f"needs options")
                return None, errors
            default = str(raw.get("default") or "")
            if default not in options:
                default = options[0]
            controls.append({"type": "select", "id": ctrl_id, "label": label or ctrl_id,
                             "options": options, "default": default})
        elif ctype == "checkbox":
            controls.append({"type": "checkbox", "id": ctrl_id, "label": label or ctrl_id,
                             "default": _truthy(raw.get("default"), False)})
        else:  # input
            controls.append({"type": "input", "id": ctrl_id, "label": label or ctrl_id,
                             "default": str(raw.get("default") or ""),
                             "placeholder": str(raw.get("placeholder") or "")})
    if not controls:
        errors.append(f"'widgets/{fname}': widget \"{name}\": no usable controls")
        return None, errors
    return {
        "name": name,
        "title": (data.get("title") or name).strip(),
        "description": (data.get("description") or "").strip(),
        "controls": controls,
        "api_version": data.get("api_version"),
        "path": os.path.join(config.USER_WIDGETS_DIR, fname),
    }, errors


def _widget_files(dirpath):
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


def load_widgets():
    """Parse the widgets/ folders into (widgets, errors) (read fresh).

    One widget per `.yaml` file; its name is the `name:` key, else the file name.
    `active: false` and files with no usable controls are skipped. The shipped
    app/widgets/ folder is read first, the user's <home>/widgets/ second (it wins
    on a name clash).
    """
    merged, errors = {}, []
    for source, dirpath, pkg in extension_sources("widget"):
        for path in _widget_files(dirpath):
            fname = os.path.basename(path)
            data = _parse_widget_file(_read_text(path))
            if not data["active"] or not data["controls"]:
                continue  # inactive, or a comments-only template
            widget, widget_errors = _validate_widget(fname, data)
            if widget is None:
                errors.extend(widget_errors)
                continue
            widget["source"] = source
            widget["package"] = pkg
            widget["path"] = path
            merged[widget["name"]] = widget
    return merged, errors


def widget_file_for(name):
    """Resolve a loaded widget to its winning file, or None."""
    widget = load_widgets()[0].get(name)
    if widget is None:
        return None
    return {
        "kind": "widget",
        "name": widget["name"],
        "path": widget["path"],
        "source": widget["source"],
        "package": widget.get("package"),
        "api_version": widget["api_version"],
    }


def sanitize_widget_values(raw):
    """Validate submitted control values -> (values, error).

    Keys must look like a control id; the placeholder becomes `WIDGET_<ID>`
    (upper-cased). Values are stringified, control characters stripped and
    capped at 500 characters.
    """
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "values must be an object"
    values = {}
    for key, value in raw.items():
        key = str(key).strip()
        if not _WIDGET_ID_RE.match(key):
            return None, f'invalid control id "{key}"'
        text = "" if value is None else str(value)
        text = "".join(ch for ch in text if ord(ch) >= 32)
        values["WIDGET_" + key.upper()] = text[:500]
    return values, None
