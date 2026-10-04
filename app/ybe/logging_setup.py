"""Logging setup (stderr by default; a file when daemonized with --log-file).

Everything logs through the single root handler configured here, so the app's
own messages and Flask/Werkzeug's request lines land in the same place (stderr
in the foreground, or the log file when running as a background daemon).
"""

import logging
import os
import sys


class _SkipPresenceFilter(logging.Filter):
    """Drop the frequent `/api/presence` access-log lines (client heartbeat).

    Each open browser tab pings presence every few seconds; logging every ping
    would drown out everything else, so those lines are filtered out.
    """

    def filter(self, record):
        # Formatting a record must never blow up; on any error keep the line.
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging fail on formatting
            return True
        return "/api/presence" not in message


def setup_logging(log_file=None, debug=False):
    """Configure logging; with `log_file`, daemon-mode output goes to that file.

    Returns the app logger. Werkzeug's access logger is routed through the same
    handler, minus the `/api/presence` heartbeat.
    """
    level = logging.DEBUG if debug else logging.INFO

    # Start from a clean root logger: this runs on every start (and again after a
    # reloader restart), so drop any handlers a previous call installed.
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = None
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            handler = logging.FileHandler(log_file, encoding="utf-8")
        except OSError:
            handler = None  # fall back to stderr below
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Route Werkzeug through the root handler instead of its own console logger,
    # and apply the heartbeat filter there.
    werkzeug = logging.getLogger("werkzeug")
    werkzeug.setLevel(level)
    werkzeug.handlers = []  # use the root handler instead of its own console one
    werkzeug.propagate = True
    werkzeug.filters = [f for f in werkzeug.filters if not isinstance(f, _SkipPresenceFilter)]
    werkzeug.addFilter(_SkipPresenceFilter())

    return logging.getLogger("ybe")
