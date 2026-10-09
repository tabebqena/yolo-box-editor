"""Per-user enable/disable overrides for extension packages.

A shipped package's `active:` lives in its manifest, which is code replaced on
upgrade. This module keeps a durable, user-owned override in
`<YBX_HOME>/extensions.json`:

    {"active": {"<package id>": true}}

so enabling or disabling a package survives updates. `load_packages` applies the
override after reading the manifests.

On first use the old tag-bar visibility setting is migrated into the `tags`
flag: a fresh install (no user config yet) enables the extension, while an
existing install keeps whatever the old `tags` / `ybe_tags_visible` setting was.
"""

import json
import os

from ybe import config


def flags_path():
    """Path of the user override file (`<YBX_HOME>/extensions.json`)."""
    return os.path.join(config.YBX_HOME, "extensions.json")


def load_flags():
    """The `{package id: bool}` active overrides ({} when absent/invalid)."""
    try:
        with open(flags_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    active = data.get("active") if isinstance(data, dict) else None
    if not isinstance(active, dict):
        return {}
    return {k: bool(v) for k, v in active.items() if isinstance(k, str)}


def save_flags(flags):
    """Write the overrides atomically; never raises."""
    path = flags_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"active": flags}, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass


def set_flag(package_id, enabled):
    """Record one package's override, preserving the others."""
    flags = load_flags()
    flags[package_id] = bool(enabled)
    save_flags(flags)
    return flags[package_id]


def active_override(package_id):
    """The override for a package, or None when it is unset."""
    return load_flags().get(package_id)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _truthy(value, default):
    """Best-effort bool for a config value stored as bool or string."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("0", "false", "no", "off"):
            return False
        if v in ("1", "true", "yes", "on"):
            return True
    return default


def read_old_tags_flag():
    """`(found, enabled)` read from the old user config.

    `found` is False on a fresh install (no user config yet), which the caller
    treats as "enable". A config with no explicit tag setting also enables, so
    an update keeps the previous default (tags shown).
    """
    settings = None
    cfg = _read_json(config.CONFIG_FILE)
    if isinstance(cfg, dict) and isinstance(cfg.get("settings"), dict):
        settings = cfg["settings"]
    else:
        legacy = _read_json(config.SETTINGS_FILE)
        if isinstance(legacy, dict):
            settings = legacy
    if settings is None:
        return False, True
    if "tags" in settings:
        return True, _truthy(settings.get("tags"), True)
    if "ybe_tags_visible" in settings:
        return True, _truthy(settings.get("ybe_tags_visible"), True)
    return True, True


def migrate_tags_flag():
    """Ensure the `tags` override exists, seeding it from the old config.

    Idempotent: an existing `tags` flag is never overwritten. Returns the
    effective value.
    """
    flags = load_flags()
    if "tags" in flags:
        return flags["tags"]
    _found, enabled = read_old_tags_flag()
    flags["tags"] = enabled
    save_flags(flags)
    return enabled


def ensure_migrated():
    """Run the one-time tag-flag migration (safe to call repeatedly)."""
    return migrate_tags_flag()
