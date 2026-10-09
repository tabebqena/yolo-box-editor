#!/usr/bin/env python3
"""Enable/disable the tags extension from the old tag-bar visibility setting.

Run after an install or update (the installer does this automatically) or by
hand:

    python app/scripts/migrate_tags_extension.py --home <user folder>
    python app/scripts/migrate_tags_extension.py --home <user folder> --disable

With no `--enable`/`--disable` a fresh install (no user config yet) enables the
tags extension, while an existing install keeps whatever the old `tags` /
`ybe_tags_visible` setting was. Either way the result is the durable
`<home>/extensions.json` override, so later updates do not reset it.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ybe import config, extension_flags  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="the user folder (default: $YBX_HOME)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true", help="force-enable the tags extension")
    group.add_argument("--disable", action="store_true", help="force-disable the tags extension")
    args = parser.parse_args(argv)
    if args.home:
        config.configure_home(args.home)
    if args.enable:
        enabled = extension_flags.set_flag("tags", True)
    elif args.disable:
        enabled = extension_flags.set_flag("tags", False)
    else:
        enabled = extension_flags.migrate_tags_flag()
    print("tags extension: %s" % ("enabled" if enabled else "disabled"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
