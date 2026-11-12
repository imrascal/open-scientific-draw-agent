# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_scene import build_swarm_html, load_spec, render_scene, run_progressive
from osda_scene.layout import apply_layout
from osda_scene.spec import SpecError


def _has_inkscape() -> bool:
    try:
        from osda_vector import find_inkscape

        find_inkscape()
        return True
    except Exception:
        return False


HAS_INKSCAPE = _has_inkscape()


def _spec(elements, **over):
    data = {
        "version": "1.0",
        "name": "t",
        "canvas": {"width_mm": 40, "height_mm": 30},
        "journal": {"font_family": "Arial", "min_font_pt": 7,
                    "min_stroke_pt": 0.5, "dpi": 200},
        "layout": {"mode": "free"},
        "progressive": {"enabled": False},
        "swarm": {"enabled": False},
        "output": {"formats": ["pdf", "png"], "dpi": 200},
        "elements": elements,
    }
    data.update(over)
    return data


RECT = {"id": "r1", "type": "rect", "x_mm": 5, "y_mm": 5, "w_mm": 20, "h_mm": 10,
        "fill": "#DDDDDD", "stroke": "#333333", "stroke_pt": 0.5}
TEXT = {"id": "t1", "type": "text", "x_mm": 5, "y_mm": 25,
        "content": "Si", "size_pt": 7}


