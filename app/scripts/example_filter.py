#!/usr/bin/env python3
"""yolo-box-editor example filter helper.

A filter YAML file calls this script once per chain run to narrow the image
list. It reads the candidate image paths from the input pipe (one absolute path
per line) and writes the paths it keeps to the output pipe. This shipped file is
referenced by `app/filters/example.yaml` as
`{APP_SCRIPT_DIR}/example_filter.py`; write your own helpers in
`<home>/scripts/` and call them from your own `filters/*.yaml`.

Contract (same positional shape the old filter scripts used):

    python example_filter.py <data.yaml> <split> <input_pipe> <output_pipe>
                             [--every N] [--reverse true|false]

`<data.yaml>` and `<split>` are accepted for compatibility; this example does
not need them. The filter options come from the YAML `arguments`.
"""

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Keep every N-th image.")
    parser.add_argument("data_yaml")
    parser.add_argument("split")
    parser.add_argument("input_pipe")
    parser.add_argument("output_pipe")
    parser.add_argument("--every", type=int, default=2,
                        help="keep one image out of every N (default: 2)")
    parser.add_argument("--reverse", choices=("true", "false"), default="false",
                        help="reverse the surviving order (default: false)")
    args = parser.parse_args(argv)

    if args.every < 1:
        print("--every must be 1 or more", file=sys.stderr)
        return 2

    with open(args.input_pipe, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    if args.reverse == "true":
        paths = paths[::-1]
    kept = paths[:: args.every]

    with open(args.output_pipe, "w", encoding="utf-8") as f:
        for path in kept:
            f.write(path + "\n")

    print(f"example_filter: kept {len(kept)} of {len(paths)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
