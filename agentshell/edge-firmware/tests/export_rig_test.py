"""Exporter tests: legacy byte reproducibility, rig compile/render, validation.

Run with a Python that has Pillow:  python3 tests/export_rig_test.py
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import export_rig  # noqa: E402

ASSETS = ROOT / 'assets/sagwa-rig'
INCLUDE = ROOT / 'components/sagwa_edge/include'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(folder):
    return {p.name: digest(p) for p in sorted(folder.iterdir()) if p.is_file()}


class ExportRigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def rig_fixture(self, parts=export_rig.RIG_PARTS, size=(4, 3), **override):
        folder = self.tmp / 'rig'
        folder.mkdir(exist_ok=True)
        layout = {'id': 'fixture', 'parts': {}}
        for index, name in enumerate(parts):
            image = Image.new('RGBA', size, (0, 0, 0, 0))
            image.putpixel((0, 0), (index * 10, 200, 30, 255))  # straight alpha
            image.save(folder / f'{name}.png')
            layout['parts'][name] = {'file': f'{name}.png', 'x': 10 + index,
                                     'y': 20, 'pivot_x': 1.5, 'pivot_y': 0}
        for name, spec in override.items():
            layout['parts'][name].update(spec)
        (folder / 'layout.json').write_text(json.dumps(layout))
        return folder / 'layout.json'

    def test_legacy_default_reproduces_current_source_without_touching_assets(self):
        before = snapshot(ASSETS)
        committed = digest(ROOT / 'components/sagwa_edge/rig_assets.c')
        output, header = self.tmp / 'rig_assets.c', self.tmp / 'rig_assets.h'
        export_rig.run(['--output', str(output), '--header', str(header),
                        '--preview', str(self.tmp / 'sheet.png')])
        self.assertEqual(digest(output), committed)
        self.assertIn('extern const lv_image_dsc_t sagwa_mouth_open;', header.read_text())
        self.assertEqual(snapshot(ASSETS), before)  # input folder is read only
        parts = self.tmp / 'parts'
        export_rig.run(['--output', str(output), '--parts-output', str(parts)])
        self.assertEqual(len(list(parts.glob('*.png'))), 12)
        # The explicit parts output matches the reviewed PNGs in the asset folder.
        for png in parts.glob('*.png'):
            with Image.open(png) as fresh, Image.open(ASSETS / png.name) as kept:
                self.assertEqual(fresh.tobytes(), kept.tobytes(), png.name)

    def test_rig_mode_compiles_and_renders_with_rig_renderer(self):
        layout = self.rig_fixture()
        source, header = self.tmp / 'rig.cpp', self.tmp / 'rig.hpp'
        preview = self.tmp / 'preview.png'
        export_rig.run(['--input', str(layout), '--output', str(source),
                        '--header', str(header), '--prefix', 'higgsfield',
                        '--preview', str(preview)])
        text = source.read_text()
        self.assertIn('const sagwa::RigDefinition higgsfield_rig{"fixture"', text)
        with Image.open(preview) as image:
            self.assertEqual(image.size, (136, 136))
        main = self.tmp / 'main.cpp'
        main.write_text('''#include "rig.hpp"
#include <cassert>
#include <cstring>
int main() {
  using namespace sagwa;
  const auto &rig = higgsfield_rig;
  assert(valid_rig(rig) && std::strcmp(rig.id, "fixture") == 0);
  for (size_t i = 0; i < rig.layers.size(); ++i) {
    const auto &l = rig.layers[i];
    assert(l.texture.width == 4 && l.texture.height == 3);
    assert(l.texture.stride == 16 && l.texture.bytes == 48);
    assert(l.x == 10.f + i && l.y == 20.f && l.pivot_x == 1.5f);
    // BGRA order: blue, green, red, alpha of the opaque first pixel.
    assert(l.texture.data[0] == 30 && l.texture.data[1] == 200 &&
           l.texture.data[2] == i * 10 && l.texture.data[3] == 255);
    assert(l.texture.data[7] == 0); // transparent pixel stays transparent
  }
  std::array<uint16_t, 136 * 136> pixels{};
  Pose pose;
  render_rig(rig, pose, pixels.data());
  int lit = 0;
  for (auto p : pixels) lit += p != 0;
  assert(lit > 0);
}
''')
        binary = self.tmp / 'rig-test'
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', f'-I{INCLUDE}', f'-I{self.tmp}',
                        str(main), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

    def assert_rejected(self, args, message):
        before = sorted(p.name for p in self.tmp.rglob('*'))
        with self.assertRaisesRegex(export_rig.ExportError, message):
            export_rig.run(args)
        self.assertEqual(sorted(p.name for p in self.tmp.rglob('*')), before)

    def test_parts_output_cannot_overwrite_input_folder(self):
        before = snapshot(ASSETS)
        out = str(self.tmp / 'out.c')
        for target in (ASSETS, ASSETS / 'nested', ASSETS.parent):
            with self.assertRaisesRegex(export_rig.ExportError, 'overlaps the input'):
                export_rig.run(['--output', out, '--parts-output', str(target)])
        self.assertEqual(snapshot(ASSETS), before)  # originals intact
        self.assertFalse((ASSETS / 'nested').exists())
        self.assertFalse((self.tmp / 'out.c').exists())  # no output on rejection
        layout = self.rig_fixture()
        rig_before = snapshot(layout.parent)
        with self.assertRaisesRegex(export_rig.ExportError, 'overlaps the input'):
            export_rig.run(['--input', str(layout), '--output', out,
                            '--parts-output', str(layout.parent)])
        self.assertEqual(snapshot(layout.parent), rig_before)
        self.assertFalse((self.tmp / 'out.c').exists())

    def test_validation_happens_before_any_write(self):
        out = str(self.tmp / 'out.cpp')
        good = str(self.rig_fixture())
        self.assert_rejected(['--input', good, '--output', out, '--prefix', '9bad'],
                             'not a C identifier')
        self.assert_rejected(['--input', good, '--output', out, '--prefix', 'a-b'],
                             'not a C identifier')
        self.assert_rejected(['--input', good, '--output', out, '--header', out],
                             'different files')
        self.assert_rejected(['--input', good, '--output', str(self.tmp / 'rig/x.cpp')],
                             'inside the input layout folder')
        self.assert_rejected(['--output', out, '--preview', str(ASSETS / 'p.png')],
                             'inside the input layout folder')
        missing = str(self.rig_fixture(parts=export_rig.RIG_PARTS[:-1]))
        self.assert_rejected(['--input', missing, '--output', out], 'mouth_open')
        shutil.rmtree(self.tmp / 'rig')
        big = str(self.rig_fixture(size=(137, 2)))
        self.assert_rejected(['--input', big, '--output', out], 'outside 1..136')
        shutil.rmtree(self.tmp / 'rig')
        escape = str(self.rig_fixture(head={'file': '../head.png'}))
        self.assert_rejected(['--input', escape, '--output', out], 'unsafe asset path')
        shutil.rmtree(self.tmp / 'rig')
        far = str(self.rig_fixture(tail={'x': 200}))
        self.assert_rejected(['--input', far, '--output', out], 'tail: x')
        shutil.rmtree(self.tmp / 'rig')
        nan = str(self.rig_fixture(body={'pivot_y': float('nan')}))
        self.assert_rejected(['--input', nan, '--output', out], 'body: pivot_y')


if __name__ == '__main__':
    unittest.main(verbosity=1)
