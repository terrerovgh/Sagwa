"""Convert the immutable generated rig to bounded LVGL assets and QA previews."""
import json
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
assets = root / 'assets/sagwa-rig'
layout = json.loads((assets / 'layout.json').read_text())
atlas = Image.open(assets / layout['source']).convert('RGBA')
source = '#include "lvgl.h"\n// New derived Sagwa art; provenance in assets/sagwa-rig.\n'
for name, spec in layout['parts'].items():
    part = atlas.crop(spec['crop'])
    # The generated atlas has near-zero-alpha pixels in the transparent gaps.
    # Find the content rectangle without rewriting the source alpha channel.
    box = part.getchannel('A').point(lambda a: 255 if a > 16 else 0).getbbox()
    if not box:
        raise ValueError('empty_rig_part')
    part = part.crop(box).resize(spec['size'], Image.Resampling.LANCZOS)
    part.save(assets / (name + '.png'))
    data = []
    for red, green, blue, alpha in part.get_flattened_data():
        data.extend((blue, green, red, alpha))
    source += f'static const uint8_t {name}_pixels[]={{' + ','.join(map(str,data)) + '};\n'
    w,h = part.size
    source += f'const lv_image_dsc_t sagwa_{name}={{.header={{.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_ARGB8888,.flags=0,.w={w},.h={h},.stride={w*4}}},.data_size=sizeof({name}_pixels),.data={name}_pixels}};\n'
(root / 'components/sagwa_edge/rig_assets.c').write_text(source)
print('Exported', len(layout['parts']), 'transparent rig layers')
