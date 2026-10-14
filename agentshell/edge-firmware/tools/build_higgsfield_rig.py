#!/usr/bin/env python3
"""Derive a native rig by partitioning the existing Higgsfield idle illustration.

The neutral composite preserves every source pixel outside eyes/mouth. Masks
divide the illustration; they never add opaque rectangular infill to the body.
Small iris, pupil, eyelid and open-mouth retouches are explicitly derived art.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
ORDER = ('tail', 'body', 'ear_left', 'ear_right', 'head', 'eye_left',
         'eye_right', 'pupil_left', 'pupil_right', 'lid_left', 'lid_right',
         'mouth_closed', 'mouth_open')
POLYGONS = {
    'tail': [(11, 5), (41, 5), (41, 27), (29, 30), (26, 40), (35, 51),
             (44, 56), (40, 62), (22, 57), (11, 42)],
    'ear_left': [(69, 18), (76, 18), (87, 28), (92, 34), (86, 41), (77, 36)],
    'ear_right': [(102, 25), (112, 12), (119, 12), (123, 23), (118, 37), (108, 40)],
}
EYES = {'eye_left': (83, 40, 94, 48), 'eye_right': (100, 38, 111, 47)}
MOUTH = (94, 54, 104, 61)
UNDERLAPS = {'body': [(75, 61, 124, 70), (24, 49, 44, 64)],
             'head': [(77, 33, 91, 42), (105, 32, 120, 41)]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source, output):
    source = source.resolve()
    output = output.resolve()
    if output == source.parent or source.parent in output.parents or output in source.parents:
        raise ValueError('Output must be separate from the source folder')
    before = digest(source)
    with Image.open(source) as image:
        original_idle = image.convert('RGBA')
    idle = original_idle.copy()
    if idle.size != (136, 136):
        raise ValueError('Expected immutable 136x136 source')
    # The source contains near-opaque alpha throughout the fur. Normalize only
    # that interior onto the mandated black LCD: the visible RGB is unchanged,
    # and identical opaque hinge pixels can overlap without becoming brighter.
    # Truly translucent silhouette edges retain their original alpha.
    opaque_interior = 0
    for y in range(136):
        for x in range(136):
            red, green, blue, alpha = idle.getpixel((x, y))
            if alpha >= 240:
                idle.putpixel((x, y), tuple((c * alpha + 127) // 255
                                           for c in (red, green, blue)) + (255,))
                opaque_interior += 1
    masks = {}
    occupied = Image.new('L', idle.size, 0)
    for name in ('tail', 'ear_left', 'ear_right'):
        mask = Image.new('L', idle.size, 0)
        ImageDraw.Draw(mask).polygon(POLYGONS[name], fill=255)
        mask = ImageChops.subtract(mask, occupied)
        masks[name] = mask
        occupied = ImageChops.lighter(occupied, mask)
    head = Image.new('L', idle.size, 0)
    ImageDraw.Draw(head).rectangle((75, 28, 125, 68), fill=255)
    masks['head'] = ImageChops.subtract(head, occupied)
    occupied = ImageChops.lighter(occupied, masks['head'])
    masks['body'] = ImageChops.invert(occupied)
    # Shared hinge pixels are copied only where the original is fully opaque.
    # At rest the upper layer replaces identical RGB, preserving reconstruction;
    # while a lower layer moves it cannot expose a black seam at the hinge.
    for name, boxes in UNDERLAPS.items():
        for left, top, right, bottom in boxes:
            for y in range(top, bottom):
                for x in range(left, right):
                    if idle.getpixel((x, y))[3] == 255:
                        masks[name].putpixel((x, y), 255)

    layers = {}
    for name, mask in masks.items():
        layer = idle.copy()
        layer.putalpha(ImageChops.multiply(idle.getchannel('A'), mask))
        box = layer.getchannel('A').getbbox()
        if not box:
            raise ValueError(f'Empty part: {name}')
        layers[name] = (layer.crop(box), box[:2])

    # Preserve the source face, removing only the tiny pupil interiors. Original
    # sockets and muzzle remain under the moving layers; no skull/neck infill.
    for name, box in EYES.items():
        eye = idle.crop(box)
        blue = [p for p in eye.getdata() if p[3] > 128 and p[2] > p[0] + 10 and p[1] >= p[0]]
        iris = tuple(round(sum(p[i] for p in blue) / len(blue)) for i in range(3)) if blue else (156, 178, 192)
        w, h = eye.size
        ImageDraw.Draw(eye).ellipse((4, 2, 6, h - 2), fill=iris + (255,))
        layers[name] = (eye, box[:2])
        side = name.removeprefix('eye_')
        pupil = Image.new('RGBA', (3, 5))
        ImageDraw.Draw(pupil).ellipse((0, 0, 2, 4), fill=(28, 30, 35, 255))
        pupil.putpixel((1, 1), (190, 208, 220, 230))
        layers['pupil_' + side] = (pupil, (box[0] + 4, box[1] + 2))
        lid = Image.new('RGBA', eye.size)
        for x in range(w):
            top = idle.getpixel((box[0] + x, box[1] - 3))
            bottom = idle.getpixel((box[0] + x, box[3] + 2))
            for y in range(h):
                ratio = y / max(1, h - 1)
                color = tuple(round(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
                lid.putpixel((x, y), color + (eye.getpixel((x, y))[3],))
        ImageDraw.Draw(lid).arc((1, 1, w - 2, h - 2), 5, 175, fill=(58, 51, 49, 255), width=1)
        layers['lid_' + side] = (lid, box[:2])

    layers['mouth_closed'] = (idle.crop(MOUTH), MOUTH[:2])
    opened = Image.new('RGBA', (MOUTH[2] - MOUTH[0], MOUTH[3] - MOUTH[1]))
    draw = ImageDraw.Draw(opened)
    draw.ellipse((2, 1, 7, 5), fill=(55, 27, 28, 255))
    draw.ellipse((3, 4, 6, 5), fill=(182, 100, 112, 255))
    layers['mouth_open'] = (opened, MOUTH[:2])

    # Remove embedded facial features from the head so pupil movement, shrinking
    # eyes and mouth cancellation cannot reveal a second static eye or mouth.
    # This retouch stays inside the declared feature boxes, never the silhouette.
    head_image, (head_x, head_y) = layers['head']
    for eye_name, box in EYES.items():
        lid, _ = layers[eye_name.replace('eye_', 'lid_')]
        for y in range(lid.height):
            for x in range(lid.width):
                point = (box[0] + x - head_x, box[1] + y - head_y)
                original = head_image.getpixel(point)
                head_image.putpixel(point, lid.getpixel((x, y))[:3] + (original[3],))
    for y in range(MOUTH[1], MOUTH[3]):
        left = idle.getpixel((MOUTH[0] - 1, y))
        right = idle.getpixel((MOUTH[2] + 1, y))
        for x in range(MOUTH[0], MOUTH[2]):
            ratio = (x - MOUTH[0]) / max(1, MOUTH[2] - MOUTH[0] - 1)
            color = tuple(round(left[i] * (1 - ratio) + right[i] * ratio) for i in range(3))
            point = (x - head_x, y - head_y)
            head_image.putpixel(point, color + (head_image.getpixel(point)[3],))

    pivots = {'tail': (39, 56), 'body': (68, 128), 'ear_left': (81, 37), 'ear_right': (109, 35)}
    layout = {'id': 'higgsfield', 'parts': {}}
    for name in ORDER:
        image, (x, y) = layers[name]
        pivot = pivots.get(name, (x, y))
        if name in EYES:
            pivot = (x + image.width / 2, y + image.height / 2)
        layout['parts'][name] = {'file': name + '.png', 'x': x, 'y': y,
                                 'pivot_x': pivot[0] - x, 'pivot_y': pivot[1] - y}

    canvas = Image.new('RGBA', idle.size, (0, 0, 0, 255))
    for name in ORDER:
        if name.startswith('lid_') or name == 'mouth_open':
            continue
        image, position = layers[name]
        canvas.alpha_composite(image, position)
    baseline = Image.new('RGBA', idle.size, (0, 0, 0, 255))
    baseline.alpha_composite(original_idle)
    feature_boxes = list(EYES.values()) + [MOUTH]
    changed = outside = 0
    for y in range(136):
        for x in range(136):
            if canvas.getpixel((x, y)) != baseline.getpixel((x, y)):
                changed += 1
                if not any(l <= x < r and t <= y < b for l, t, r, b in feature_boxes):
                    outside += 1
    if outside:
        raise ValueError(f'Neutral reconstruction changed {outside} pixels outside facial features')
    if digest(source) != before:
        raise ValueError('Source modified')
    output.mkdir(parents=True, exist_ok=True)
    for name, (image, _) in layers.items():
        image.save(output / (name + '.png'))
    canvas.save(output / 'assembled-black-preview.png')
    (output / 'layout.json').write_text(json.dumps(layout, indent=2) + '\n')
    provenance = {
        'derived': True, 'source': 'agentshell/assets/sagwa/higgsfield-v1/idle.png',
        'source_sha256': before, 'source_modified': False,
        'method': 'Source partitions with opaque original hinge underlap; anatomy retained outside eyes and mouth',
        'retouches': ['Pupil interiors sampled from blue iris; independent 3x5 pupils',
                      'Eyelid fur interpolated from adjacent source rows; thin closed-eye line',
                      'Head eye/mouth underlays cleaned only inside declared feature boxes',
                      'Independent small open mouth and tongue, procedurally drawn derivative'],
        'opaque_interior_normalization': {'pixels': opaque_interior,
                                          'source_alpha_min': 240,
                                          'background': '#000000',
                                          'visible_rgb_unchanged': True},
        'neutral_changed_pixels': changed, 'neutral_changed_pixels_outside_features': outside,
        'masks': POLYGONS, 'opaque_hinge_underlaps': UNDERLAPS, 'feature_boxes': feature_boxes,
        'layers': {name: {'sha256': digest(output / (name + '.png')), 'size': list(image.size),
                          'bytes_bgra': image.width * image.height * 4}
                   for name, (image, _) in layers.items()},
        'hardware_verified': False, 'visual_approval_pending': True,
    }
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'PASS: 13 layers, {changed} retouched pixels, {outside} changes outside features; source intact')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'agentshell/assets/sagwa/higgsfield-v1/idle.png')
    parser.add_argument('--output', type=Path, default=ROOT / 'agentshell/edge-firmware/assets/higgsfield-rig')
    args = parser.parse_args()
    build(args.source, args.output)
