"""Declared support registry for extension and plugin API versions.

The app parses extension files (actions, hooks, filters, widgets, packages) for
a **window** of the newest format versions. This module is the single place that
declares, per axis, which versions are supported and which were dropped, so a
future format change is an explicit decision rather than a guess.

Rules (see `config`):

* The app supports the newest `EXTENSION_API_SUPPORT_WINDOW` extension format
  versions (`min_supported()..EXTENSION_API_VERSION`).
* Files **older** than that window (or with no `api_version`) are not guaranteed:
  they are skipped with an explaining error, unless the user forces parsing with
  `--allow-old-extensions` (`config.ALLOW_OLD_EXTENSIONS`).
* Files **newer** than `EXTENSION_API_VERSION`, and versions listed in
  `EXTENSION_API_DROPPED`, are never parsed.
* Panels declaring `ui.api_version` newer than `PLUGIN_API_VERSION` are not
  loaded.
"""

import os

from ybe import config


def min_supported():
    """The oldest extension format version the app is responsible for."""
    window = max(1, config.EXTENSION_API_SUPPORT_WINDOW)
    return max(1, config.EXTENSION_API_VERSION - (window - 1))


def newest_extension_version():
    return config.EXTENSION_API_VERSION


def newest_plugin_version():
    return config.PLUGIN_API_VERSION


def support_status(version):
    """Classify an extension file's `api_version`.

    One of: "current", "supported", "too_old", "legacy" (no/invalid version),
    "dropped" or "newer".
    """
    if not isinstance(version, int):
        return "legacy"
    if version > config.EXTENSION_API_VERSION:
        return "newer"
    if version in config.EXTENSION_API_DROPPED:
        return "dropped"
    if version == config.EXTENSION_API_VERSION:
        return "current"
    if version >= min_supported():
        return "supported"
    return "too_old"


def is_allowed(version):
    """True when the app parses this version (older ones only when forced).

    Unversioned files ("legacy") are read best-effort — they predate versioning
    and are the original format. Only explicitly-versioned files below the
    support window need `--allow-old-extensions`.
    """
    status = support_status(version)
    if status in ("current", "supported", "legacy"):
        return True
    if status == "too_old":
        return bool(config.ALLOW_OLD_EXTENSIONS)
    return False  # "dropped" / "newer" are never parsed


def version_error(kind, path, version, label=None):
    """A skip message for a version the app will not parse, else None.

    `kind` is the folder kind ("actions", "hooks", "filters", "widgets",
    "extensions"); `path` is the file the message points at; `label` overrides
    the displayed file name.
    """
    status = support_status(version)
    name = label or os.path.basename(path)
    if status in ("current", "supported", "legacy"):
        return None  # legacy (unversioned) files are read best-effort
    if status == "newer":
        return ("'%s/%s': written for extension format v%s, but this app supports "
                "v%s — update yolo-box-editor to use it" % (
                    kind, name, version, config.EXTENSION_API_VERSION))
    if status == "dropped":
        return ("'%s/%s': support for extension format v%s was dropped — update "
                "the file to a supported version (v%s..v%s)" % (
                    kind, name, version, min_supported(), config.EXTENSION_API_VERSION))
    # "too_old": an explicit version below the support window
    if config.ALLOW_OLD_EXTENSIONS:
        return None
    return ("'%s/%s': written for extension format v%s, but this app supports the "
            "last %d versions (v%s..v%s) — update the file, or start the app with "
            "--allow-old-extensions to force it" % (
                kind, name, version, config.EXTENSION_API_SUPPORT_WINDOW,
                min_supported(), config.EXTENSION_API_VERSION))


def is_dropped(version):
    return isinstance(version, int) and version in config.EXTENSION_API_DROPPED


def support_table():
    """The declared support matrix, for `/api/config` and the docs."""
    return {
        "extension": {
            "newest": config.EXTENSION_API_VERSION,
            "window": config.EXTENSION_API_SUPPORT_WINDOW,
            "min_supported": min_supported(),
            "history": [{"version": v, "summary": s}
                        for v, s in config.EXTENSION_API_HISTORY],
            "dropped": list(config.EXTENSION_API_DROPPED),
            "kinds": ["actions", "hooks", "filters", "widgets", "extensions"],
            "allow_old": bool(config.ALLOW_OLD_EXTENSIONS),
        },
        "plugin": {
            "newest": config.PLUGIN_API_VERSION,
            "history": [{"version": v, "summary": s}
                        for v, s in config.PLUGIN_API_HISTORY],
            "dropped": list(config.PLUGIN_API_DROPPED),
        },
        "note": (
            "This app is responsible for the last %d extension format versions "
            "(v%d..v%d); older files are skipped unless --allow-old-extensions "
            "is set. Files newer than v%d, and panels newer than plugin API v%d, "
            "are not read." % (
                config.EXTENSION_API_SUPPORT_WINDOW, min_supported(),
                config.EXTENSION_API_VERSION, config.EXTENSION_API_VERSION,
                config.PLUGIN_API_VERSION)
        ),
    }
