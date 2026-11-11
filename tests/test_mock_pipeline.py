# SPDX-License-Identifier: GPL-3.0-or-later
"""端到端：mock 后端不需要 Blender、GPU 或网络。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_render.cli import EXIT_OK, main


class TestMockPipeline(unittest.TestCase):
    def test_mock_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            outdir = Path(tmp) / "out"
            code = main([
                "--script", "templates/build_3d.py",
                "--renderer", "mock",
                "--resolution", "320x240",
                "--outdir", str(outdir),
            ])
            self.assertEqual(code, EXIT_OK)

            png = outdir / "iter_01" / "render_0001.png"
            self.assertTrue(png.is_file(), "应产出统一命名的 render_0001.png")

            meta = json.loads((outdir / "iter_01" / "meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["transparent"])

            summary = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["renderer_used"], "mock")
            self.assertEqual(summary["review"]["provider"], "none")
            self.assertIsNone(summary["verdict"])
            self.assertTrue(summary["alpha"]["ok"])

    def test_no_render_skips_image(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            outdir = Path(tmp) / "out"
            code = main([
                "--script", "templates/build_3d.py",
                "--renderer", "mock",
                "--no-render",
                "--outdir", str(outdir),
            ])
            self.assertEqual(code, EXIT_OK)
            self.assertFalse((outdir / "iter_01" / "render_0001.png").exists())
            summary = json.loads((outdir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["renderer_used"], "none")

    def test_bad_resolution_exits_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            code = main([
                "--script", "x.py", "--renderer", "mock",
                "--resolution", "bad", "--outdir", tmp,
            ])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
