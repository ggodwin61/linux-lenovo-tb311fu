#!/usr/bin/env python3
"""Hardware-independent regression checks for the camera color decoder."""
from pathlib import Path
import runpy
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COLOR = runpy.run_path(str(ROOT / 'adaptation/rootfs/usr/local/libexec/tb311fu-camera/camera-color.py'))


class CameraColorTests(unittest.TestCase):
    def test_primary_channels_in_each_bayer_layout(self):
        # Independent mosaics: each pair describes the two sensor pixel rows.
        layouts = {'RGGB': ('RG', 'GB'), 'GRBG': ('GR', 'BG'),
                   'GBRG': ('GB', 'RG'), 'BGGR': ('BG', 'GR')}
        for pattern, sites in layouts.items():
            for channel, name in enumerate('RGB'):
                with self.subTest(pattern=pattern, channel=name):
                    mosaic = np.array([[224 if label == name else 16 for label in row]
                                       for row in sites], dtype=np.uint8)
                    raw = np.tile(mosaic, (2, 4)).reshape(4, 2, 4)
                    packed = np.zeros((4, 2, 5), dtype=np.uint8)
                    packed[:, :, :4] = raw
                    rgb = COLOR['decode_raw10'](packed.tobytes(), 8, 4, 10, pattern)
                    rendered = COLOR['render_preview'](rgb)
                    self.assertTrue(np.all(rendered[:, :, channel] > 240))
                    self.assertEqual(int(np.delete(rendered, channel, axis=2).max()), 0)

    def test_row_padding_is_not_treated_as_pixels(self):
        packed = np.zeros((4, 16), dtype=np.uint8)
        packed[:, :10] = 100
        packed[:, 10:] = 255
        rgb = COLOR['decode_raw10'](packed.tobytes(), 8, 4, 16, 'GRBG')
        np.testing.assert_array_equal(rgb, np.full((2, 4, 3), 100))

    def test_dominant_red_stays_red(self):
        rgb = np.full((16, 16, 3), [224, 40, 20], dtype=np.float32)
        rendered = COLOR['render_preview'](rgb)
        self.assertTrue(np.all(rendered[:, :, 0] > rendered[:, :, 1]))
        self.assertTrue(np.all(rendered[:, :, 1] > rendered[:, :, 2]))

    def test_invalid_geometry_and_truncated_frames_are_rejected(self):
        for width, height, stride, size in [(6, 4, 10, 40), (8, 3, 10, 30),
                                             (8, 4, 9, 36), (8, 4, 10, 39)]:
            with self.subTest(width=width, height=height, stride=stride, size=size):
                with self.assertRaises(ValueError):
                    COLOR['decode_raw10'](bytes(size), width, height, stride, 'GRBG')


if __name__ == '__main__':
    unittest.main(verbosity=2)
