import sys
import os

if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) == 2:
        image_path = argv[0]
        tag = argv[1]       
        # train/images/image.jpeg  -> train/tags/image.jpeg
        # images/train/image.jpeg -> tags/train/image.jpeg
        dirname = os.path.dirname(image_path.replace("images", "tags"))
        basename = os.path.basename(image_path)
        filename, ext = os.path.splitext(basename)
        os.makedirs(dirname, exist_ok=True)
        tag_path = os.path.join(dirname, f"{filename}.txt")
        lines = []
        if os.path.exists(tag_path) and os.path.isfile(tag_path):
            with open(tag_path, "r") as f:
                lines = [l.strip() for l in f.readlines()]
        lines.append(tag.strip())
        lines = [f"{l}\n" for l in lines]
        lines = set(lines)
        tmp_path = f"{tag_path}-tmp"
        with open(tmp_path, "w") as ff:
            ff.writelines(lines)
        os.replace(tmp_path, tag_path)
    else:
        sys.exit(f"Invalid exec ution, 2 arguments required, image_path & the tag, given ({len(argv)})")