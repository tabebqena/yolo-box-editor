#!/usr/bin/env python3
"""Thin entry point for the `ybe` launcher.

The installed `yolo-box-editor` command is a one-line shim that runs this file
with the virtual environment's Python; the real logic lives in `ybe.launcher`.
Running it directly from a clone works too (`python app/launcher.py status`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ybe.launcher import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main())
