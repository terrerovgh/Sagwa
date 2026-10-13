"""Convert exported original videos to a bounded, offline CoreS3 sprite pack.

Original files remain untouched. Requires Pillow and ffmpeg (or imageio-ffmpeg).
Private input/output paths are never committed with the firmware sources.
"""
import argparse, hashlib, json, shutil, struct, subprocess
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path, help='Directory containing the exported manifest.json')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--ffmpeg')
args = parser.parse_args()
source = args.source.resolve()
manifest = json.loads((source/'manifest.json').read_text())
ffmpeg = args.ffmpeg or shutil.which('ffmpeg')
if not ffmpeg:
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
size, fps = 96, 8
blob, animations = bytearray(), []
for state in ('idle', 'working', 'making_something', 'milestone'):
    entry = manifest['states'].get(state)
    if not entry:
        raise ValueError('Missing original state: '+state)
    video = (source/entry['file']).resolve()
    if not video.is_relative_to(source) or video.suffix != '.mp4':
        raise ValueError('Invalid original video path')
    raw = subprocess.run([ffmpeg, '-v', 'error', '-i', str(video), '-t', '8',
                          '-vf', 'fps=8,scale=96:96', '-frames:v', '64',
                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         check=True, capture_output=True, timeout=30).stdout
    frame_size = size*size*3
    if len(raw) != 64*frame_size:
        raise ValueError('Expected an eight-second original video: '+state)
    atlas = Image.frombytes('RGB', (size, size*64), raw)
    indexed = atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                             dither=Image.Dither.NONE)
    palette_offset = len(blob)
    palette = indexed.getpalette()
    for n in range(256):
        r, g, b = palette[n*3:n*3+3]
        blob += struct.pack('<H', ((r>>3)<<11)|((g>>2)<<5)|(b>>3))
    offset = len(blob)
    blob += indexed.tobytes()
    animations.append(dict(name=state, width=size, height=size, frames=64,
                           duration_ms=8000, palette_offset=palette_offset,
                           data_offset=offset, source_file=video.name,
                           source_sha256=hashlib.sha256(video.read_bytes()).hexdigest()))
if len(blob)>2500000:
    raise ValueError('Avatar exceeds embedded sprite budget')
args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
(args.output/'sagwa.bin').write_bytes(blob)
header = '#pragma once\nnamespace shell {\ninline constexpr Animation sagwa_animations[] = {\n'
for a in animations:
    header += '  {"%s",96,96,64,8000,%d,%d},\n'%(a['name'],a['palette_offset'],a['data_offset'])
header += '};\n}\n'
(args.output/'sagwa_assets.hpp').write_text(header)
(args.output/'manifest.json').write_text(json.dumps(dict(
    name=manifest['avatar'], fps=fps, packed_sha256=hashlib.sha256(blob).hexdigest(),
    animations=animations, unavailable=manifest.get('unavailable', {}),
    adaptations='96x96, 8 fps, shared 256-colour palette per clip, RGB565; originals preserved'), indent=2)+'\n')
print(json.dumps(dict(bytes=len(blob), animations=len(animations), output=str(args.output))))
