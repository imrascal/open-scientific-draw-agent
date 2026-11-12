# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_vector import Canvas, check_text_present, export, find_inkscape, verify_svg
from osda_vector.compose import place_svg, svg_viewbox
from osda_vector.export import ExportError
from osda_vector.svg import PT2MM


class TestCanvas(unittest.TestCase):
    def test_canvas_units(self):
        c = Canvas(85, 60)
        self.assertEqual(c.root.get("width"), "85mm")
        self.assertEqual(c.root.get("viewBox"), "0 0 85 60")

    def test_text_runs_subscript(self):
        c = Canvas(40, 20)
        before = len(c.layer)
        c.text(5, 10, "", runs=[{"t": "SiO"}, {"t": "2", "sub": True}])
        self.assertEqual(len(c.layer), before + 1)
        text_el = c.layer[-1]
        tspans = list(text_el)
        self.assertEqual(len(tspans), 2)
        self.assertEqual(tspans[1].get("font-size"), "70%")
        self.assertIn("dy", tspans[1].attrib)

    def test_text_runs_bold(self):
        c = Canvas(40, 20)
        c.text(5, 10, "", runs=[{"t": "Si"}, {"t": "2", "sub": True, "bold": True}])
        tspans = list(c.layer[-1])
        self.assertIsNone(tspans[0].get("font-weight"))
        self.assertEqual(tspans[1].get("font-weight"), "bold")

    def test_font_size_converted_to_mm(self):
        c = Canvas(40, 20)
        c.text(1, 1, "A", size_pt=7)
        size_mm = float(c.layer[-1].get("font-size"))
        self.assertAlmostEqual(size_mm, 7 * PT2MM, places=4)


class TestVerify(unittest.TestCase):
    def _save(self, canvas: Canvas, tmp: str) -> Path:
        return canvas.save(Path(tmp) / "t.svg")

    def test_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(85, 60)
            c.rect(1, 1, 10, 10, stroke="#000000", stroke_pt=0.5)
            c.text(2, 2, "Si", size_pt=7)
            report = verify_svg(self._save(c, tmp), expected_size_mm=(85, 60))
            self.assertTrue(report["ok"], report["errors"])
            self.assertIn("Si", report["texts"])

    def test_small_font_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(85, 60)
            c.text(2, 2, "tiny", size_pt=5)
            report = verify_svg(self._save(c, tmp))
            self.assertFalse(report["ok"])
            self.assertTrue(any("字号" in e for e in report["errors"]))

    def test_thin_stroke_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(85, 60)
            c.rect(1, 1, 10, 10, stroke="#000000", stroke_pt=0.2)
            report = verify_svg(self._save(c, tmp))
            self.assertFalse(report["ok"])
            self.assertTrue(any("线宽" in e for e in report["errors"]))

    def test_wrong_canvas_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(85, 60)
            report = verify_svg(self._save(c, tmp), expected_size_mm=(180, 120))
            self.assertFalse(report["ok"])

    def test_missing_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(85, 60)
            c.text(2, 2, "MoS2", size_pt=7)
            missing = check_text_present(self._save(c, tmp), ["MoS2", "WSe2"])
            self.assertEqual(missing, ["WSe2"])


class TestExport(unittest.TestCase):
    def test_export_if_inkscape_available(self):
        try:
            find_inkscape()
        except Exception:
            self.skipTest("未安装 Inkscape")
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(30, 20)
            c.rect(2, 2, 26, 16, fill="#EEEEEE", stroke="#000000", stroke_pt=0.5)
            c.text(4, 10, "test", size_pt=7)
            svg = c.save(Path(tmp) / "tiny.svg")
            files = export(svg, Path(tmp) / "out", formats=("pdf", "png"), dpi=300)
            for path in files.values():
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

    def test_svg_format_does_not_self_destruct(self):
        """回归：--formats svg 会删掉源 SVG 再尝试导出，导致 input not found。
        现在 svg 直接拷贝，不走 Inkscape。"""
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(30, 20)
            c.rect(2, 2, 26, 16, fill="#EEEEEE")
            svg = c.save(Path(tmp) / "t.svg")
            files = export(svg, Path(tmp) / "out", formats=("svg",))
            self.assertIn("svg", files)
            self.assertTrue(files["svg"].is_file())
            # 源文件也必须还在（export 的输入不能被自己删掉）
            self.assertTrue(svg.is_file())

    def test_unknown_format_rejected(self):
        """不可接受的格式必须在 Inkscape 调用之前就报错，不搞半吊子。"""
        with tempfile.TemporaryDirectory() as tmp:
            c = Canvas(30, 20)
            svg = c.save(Path(tmp) / "t.svg")
            with self.assertRaises(ExportError) as ctx:
                export(svg, Path(tmp) / "out", formats=("pdf", "bogus"))
            self.assertIn("不支持的导出格式", str(ctx.exception))


class TestCompose(unittest.TestCase):
    def test_svg_viewbox_parses_mm_units(self):
        """历史 bug：rstrip('pt') 对 '80mm' 无效，float() 直接拒绝。
        现在用正则只吃数字。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.svg"
            p.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="50mm">'
                '<rect width="10" height="10"/></svg>',
                encoding="utf-8",
            )
            vx, vy, vw, vh = svg_viewbox(p)
            self.assertEqual((vx, vy), (0.0, 0.0))
            self.assertAlmostEqual(vw, 80.0)
            self.assertAlmostEqual(vh, 50.0)

    def test_embedded_svg_sanitized(self):
        """外部 SVG 面板嵌入时 script/foreignObject/on* 属性必须被剥掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            evil = Path(tmp) / "evil.svg"
            evil.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm">'
                '<script>alert(1)</script>'
                '<rect width="10" height="10" onload="alert(2)"/>'
                '<foreignObject><div onclick="alert(3)">x</div></foreignObject>'
                '</svg>',
                encoding="utf-8",
            )
            c = Canvas(20, 20)
            place_svg(c, evil, 0, 0, 10)
            out = c.save(Path(tmp) / "out.svg").read_text(encoding="utf-8")
            self.assertNotIn("<script>", out)
            self.assertNotIn("foreignObject", out)
            self.assertNotIn("onload=", out)
            self.assertNotIn("onclick=", out)


class TestExampleGeometry(unittest.TestCase):
    """示例器件必须让源漏电极与二维半导体层直接接触，不能只是贴近或留缝。"""

    def test_electrodes_overlap_2d_layers(self):
        from examples import fig_stack

        canvas = fig_stack.build()
        rects = {}
        for el in canvas.layer.iter():
            element_id = el.get("id")
            if element_id in {"source", "drain", "mos2", "wse2"}:
                rects[element_id] = tuple(
                    float(el.get(key)) for key in ("x", "y", "width", "height")
                )
        self.assertEqual(set(rects), {"source", "drain", "mos2", "wse2"})

        def overlaps(a, b):
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            return (min(ax + aw, bx + bw) > max(ax, bx)
                    and min(ay + ah, by + bh) > max(ay, by))

        for electrode in ("source", "drain"):
            for layer in ("wse2", "mos2"):
                self.assertTrue(
                    overlaps(rects[electrode], rects[layer]),
                    f"{electrode} 必须与 {layer} 有实际重叠（直接接触）",
                )


if __name__ == "__main__":
    unittest.main()
