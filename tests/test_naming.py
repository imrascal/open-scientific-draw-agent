# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_render.naming import (expand_frames, find_render_output, mm_to_px,
                                parse_resolution)


class TestNaming(unittest.TestCase):
    def test_parse_resolution(self):
        self.assertEqual(parse_resolution("1920x1080"), (1920, 1080))
        self.assertEqual(parse_resolution("2008X1417"), (2008, 1417))

    def test_parse_resolution_invalid(self):
        for bad in ("1920", "0x100", "axb"):
            with self.assertRaises(ValueError):
                parse_resolution(bad)

    def test_expand_frames(self):
        self.assertEqual(expand_frames("1"), "1")
        self.assertEqual(expand_frames("1-3"), "1,2,3")
        self.assertEqual(expand_frames("1,5-7"), "1,5,6,7")

    def test_expand_frames_invalid(self):
        with self.assertRaises(ValueError):
            expand_frames("5-1")

    def test_find_render_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_render_output(tmp))
            (Path(tmp) / "render_0001.png").write_bytes(b"x")
            (Path(tmp) / "preview_0001.png").write_bytes(b"x")
            found = find_render_output(tmp)
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "render_0001.png")

    def test_mm_to_px(self):
        self.assertEqual(mm_to_px(85, 600), 2008)
        self.assertEqual(mm_to_px(180, 300), 2126)


if __name__ == "__main__":
    unittest.main()
