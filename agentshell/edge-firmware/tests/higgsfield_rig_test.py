"""Verify deterministic derivation and preservation of the original illustration."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

EDGE = Path(__file__).resolve().parents[1]
SOURCE = EDGE.parents[0] / 'assets/sagwa/higgsfield-v1/idle.png'
spec = importlib.util.spec_from_file_location('derive_rig', EDGE / 'tools/build_higgsfield_rig.py')
derive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(derive)


class DerivationTests(unittest.TestCase):
    def test_source_preserved_and_reproducible(self):
        original = SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'rig'
            derive.build(SOURCE, output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            derive.build(SOURCE, output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            self.assertEqual(SOURCE.read_bytes(), original)
            layout = json.loads(first['layout.json'])
            self.assertEqual(set(layout['parts']), set(derive.ORDER))
            provenance = json.loads(first['provenance.json'])
            self.assertEqual(provenance['neutral_changed_pixels_outside_features'], 0)
            self.assertLess(provenance['neutral_changed_pixels'], 300)
            for part in layout['parts'].values():
                with Image.open(output / part['file']) as image:
                    self.assertEqual(image.mode, 'RGBA')
                    self.assertTrue(0 < image.width <= 136 and 0 < image.height <= 136)
            # Neutral image retains the source silhouette, including all paws.
            self.assertIn('assembled-black-preview.png', first)

    def test_input_overlap_rejected(self):
        original = SOURCE.read_bytes()
        for path in (SOURCE.parent, SOURCE.parent / 'nested', SOURCE.parent.parent):
            with self.assertRaises(ValueError):
                derive.build(SOURCE, path)
        self.assertEqual(SOURCE.read_bytes(), original)

    def test_wrong_size_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.png'
            output = Path(temporary) / 'rig'
            Image.new('RGBA', (135, 136)).save(source)
            with self.assertRaises(ValueError):
                derive.build(source, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