class TestSpecValidation(unittest.TestCase):
    def _write(self, tmp, data):
        path = Path(tmp) / "s.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = load_spec(self._write(tmp, _spec([RECT, TEXT])))
            self.assertEqual(spec["backend"], "auto")
            self.assertEqual(len(spec["elements"]), 2)

    def test_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([RECT])
            data["nonsense"] = 1
            with self.assertRaises(SpecError):
                load_spec(self._write(tmp, data))

    def test_duplicate_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SpecError):
                load_spec(self._write(tmp, _spec([RECT, dict(RECT)])))

    def test_missing_coords_in_free_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            el = {k: v for k, v in RECT.items() if k not in ("x_mm", "y_mm")}
            with self.assertRaises(SpecError):
                load_spec(self._write(tmp, _spec([el])))

    def test_backend_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([RECT], backend="inkscape")
            data["elements"] = [RECT, {
                "id": "plot", "type": "data_plot", "csv": "x.csv", "x": "a", "y": "b",
                "x_mm": 0, "y_mm": 0, "w_mm": 20,
            }]
            (Path(tmp) / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            with self.assertRaises(SpecError):
                load_spec(self._write(tmp, data))

    def test_order_reference_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([RECT], layout={"mode": "free", "order": ["nope"]})
            with self.assertRaises(SpecError):
                load_spec(self._write(tmp, data))

    def test_grid_rect_with_only_cell(self):
        """grid 布局下 rect 只给 cell/w_mm/h_mm 不应该在 load_spec 阶段 KeyError。"""
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([
                {"id": "g1", "type": "rect", "cell": [0, 0],
                 "w_mm": 10, "h_mm": 10, "fill": "#ccc"},
            ], layout={"mode": "grid", "cols": 2, "gap_mm": 2, "margin_mm": 2})
            # 加载阶段不崩就行，坐标由 apply_layout 填
            spec = load_spec(self._write(tmp, data))
            self.assertEqual(spec["elements"][0]["cell"], [0, 0])
            apply_layout(spec)
            self.assertIn("x_mm", spec["elements"][0])

    def test_grid_circle_with_only_radius(self):
        """grid 布局下 circle 只给 cell/r_mm 不应该 KeyError。"""
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([
                {"id": "c1", "type": "circle", "cell": [0, 0],
                 "r_mm": 3, "fill": "#aaa"},
            ], layout={"mode": "grid", "cols": 2})
            spec = load_spec(self._write(tmp, data))
            apply_layout(spec)
            self.assertIn("cx_mm", spec["elements"][0])

    def test_layout_type_must_be_object(self):
        """layout 写成字符串要给出清晰 SpecError，不是 AttributeError traceback。"""
        with tempfile.TemporaryDirectory() as tmp:
            data = _spec([RECT], layout="grid")
            with self.assertRaises(SpecError) as ctx:
                load_spec(self._write(tmp, data))
            # jsonschema 先校验（Draft202012），错误信息可能来自 schema 或后面的语义校验；
            # 两种都接受，只要是 SpecError、不泄漏 AttributeError 就行。
            msg = str(ctx.exception)
            self.assertTrue(
                "layout" in msg and ("object" in msg or "必须是对象" in msg),
                msg,
            )


class TestMock3DSummary(unittest.TestCase):
    """Scene Spec + mock 3D 必须把 renderer 暴露在 summary 里，便于 agent 判断。"""

    def test_scene_spec_summary_exposes_mock_3d(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            asset_dir = base / "fake3d"
            asset_dir.mkdir()
            (asset_dir / "build.py").write_text("import os\n", encoding="utf-8")
            data = _spec([{
                "id": "fake3d", "type": "blender_asset",
                "asset_dir": "fake3d", "w_mm": 20,
                "x_mm": 5, "y_mm": 5,
            }], backend="composite")
            path = base / "s.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            spec = load_spec(path)
            spec["_base"] = str(base)
            out = base / "out"

            from osda_scene.render import prepare_elements
            elements = prepare_elements(spec, out / "_work", renderer_override="mock")
            result = render_scene(spec, out, formats=("svg",), elements=elements)

            self.assertIn("assets", result)
            self.assertTrue(result["assets"])
            self.assertEqual(result["assets"][0]["id"], "fake3d")
            self.assertEqual(result["assets"][0]["renderer"], "mock")
            self.assertTrue(result["degraded"])
            self.assertTrue(any("mock" in w for w in result["report"]["warnings"]))


class TestGridLayout(unittest.TestCase):
    def test_auto_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _spec([
                {"id": "a", "type": "panel", "src": "a.svg", "w_mm": 15},
                {"id": "b", "type": "panel", "src": "a.svg", "w_mm": 15},
                {"id": "c", "type": "panel", "src": "a.svg", "w_mm": 15},
            ], layout={"mode": "grid", "cols": 2, "gap_mm": 2, "margin_mm": 2})
            (Path(tmp) / "a.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" '
                'viewBox="0 0 10 10"><rect x="0" y="0" width="10" height="10"/></svg>',
                encoding="utf-8")
            apply_layout(spec)
            xs = [round(el["x_mm"], 3) for el in spec["elements"]]
            ys = [round(el["y_mm"], 3) for el in spec["elements"]]
            self.assertNotEqual(xs[0], xs[1])   # 同一行不同列
            self.assertEqual(ys[0], ys[1])
            self.assertGreater(ys[2], ys[1])    # 第三个换行


class TestRender(unittest.TestCase):
    @unittest.skipUnless(HAS_INKSCAPE, "未安装 Inkscape")
    def test_render_vector_and_tiff(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _spec([RECT, TEXT])
            out = Path(tmp) / "out"
            result = render_scene(spec, out, formats=("pdf", "png", "tiff"),
                                  dpi=200, color_mode="CMYK")
            self.assertTrue(result["ok"], result["report"]["errors"])
            for key in ("pdf", "png", "tiff"):
                self.assertTrue(Path(result["files"][key]).is_file())
            dpi = result["checks"]["png_dpi"]["dpi"]
            self.assertAlmostEqual(dpi[0], 200, delta=1)
            self.assertTrue(result["checks"]["pdf_fonts"]["embedded"])

            from PIL import Image
            with Image.open(result["files"]["tiff"]) as img:
                self.assertEqual(img.mode, "CMYK")

    @unittest.skipUnless(HAS_INKSCAPE, "未安装 Inkscape")
    def test_progressive_gif(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _spec([RECT, TEXT, {**RECT, "id": "r2", "x_mm": 20}],
                         progressive={"enabled": True, "step": 1,
                                      "hold_ms": 100, "dpi": 100, "gif": True})
            out = Path(tmp) / "out"
            result = run_progressive(spec, out)
            self.assertGreaterEqual(result["frames"], 3)
            gif = Path(result["gif"])
            self.assertTrue(gif.is_file())
            from PIL import Image
            with Image.open(gif) as img:
                self.assertEqual(img.n_frames, result["frames"])

    @unittest.skipUnless(HAS_INKSCAPE, "未安装 Inkscape")
    def test_swarm_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _spec([RECT, TEXT, {**RECT, "id": "r2", "x_mm": 20}],
                         swarm={"enabled": True, "cursors": 4, "duration_s": 5})
            out = Path(tmp) / "out"
            result = render_scene(spec, out)
            svg = out / "t.svg"
            self.assertTrue(svg.is_file())
            info = build_swarm_html(svg, spec, spec["elements"], out / "swarm.html")
            html = (out / "swarm.html").read_text(encoding="utf-8")
            self.assertEqual(info["cursors"], 3)   # 3 个元素，最多 3 个光标
            self.assertEqual(info["steps"], 3)
            self.assertEqual(html.count('class="cursor"'), 3)
            self.assertIn('id="el_r1"', html)
            self.assertIn("构建回放", html)

    @unittest.skipUnless(HAS_INKSCAPE, "未安装 Inkscape")
    def test_data_plot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "d.csv").write_text("x,y\n0,1\n1,2\n2,3\n", encoding="utf-8")
            spec = _spec([{
                "id": "plot", "type": "data_plot", "csv": "d.csv", "x": "x", "y": "y",
                "x_mm": 2, "y_mm": 2, "w_mm": 30, "h_mm": 20,
            }], backend="matplotlib")
            spec["_base"] = str(base)
            result = render_scene(spec, base / "out", dpi=150)
            self.assertTrue(result["ok"], result["report"]["errors"])

    def test_pdf_panel_import(self):
        try:
            from osda_vector import Canvas, export, find_inkscape
            find_inkscape()
        except Exception:
            self.skipTest("未安装 Inkscape")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            c = Canvas(30, 20)
            c.rect(2, 2, 26, 16, fill="#EEEEEE", stroke="#000000", stroke_pt=0.5)
            c.text(4, 10, "panel", size_pt=7)
            svg = c.save(base / "src.svg")
            export(svg, base, formats=("pdf",), dpi=150)

            spec = _spec([{
                "id": "p", "type": "panel", "src": str(base / "src.pdf"),
                "x_mm": 2, "y_mm": 2, "w_mm": 30, "h_mm": 20, "label": "a",
            }])
            spec["_base"] = str(base)
            result = render_scene(spec, base / "out", dpi=150)
            self.assertTrue(result["ok"], result["report"]["errors"])
            self.assertGreater(Path(result["files"]["pdf"]).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
