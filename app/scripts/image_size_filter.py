#!/usr/bin/env python3
"""yolo-box-editor image-size filter helper.

Keeps the images whose pixel size matches the requested width and/or height.
Used by `app/filters/image_size.yaml`.

    python image_size_filter.py <data.yaml> <split> <input_pipe> <output_pipe>
                               [--width N] [--height N] [--invert true|false]

A blank `--width` / `--height` matches any value, so a filter with only a width
keeps every image that wide regardless of height. A value may be prefixed with a
comparison operator — `>=`, `>`, `=`, `<`, `<=` or `!=` — to match a range
instead of an exact size (e.g. `--width ">=640" --height "<480"`); a bare number
means `=`. The image dimensions are read from the file header with the standard
library only (no Pillow at runtime) for PNG, JPEG, GIF, BMP, WebP and TIFF files.
"""

import argparse
import struct
import sys


def _png(f):
    f.seek(16)
    return struct.unpack(">II", f.read(8))


def _gif(f):
    f.seek(6)
    return struct.unpack("<HH", f.read(4))


def _bmp(f):
    f.seek(18)
    width, height = struct.unpack("<ii", f.read(8))
    return width, abs(height)


def _jpeg(f):
    f.seek(2)
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            return None
        code = marker[0]
        # Standalone markers carry no length; SOS/EOI mean no SOF was seen.
        if code in (0x01,) or 0xD0 <= code <= 0xD7:
            continue
        if code in (0xD9, 0xDA):
            return None
        length = struct.unpack(">H", f.read(2))[0]
        # SOF0..SOF15 (except DHT/DAC/RST) holds the dimensions.
        if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
            data = f.read(5)
            height, width = struct.unpack(">HH", data[1:5])
            return width, height
        f.seek(length - 2, 1)


def _webp(f):
    f.seek(12)
    fourcc = f.read(4)
    f.read(4)  # chunk size (not needed)
    if fourcc == b"VP8 ":
        f.read(6)  # frame tag + start code
        data = f.read(4)
        if len(data) < 4:
            return None
        width = struct.unpack("<H", data[:2])[0] & 0x3FFF
        height = struct.unpack("<H", data[2:4])[0] & 0x3FFF
        return width, height
    if fourcc == b"VP8L":
        f.read(1)  # signature byte
        data = f.read(4)
        if len(data) < 4:
            return None
        bits = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if fourcc == b"VP8X":
        f.read(4)  # flags + reserved
        data = f.read(6)
        if len(data) < 6:
            return None
        width = data[0] | (data[1] << 8) | (data[2] << 16)
        height = data[3] | (data[4] << 8) | (data[5] << 16)
        return width + 1, height + 1
    return None


def _tiff(f):
    header = f.read(8)
    if header[:2] == b"II":
        endian = "<"
    elif header[:2] == b"MM":
        endian = ">"
    else:
        return None
    offset = struct.unpack(endian + "I", header[4:8])[0]
    f.seek(offset)
    count = struct.unpack(endian + "H", f.read(2))[0]
    width = height = None
    for _ in range(count):
        entry = f.read(12)
        if len(entry) < 12:
            break
        tag, field_type = struct.unpack(endian + "HH", entry[:4])
        value = struct.unpack(endian + "I", entry[8:12])[0]
        if field_type == 3:  # SHORT values sit in the first two value bytes
            value = struct.unpack(endian + "H", entry[8:10])[0]
        if tag == 256:
            width = value
        elif tag == 257:
            height = value
    return (width, height) if width and height else None


def image_size(path):
    """The (width, height) of an image file, or None when it cannot be read."""
    try:
        with open(path, "rb") as f:
            signature = f.read(16)
            if signature.startswith(b"\x89PNG\r\n\x1a\n"):
                return _png(f)
            if signature[:2] == b"\xff\xd8":
                return _jpeg(f)
            if signature[:6] in (b"GIF87a", b"GIF89a"):
                return _gif(f)
            if signature[:2] == b"BM":
                return _bmp(f)
            if signature[:4] == b"RIFF" and signature[8:12] == b"WEBP":
                return _webp(f)
            if signature[:4] in (b"II*\x00", b"MM\x00*"):
                f.seek(0)
                return _tiff(f)
    except (OSError, struct.error):
        return None
    return None


_OPERATORS = (">=", "<=", "!=", ">", "<", "=")


def _dimension(value):
    """Parse a `--width` / `--height` value; blank means "any" (None).

    Returns `(operator, number)`, where the operator defaults to `=` when the
    value is a bare number.
    """
    value = (value or "").strip()
    if not value:
        return None
    op = "="
    for candidate in _OPERATORS:
        if value.startswith(candidate):
            op = candidate
            value = value[len(candidate):].strip()
            break
    try:
        number = int(float(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}")
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return op, number


def _compare(actual, constraint):
    """Whether `actual` satisfies a constraint (None = any, int = `=`)."""
    if constraint is None:
        return True
    if not isinstance(constraint, tuple):
        constraint = ("=", constraint)
    op, number = constraint
    if op == ">=":
        return actual >= number
    if op == "<=":
        return actual <= number
    if op == ">":
        return actual > number
    if op == "<":
        return actual < number
    if op == "!=":
        return actual != number
    return actual == number


def _format(constraint):
    """Render a constraint for the summary line (`*` when unset)."""
    if constraint is None:
        return "*"
    if isinstance(constraint, tuple):
        op, number = constraint
        return f"{op}{number}"
    return str(constraint)


def matches(size, width, height):
    """Whether an image size matches the given width/height (None = any)."""
    if size is None:
        return False
    w, h = size
    return _compare(w, width) and _compare(h, height)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Filter images by pixel size.")
    parser.add_argument("data_yaml")
    parser.add_argument("split")
    parser.add_argument("input_pipe")
    parser.add_argument("output_pipe")
    parser.add_argument("--width", type=_dimension, default=None,
                        help="width in pixels, optionally prefixed with an "
                             "operator (>=, >, =, <, <=, !=); blank = any")
    parser.add_argument("--height", type=_dimension, default=None,
                        help="height in pixels, optionally prefixed with an "
                             "operator (>=, >, =, <, <=, !=); blank = any")
    parser.add_argument("--invert", choices=("true", "false"), default="false",
                        help="keep images that do NOT match (default: false)")
    args = parser.parse_args(argv)

    if args.width is None and args.height is None:
        print("image_size_filter: give --width and/or --height", file=sys.stderr)
        return 2

    with open(args.input_pipe, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    invert = args.invert == "true"
    kept = [
        path for path in paths
        if matches(image_size(path), args.width, args.height) != invert
    ]

    with open(args.output_pipe, "w", encoding="utf-8") as f:
        for path in kept:
            f.write(path + "\n")

    wanted = f"{_format(args.width)}x{_format(args.height)}"
    print(f"image_size_filter: kept {len(kept)} of {len(paths)} "
          f"({'not ' if invert else ''}{wanted})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
