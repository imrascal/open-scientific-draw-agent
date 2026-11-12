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


class TestMetaSync(unittest.TestCase):
    """渲染分辨率可能被 CLI/spec 覆盖，meta.resolution 必须跟随实际 PNG。"""

    def test_resolution_follows_actual_png(self):
        from PIL import Image

        from osda_render.meta import load_meta, sync_meta_resolution

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            png = base / "render_0001.png"
            Image.new("RGBA", (321, 123), (0, 0, 0, 0)).save(png)
            meta = base / "meta.json"
            meta.write_text(json.dumps({
                "asset_id": "x", "resolution": [1600, 1200],
                "transparent": True, "ortho_scale_mm": 46.0,
            }), encoding="utf-8")

            self.assertTrue(sync_meta_resolution(meta, png, (640, 480)))
            loaded = load_meta(meta)
            self.assertEqual(loaded.resolution, (321, 123))
            # 其它字段不能被覆盖
            self.assertTrue(loaded.transparent)
            self.assertEqual(loaded.ortho_scale_mm, 46.0)

            # 读不到 PNG 时退回请求分辨率
            self.assertTrue(sync_meta_resolution(meta, base / "missing.png", (640, 480)))
            self.assertEqual(load_meta(meta).resolution, (640, 480))

            # meta 不存在则安静跳过
            self.assertFalse(sync_meta_resolution(base / "nope.json", png))


if __name__ == "__main__":
    unittest.main()
