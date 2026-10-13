"""Prepare transparent pose assets without assuming perfectly aligned atlas rows.

Connected alpha regions distinguish each cat from a neighbouring pose's feet
or tail. This converts a generated atlas; it does not redraw the character.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image


def regions(mask):
    parent = []
    runs = []
    previous = []

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y, row in enumerate(mask):
        current = []
        for match in re.finditer(b"\x01+", row.astype(np.uint8).tobytes()):
            left, right = match.span()
            i = len(parent)
            parent.append(i)
            for a, b, old in previous:
                if a <= right and b >= left:  # Eight-connected, exclusive end.
                    parent[root(i)] = root(old)
            current.append((left, right, i))
            runs.append((left, right, y, i))
        previous = current
    found = {}
    for left, right, y, i in runs:
        i = root(i)
        area, box, spans = found.setdefault(i, [0, [left, y, right, y + 1], []])
        found[i][0] = area + right - left
        box[:] = [min(box[0], left), min(box[1], y), max(box[2], right), max(box[3], y + 1)]
        spans.append((left, right, y))
    return sorted(found.values(), key=lambda r: r[0], reverse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    folder = args.directory
    atlas = Image.open(folder / "atlas-original.png").convert("RGBA")
    alpha = np.asarray(atlas.getchannel("A"))
    manifest = json.loads((folder / "manifest.json").read_text())
    assert hashlib.sha256((folder / "atlas-original.png").read_bytes()).hexdigest() == manifest["original_atlas_sha256"]
    crops = {}
    for column in range(4):
        left, right = round(column * atlas.width / 4), round((column + 1) * atlas.width / 4)
        cats = regions(alpha[:, left:right] > 8)[:3]
        if len(cats) != 3 or min(cat[0] for cat in cats) < 2000:
            raise ValueError("Atlas needs manual segmentation; no pose written")
        for row, (area, box, spans) in enumerate(sorted(cats, key=lambda c: c[1][1])):
            x0, y0, x1, y1 = box
            if x0 == 0 or x1 == right - left or y0 == 0 or y1 == atlas.height:
                raise ValueError("Character touches atlas/column boundary")
            # Crop around the whole character, including detached whiskers or
            # fur highlights within its bounds. Do not mask to the component:
            # generated alpha can split visible regions inside the character.
            box = [max(left, left + x0 - 2), max(0, y0 - 2), min(right, left + x1 + 2), min(atlas.height, y1 + 2)]
            sprite = atlas.crop(box)
            crops[row * 4 + column] = (box, area, sprite)
    # Validate all regions before replacing any derived pose.
    for index, item in enumerate(manifest["poses"]):
        box, area, sprite = crops[index]
        sprite.thumbnail((124, 124), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (136, 136), (0, 0, 0, 0))
        frame.alpha_composite(sprite, ((136 - sprite.width) // 2, 136 - sprite.height - 6))
        target = folder / item["file"]
        frame.save(target)
        item.update(source_bbox=box, alpha_component_pixels=area, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        item.pop("source_cell", None)
    manifest["segmentation"] = "Largest three alpha>8 regions per column locate whole-character crop bounds; original alpha retained within bounds plus 2px margin"
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    preview = Image.new("RGB", (640, 516), (0, 0, 0))
    for index, item in enumerate(manifest["poses"]):
        frame = Image.open(folder / item["file"])
        preview.paste(frame, ((index % 4) * 160 + 12, (index // 4) * 172 + 12), frame)
    preview.save(folder / "preview-black.png")
    print(json.dumps({"poses": len(manifest["poses"]), "transparent": True, "deployed": False}))


if __name__ == "__main__":
    main()
