"""Export Sagwa rig art to bounded native sources and optional QA images.

Two layout formats are accepted; the input layout and its images are only read.

Legacy (``source`` atlas + per-part ``crop``/``size``): reproduces the current
``rig_assets.c`` byte for byte with the default prefix ``sagwa``.

Rig (``parts`` with ``file``, ``x``, ``y``, ``pivot_x``, ``pivot_y`` for all 13
``RigPart`` layers): emits a C++ ``const sagwa::RigDefinition <prefix>_rig``
compatible with ``rig_renderer.hpp``. Pixels are straight-alpha BGRA, stride
``width * 4`` and ``bytes == stride * height``; every side is 1..136.

Everything is validated and rendered in memory before any file is written.
Part PNGs are written only to an explicit ``--parts-output`` directory.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'assets/sagwa-rig/layout.json'
DEFAULT_OUTPUT = ROOT / 'components/sagwa_edge/rig_assets.c'
# Order matches sagwa::RigPart, which is also the compositing order.
RIG_PARTS = ('tail', 'body', 'ear_left', 'ear_right', 'head', 'eye_left',
             'eye_right', 'pupil_left', 'pupil_right', 'lid_left', 'lid_right',
             'mouth_closed', 'mouth_open')
MAX_SIDE = 136
MAX_OFFSET = 136
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,47}')
PART_NAME = re.compile(r'[a-z][a-z0-9_]{0,31}')


class ExportError(ValueError):
    pass


def bgra(image):
    data = []
    # Pillow >= 12.1 renames getdata(); both yield the same RGBA tuples.
    pixels = getattr(image, 'get_flattened_data', None) or image.getdata
    for red, green, blue, alpha in pixels():
        data.extend((blue, green, red, alpha))
    return data


def check_size(name, image):
    w, h = image.size
    if not (1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE):
        raise ExportError(f'{name}: size {w}x{h} outside 1..{MAX_SIDE}')


def legacy_parts(layout, base):
    source = layout.get('source')
    if not isinstance(source, str):
        raise ExportError('legacy layout needs a source atlas')
    atlas = Image.open(resolve(base, source)).convert('RGBA')
    parts = []
    for name, spec in layout['parts'].items():
        if not isinstance(name, str) or not PART_NAME.fullmatch(name):
            raise ExportError(f'invalid part name {name!r}')
        part = atlas.crop(spec['crop'])
        # The generated atlas has near-zero-alpha pixels in the transparent gaps.
        # Find the content rectangle without rewriting the source alpha channel.
        box = part.getchannel('A').point(lambda a: 255 if a > 16 else 0).getbbox()
        if not box:
            raise ExportError(f'{name}: empty_rig_part')
        part = part.crop(box).resize(spec['size'], Image.Resampling.LANCZOS)
        check_size(name, part)
        parts.append((name, part, None))
    return parts


def rig_parts(layout, base):
    parts = layout['parts']
    if set(parts) != set(RIG_PARTS):
        missing = sorted(set(RIG_PARTS) - set(parts))
        extra = sorted(set(parts) - set(RIG_PARTS))
        raise ExportError(f'rig parts mismatch: missing={missing} extra={extra}')
    result = []
    for name in RIG_PARTS:
        spec = parts[name]
        if not isinstance(spec, dict) or not isinstance(spec.get('file'), str):
            raise ExportError(f'{name}: file is required')
        place = []
        for key in ('x', 'y', 'pivot_x', 'pivot_y'):
            value = spec.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or abs(value) > MAX_OFFSET):
                raise ExportError(f'{name}: {key} must be finite, |v| <= {MAX_OFFSET}')
            place.append(float(value))
        with Image.open(resolve(base, spec['file'])) as image:
            part = image.convert('RGBA')
        check_size(name, part)
        result.append((name, part, place))
    return result


def resolve(base, relative):
    """Resolve a layout-relative file that must stay inside the layout folder."""
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ExportError(f'unsafe asset path {relative!r}')
    full = (base / path).resolve()
    if base not in full.parents or not full.is_file():
        raise ExportError(f'missing asset {relative!r}')
    return full


def legacy_source(parts, prefix):
    source = '#include "lvgl.h"\n// New derived Sagwa art; provenance in assets/sagwa-rig.\n'
    for name, part, _ in parts:
        data = bgra(part)
        source += f'static const uint8_t {name}_pixels[]={{' + ','.join(map(str, data)) + '};\n'
        w, h = part.size
        source += (f'const lv_image_dsc_t {prefix}_{name}={{.header={{.magic=LV_IMAGE_HEADER_MAGIC,'
                   f'.cf=LV_COLOR_FORMAT_ARGB8888,.flags=0,.w={w},.h={h},.stride={w*4}}},'
                   f'.data_size=sizeof({name}_pixels),.data={name}_pixels}};\n')
    return source


def legacy_header(parts, prefix):
    lines = ['#pragma once', '#include "lvgl.h"', '#ifdef __cplusplus', 'extern "C" {', '#endif']
    lines += [f'extern const lv_image_dsc_t {prefix}_{name};' for name, _, _ in parts]
    lines += ['#ifdef __cplusplus', '}', '#endif', '']
    return '\n'.join(lines)


def number(value):
    return repr(float(value)) + 'f'


def rig_source(parts, prefix, rig_id):
    out = ['#include "rig_renderer.hpp"',
           '// Generated by tools/export_rig.py; straight-alpha BGRA, stride = width * 4.',
           'namespace {']
    for name, part, _ in parts:
        data = bgra(part)
        out.append(f'const uint8_t {prefix}_{name}_pixels[]={{' + ','.join(map(str, data)) + '};')
    out.append('} // namespace')
    out.append(f'extern const sagwa::RigDefinition {prefix}_rig;')
    out.append(f'const sagwa::RigDefinition {prefix}_rig{{"{rig_id}", {{{{')
    layers = []
    for name, part, (x, y, pivot_x, pivot_y) in parts:
        w, h = part.size
        layers.append(f'  {{{{{prefix}_{name}_pixels, sizeof({prefix}_{name}_pixels), {w}, {h}, {w * 4}}}, '
                      f'{number(x)}, {number(y)}, {number(pivot_x)}, {number(pivot_y)}}}, // {name}')
    out.append(',\n'.join(layers))
    out.append('}}};')
    return '\n'.join(out) + '\n'


def rig_header(prefix):
    return ('#pragma once\n#include "rig_renderer.hpp"\n'
            f'extern const sagwa::RigDefinition {prefix}_rig;\n')


def preview(parts, rig):
    if rig:
        canvas = Image.new('RGBA', (MAX_SIDE, MAX_SIDE), (0, 0, 0, 255))
        for _, part, (x, y, _, _) in parts:
            canvas.alpha_composite(part, (int(round(x)), int(round(y))))
        return canvas
    width = sum(part.size[0] for _, part, _ in parts) + 4 * (len(parts) + 1)
    canvas = Image.new('RGBA', (width, MAX_SIDE + 8), (0, 0, 0, 255))
    x = 4
    for _, part, _ in parts:
        canvas.alpha_composite(part, (x, 4))
        x += part.size[0] + 4
    return canvas


def parse(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT, help='layout.json (read only)')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help='generated C/C++ source')
    parser.add_argument('--prefix', default='sagwa', help='C identifier prefix for exported symbols')
    parser.add_argument('--header', type=Path, help='optional generated header')
    parser.add_argument('--preview', type=Path, help='optional QA preview PNG')
    parser.add_argument('--parts-output', type=Path, help='optional directory for per-part PNGs')
    return parser.parse_args(argv)


def run(argv=None):
    args = parse(argv)
    if not IDENTIFIER.fullmatch(args.prefix):
        raise ExportError(f'prefix {args.prefix!r} is not a C identifier (<= 48 chars)')
    layout_path = args.input.resolve()
    base = layout_path.parent
    try:
        layout = json.loads(layout_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ExportError(f'cannot read layout: {error}') from error
    if not isinstance(layout, dict) or not isinstance(layout.get('parts'), dict) or not layout['parts']:
        raise ExportError('layout needs a non-empty parts object')
    rig = any(isinstance(spec, dict) and 'file' in spec for spec in layout['parts'].values())

    outputs = [p.resolve() for p in (args.output, args.header, args.preview) if p]
    if len(set(outputs)) != len(outputs):
        raise ExportError('output, header and preview must be different files')
    parts_dir = args.parts_output.resolve() if args.parts_output else None
    for path in outputs:
        # Inputs are read only: generated files never land in the layout folder.
        if path == layout_path or base == path.parent or base in path.parents:
            raise ExportError(f'{path} would write inside the input layout folder')
        if parts_dir and (path.parent == parts_dir or parts_dir in path.parents):
            raise ExportError(f'{path} is inside --parts-output')

    if rig:
        rig_id = layout.get('id', args.prefix)
        if not isinstance(rig_id, str) or not IDENTIFIER.fullmatch(rig_id):
            raise ExportError('rig id must be a C identifier')
        parts = rig_parts(layout, base)
        source, header = rig_source(parts, args.prefix, rig_id), rig_header(args.prefix)
    else:
        parts = legacy_parts(layout, base)
        source, header = legacy_source(parts, args.prefix), legacy_header(parts, args.prefix)
    image = preview(parts, rig) if args.preview else None

    for path in outputs:
        if not path.parent.is_dir():
            raise ExportError(f'output folder missing: {path.parent}')
    args.output.write_text(source)
    if args.header:
        args.header.write_text(header)
    if image:
        image.save(args.preview)
    if parts_dir:
        parts_dir.mkdir(parents=True, exist_ok=True)
        for name, part, _ in parts:
            part.save(parts_dir / (name + '.png'))
    kind = 'rig layers' if rig else 'transparent rig layers'
    print('Exported', len(parts), kind)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except ExportError as error:
        print(f'export_rig: {error}', file=sys.stderr)
        sys.exit(2)
