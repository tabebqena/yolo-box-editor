"""Pure text / YAML / shortcut parsing helpers.

These functions never touch shared configuration or runtime state, so they are
free of the module-level globals that the routes mutate. They only read the
paths they are given and return plain data.
"""

import re


def _strip_comment(s):
    return s.split("#", 1)[0].strip()


def _parse_yaml_names_value(value):
    value = _strip_comment(value.strip())
    if not value:
        return []
    # inline list: [fire, smoke]
    if value.startswith("["):
        inner = value[1 : value.rfind("]")]
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
            name = line.split(":", 1)[1].strip().strip("'\"")
            if name:
                names.append(name)
    return names


def _extract_yaml_block(lines, key):
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(key + ":"):
            continue
        indent = len(line) - len(line.lstrip())
        block = []
        first = _strip_comment(stripped.split(":", 1)[1])
        if first:
            block.append(first)
        for ln in lines[i + 1 :]:
            s = ln.strip()
            if not s:
                block.append(s)
                continue
            cur_indent = len(ln) - len(ln.lstrip())
            if cur_indent <= indent:
                break
            block.append(_strip_comment(s))
        return "\n".join(block).strip()
    return None


def _read_yaml_names(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    value = _extract_yaml_block(lines, "names")
    return _parse_yaml_names_value(value or "")


def _parse_data_yaml(path):
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return data

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
                data["nc"] = int(float(value))
            except ValueError:
                pass
    return data


def _read_text_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except OSError:
        return []


def _read_text(path):
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
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a > b


def _line_comment(line):
    """Whole-line comments only; labels may contain '#'."""
    return line.startswith("#")


def parse_shortcut_line(line):
    """One optionally-inline line  NAME <SHORTCUT> label  -> (name, shortcut, label)."""
    line = line.strip()
    if not line or _line_comment(line):
        return None
    parts = line.split(None, 1)
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


def _normalize_tags(raw):
    """Coerce arbitrary input into a clean, de-duplicated list of tag names."""
    tags = []
    if isinstance(raw, list):
        for t in raw:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if t and "\n" not in t and t not in tags:
                tags.append(t)
    return tags


def _read_tag_lines(path):
    """Read a per-image tag file: one tag name per line."""
    tags = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    tags.append(t)
    except OSError:
        pass
    return tags


def _is_toplevel_list_item(line):
    """True for a column-0 YAML list item (`- name`), not a nested one."""
    return (len(line) - len(line.lstrip()) == 0
            and _strip_comment(line.strip()).startswith("-"))


def _toplevel_list_names(lines):
    """Names from a bare, top-level YAML list (`- name` at column 0).

    `tags.yaml` is a plain list, one tag per line, each prefixed by ``- ``.
    Repeated leading markers are stripped too, matching `dataset_autotag.py`,
    so a file corrupted by an earlier buggy write is read back cleanly.
    """
    names = []
    for raw in lines:
        if not _is_toplevel_list_item(raw):
            continue
        name = _strip_comment(raw.strip())
        while name.startswith("-"):
            name = name[1:].strip()
        name = name.strip("'\"")
        if name:
            names.append(name)
    return names
