"""tags.yaml (available tags) and per-image tag files.

`tags.yaml` sits beside `data.yaml` and is a bare top-level `- tag` list;
each image's own tags live in a sibling file under the split's tags dir.
"""

import os

from ybe import state
from ybe.dataset import _split_by_name, tag_path
from ybe.parsing import (
    _is_toplevel_list_item,
    _normalize_tags,
    _strip_comment,
    _toplevel_list_names,
)


def tags_yaml_path():
    """Path of the dataset's tags.yaml (beside data.yaml), or None."""
    if not state.STATE["data_yaml"]:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(state.STATE["data_yaml"])), "tags.yaml")


def read_tags_yaml():
    """Read the available-tags list from the dataset's tags.yaml ([] if absent).

    The list is a bare YAML list; a nested `tags:` key is ignored.
    """
    path = tags_yaml_path()
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return _normalize_tags(_toplevel_list_names(lines))


def save_tags_yaml(tags):
    """Write `tags` to the dataset's tags.yaml as a plain list, one per row.

    The canonical shape is a bare top-level list, one tag per line, each
    prefixed by ``- ``:

        - fire
        - smoke

    Any other content is preserved: an old `tags:` key (with its block) is
    replaced in place, and a pre-existing bare list is rewritten. Returns the
    written path, or None when no dataset is loaded.
    """
    path = tags_yaml_path()
    if not path:
        return None
    tags = _normalize_tags(tags)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []

    # Drop a pre-existing bare list; it is rewritten below.
    lines = [ln for ln in lines if not _is_toplevel_list_item(ln)]

    out = []
    replaced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not replaced and _strip_comment(line.strip()).startswith("tags:"):
            for t in tags:
                out.append(f"- {t}\n")
            i += 1
            # skip the old tag block (list items only; stop at anything else)
            while i < len(lines) and _strip_comment(lines[i].strip()).startswith("-"):
                i += 1
            replaced = True
            continue
        out.append(line)
        i += 1

    if not replaced:
        if out and out[-1].strip():
            out.append("\n")
        for t in tags:
            out.append(f"- {t}\n")

    text = "".join(out)
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_image_tags(entry, tags):
    """Write one image's tag file (normalized, one tag per line).

    Creates the split's tags folder when needed. Returns the written path, or
    None when the split is unknown.
    """
    split = _split_by_name(entry["split"])
    path = tag_path(entry)
    if split is None or path is None:
        return None
    tags = _normalize_tags(tags)
    os.makedirs(split["tags_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(tags))
        if tags:
            f.write("\n")
    return path


def register_available_tags(tags):
    """Add tag names not yet in tags.yaml, preserving order.

    `tags.yaml` is rewritten only when there is at least one new name; when
    every name is already known the file is left untouched. Returns the
    resulting available-tags list ([] when no dataset is loaded).
    """
    available = read_tags_yaml()
    if tags_yaml_path() is None:
        return available
    fresh = [t for t in _normalize_tags(tags) if t not in available]
    if not fresh:
        return available
    available = available + fresh
    save_tags_yaml(available)
    return available
