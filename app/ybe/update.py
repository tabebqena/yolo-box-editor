"""Update check: compare the shipped VERSION with the newest published one.

A cached result in `UPDATE_CHECK_FILE` avoids hammering GitHub; a background
thread re-checks periodically, and the cache enforces the weekly gap. All
network errors are swallowed so a check can never crash the app.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

from ybe import config, state
from ybe.parsing import _parse_version, _version_newer

_UPDATE_THREAD = None


def read_version():
    """The shipped app version, from app/VERSION (never raises)."""
    try:
        with open(config.VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return "unknown"


def _http_get_text(url, timeout=config.UPDATE_CHECK_TIMEOUT):
    """GET a URL and return its body as text (GitHub needs a User-Agent)."""
    req = urllib.request.Request(url, headers={"User-Agent": f"yolo-box-editor/{read_version()}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_latest_version(timeout=config.UPDATE_CHECK_TIMEOUT):
    """Newest published version, or None when it cannot be determined.

    Considers the latest release **and** every tag and returns the highest
    version (so a newer tag is not hidden by an older release), else the `main`
    branch's VERSION. Any network/parse error is swallowed.
    """
    candidates = []
    try:
        data = json.loads(_http_get_text(f"{config.UPDATE_API}/releases/latest", timeout))
        tag = str(data.get("tag_name") or "").strip().lstrip("vV")
        if tag:
            candidates.append(tag)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass
    try:
        data = json.loads(_http_get_text(f"{config.UPDATE_API}/tags", timeout))
        if isinstance(data, list):
            for entry in data:
                name = str((entry or {}).get("name") or "").strip().lstrip("vV")
                if name:
                    candidates.append(name)
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        pass

    parsed = [(v, name) for name, v in ((n, _parse_version(n)) for n in candidates) if v]
    if parsed:
        return max(parsed)[1]
    try:
        text = _http_get_text(f"{config.UPDATE_RAW}/main/app/VERSION", timeout).strip()
        if text:
            return text.splitlines()[0].strip()
    except (urllib.error.URLError, OSError):
        pass
    return candidates[0] if candidates else None


def parse_changes(text):
    """Parse the shipped CHANGES file into `{version: [lines]}`.

    A `## <version>` line starts a section; every following non-empty line is
    that version's changelog (a leading `- ` is stripped). Lines before the
    first section (the header comment) are ignored.
    """
    sections = {}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None and line:
            sections[current].append(line[2:].strip() if line.startswith("- ") else line)
    return sections


def load_changes():
    """The shipped CHANGES sections (empty on error)."""
    try:
        with open(config.CHANGES_FILE, encoding="utf-8") as f:
            return parse_changes(f.read())
    except OSError:
        return {}


def changelog_for(version):
    """The changelog lines for `version` (empty when it has no section)."""
    return load_changes().get((version or "").strip(), [])


def _load_update_cache():
    """The last update-check result, or {} when missing/invalid."""
    try:
        with open(config.UPDATE_CHECK_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_payload(info):
    """A stable UI shape built from a (possibly empty) cache entry."""
    current = info.get("current_version") or read_version()
    latest = info.get("latest_version")
    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": bool(latest) and _version_newer(latest, current),
        "checked_at": info.get("checked_at"),
    }


def update_status():
    """The cached update info; never touches the network (fast for /api/config)."""
    return _update_payload(_load_update_cache())


def check_for_update(force=False, now=None):
    """Check for a newer version, using/storing the cache, and return its payload.

    A network request is made only when `force` is set, the cache is missing, it
    is older than config.UPDATE_CHECK_INTERVAL, or the running version changed.
    """
    now = time.time() if now is None else now
    current = read_version()
    cache = _load_update_cache()
    checked_at = cache.get("checked_at")
    # The cache is "fresh" when it was checked within the interval *and* against
    # the same running version; otherwise (or when forced) hit the network.
    fresh = (
        isinstance(checked_at, (int, float))
        and now - checked_at < config.UPDATE_CHECK_INTERVAL
        and cache.get("current_version") == current
    )
    if fresh and not force:
        return _update_payload(cache)

    latest = fetch_latest_version()
    info = {
        "checked_at": now,
        "current_version": current,
        "latest_version": latest,
    }
    try:
        os.makedirs(os.path.dirname(config.UPDATE_CHECK_FILE), exist_ok=True)
        with open(config.UPDATE_CHECK_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
            f.write("\n")
    except OSError:
        pass
    return _update_payload(info)


def _update_check_loop():
    """Check now, then wake up periodically (the cache enforces the weekly gap)."""
    while True:
        try:
            check_for_update()
        except Exception:  # noqa: BLE001 - the checker must never crash the app
            pass
        time.sleep(config.UPDATE_POLL_INTERVAL)


def start_update_checker():
    """Start the background update checker once (no-op when disabled)."""
    global _UPDATE_THREAD
    if state.STATE.get("no_update_check"):
        return
    if _UPDATE_THREAD is not None and _UPDATE_THREAD.is_alive():
        return
    _UPDATE_THREAD = threading.Thread(target=_update_check_loop, name="update-check", daemon=True)
    _UPDATE_THREAD.start()
