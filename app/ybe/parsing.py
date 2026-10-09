"""Pure text / YAML / shortcut parsing helpers.

The app deliberately ships without PyYAML: the small subset of YAML it needs
(one-line scalars, a bare `- item` list, and indented blocks) is parsed by hand
here. These functions never touch shared configuration or runtime state, so they
are free of the module-level globals the routes mutate. They only read the paths
they are given and return plain data.

Conventions used throughout: a `#` starts a comment to the end of the line
(unless it is inside quotes, which this simple parser does not try to honour),
and one layer of matching single/double quotes is stripped from scalars.
"""

import re


def _strip_comment(s):
    """Drop everything from the first `#` and trim the surrounding space."""
    return s.split("#", 1)[0].strip()


def _parse_yaml_names_value(value):
    """Parse a `names:` value into a list of class/tag names.

    Handles the three shapes seen in real data.yaml files:
      - an inline list:      [fire, smoke]
      - a block of items:    - fire   /  - smoke
      - a block of keyed items:  0: fire  /  1: smoke
    Quotes are stripped from each name and blank entries are dropped.
    """
    value = _strip_comment(value.strip())
    if not value:
        return []
    # inline list: [fire, smoke]
    if value.startswith("["):
        inner = value[1 : value.rfind("]")]  # text between [ and the last ]
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    names = []
    for raw in value.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("-"):
            name = line[1:].strip().strip("'\"")
            if name:
                names.append(name)
        elif ":" in line:
            # keyed block form: keep the part after the colon
            name = line.split(":", 1)[1].strip().strip("'\"")
            if name:
                names.append(name)
    return names


def _extract_yaml_block(lines, key):
    """Return the indented block that follows a top-level `key:` line.

    The block starts on the key's own line (if it has an inline value) and keeps
    every following line that is indented deeper than `key:`; the first line at
    the same or a shallower indent ends it. Returns None when `key:` is absent.
    Used for block-form `names:` lists.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(key + ":"):
            continue
        indent = len(line) - len(line.lstrip())  # indentation of the key line
        block = []
        first = _strip_comment(stripped.split(":", 1)[1])
        if first:
            block.append(first)
        for ln in lines[i + 1 :]:
            s = ln.strip()
            if not s:
                block.append(s)  # keep blank lines inside the block
                continue
            cur_indent = len(ln) - len(ln.lstrip())
            if cur_indent <= indent:
                break  # dedented back out of the block
            block.append(_strip_comment(s))
        return "\n".join(block).strip()
    return None


def _read_yaml_names(path):
    """The `names:` class list from a data.yaml file ([] when missing/absent)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    value = _extract_yaml_block(lines, "names")
    return _parse_yaml_names_value(value or "")


def _parse_data_yaml(path):
    """Read the handful of keys this app understands from a data.yaml.

    Returns a dict with any of: `names` (list), `path`, `train`, `val`, `test`
    (strings) and `nc` (int). Unknown keys and unreadable files are ignored, so
    this never raises — callers only need the keys they use.
    """
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return data

    # `names` may span several indented lines, so it gets the block parser.
    names = _read_yaml_names(path)
    if names:
        data["names"] = names

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = _strip_comment(value).strip().strip("'\"")
        if key in ("path", "train", "val", "test") and value:
            data[key] = value
        elif key == "nc":
            try:
                data["nc"] = int(float(value))  # tolerate "3" and "3.0"
            except ValueError:
                pass
    return data


def _read_text_lines(path):
    """File contents as a list of lines; [] when the file is missing/unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except OSError:
        return []


def _read_text(path):
    """Whole-file text; "" when the file is missing/unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _yaml_scalar(s):
    """Strip one layer of matching single/double quotes from a YAML scalar."""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_api_version(value):
    """Parse an `api_version:` scalar to an int, or None when absent/invalid."""
    value = _yaml_scalar(_strip_comment(value or "").strip())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_version(value):
    """`v2.2.0` -> (2, 2, 0); None when there is no leading numeric part."""
    if value is None:
        return None
    match = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _version_newer(candidate, current):
    """True when `candidate` is a strictly newer version than `current`."""
    a, b = _parse_version(candidate), _parse_version(current)
    if a is None or b is None:
        return False
    # Pad the shorter tuple with zeros so (2, 2) and (2, 2, 0) compare equal.
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a > b


def _line_comment(line):
    """Whole-line comments only; labels may contain '#'."""
    return line.startswith("#")


def parse_shortcut_line(line):
    """One optionally-inline line  NAME <SHORTCUT> label  -> (name, shortcut, label).

    The shortcut is whatever sits between the first `<` and the next `>`; the
    label is the free text after `>` (it may be empty and may contain spaces).
    Returns None for a blank/comment line or a malformed one, so callers can just
    skip it.
    """
    line = line.strip()
    if not line or _line_comment(line):
        return None
    parts = line.split(None, 1)  # split off the action name; keep the rest intact
    if len(parts) < 2:
        return None
    name = parts[0]
    rest = parts[1]
    start = rest.find("<")
    end = rest.find(">", start + 1)
    if start < 0 or end < 0:
        return None  # malformed: no <SHORTCUT> brackets
    shortcut = rest[start + 1 : end].strip()
    label = rest[end + 1 :].strip()
    if not shortcut:
        return None
    return name, shortcut, label



