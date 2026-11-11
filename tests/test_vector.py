# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_vector import Canvas, check_text_present, export, find_inkscape, verify_svg
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


if __name__ == "__main__":
    unittest.main()
