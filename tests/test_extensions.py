# SPDX-License-Identifier: GPL-3.0-or-later
"""polygon / ellipse / rotation / raw_svg 的扩展能力测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_scene.render import build_canvas
from osda_scene.spec import SpecError, load_spec
from osda_vector import check_text_present


def _spec(elements):
    return {
        "version": "1.0",
        "name": "ext",
        "canvas": {"width_mm": 60, "height_mm": 40},
        "journal": {"font_family": "Arial", "min_font_pt": 7,
                    "min_stroke_pt": 0.5, "dpi": 300},
        "layout": {"mode": "free"},
        "progressive": {"enabled": False},
        "swarm": {"enabled": False},
        "output": {"formats": ["svg"], "dpi": 300},
        "elements": elements,
    }


def _load(data):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return load_spec(path)


def _svg(elements):
    spec = _load(_spec(elements))
    canvas = build_canvas(spec, spec["elements"])
    with tempfile.TemporaryDirectory() as tmp:
        path = canvas.save(Path(tmp) / "t.svg")
        return path.read_text(encoding="utf-8")


class TestGeometry(unittest.TestCase):
    def test_polygon(self):
        svg = _svg([{
            "id": "tri", "type": "polygon",
            "points_mm": [[5, 5], [25, 5], [15, 20]],
            "fill": "#DDDDDD", "stroke": "#000000", "stroke_pt": 0.5,
        }])
        self.assertIn("<polygon", svg)
        self.assertIn("5,5", svg)

    def test_ellipse(self):
        svg = _svg([{
            "id": "e1", "type": "ellipse", "cx_mm": 20, "cy_mm": 15,
            "rx_mm": 8, "ry_mm": 4, "fill": "#EEEEEE", "stroke": "#000000",
            "stroke_pt": 0.5,
        }])
        self.assertIn("<ellipse", svg)
        self.assertIn('rx="8"', svg)

    def test_rotation_uses_bbox_center(self):
        svg = _svg([{
            "id": "r1", "type": "rect", "x_mm": 10, "y_mm": 10,
            "w_mm": 20, "h_mm": 10, "rotation_deg": 30,
            "fill": "#FFFFFF", "stroke": "#000000", "stroke_pt": 0.5,
        }])
        self.assertIn('transform="rotate(30 20 15)"', svg)

    def test_rotation_explicit_pivot(self):
        svg = _svg([{
            "id": "t1", "type": "text", "x_mm": 10, "y_mm": 20, "content": "A",
            "size_pt": 7, "rotation_deg": -90, "rotate_about_mm": [10, 20],
        }])
        self.assertIn('transform="rotate(-90 10 20)"', svg)


class TestRawSvg(unittest.TestCase):
    FRAGMENT = (
        '<rect id="inner" x="0" y="0" width="10" height="6" '
        'fill="#FFCC00" stroke="#000000" stroke-width="0.2"/>'
        '<text x="1" y="4" font-family="Arial" font-size="2.5">RAW</text>'
    )

    def test_embeds_and_prefixes_ids(self):
        svg = _svg([{
            "id": "badge", "type": "raw_svg", "svg": self.FRAGMENT,
            "x_mm": 10, "y_mm": 10,
        }])
        self.assertIn('id="e0_badge_inner"', svg)
        self.assertIn("RAW", svg)

    def test_text_is_checked(self):
        svg = _svg([{
            "id": "badge", "type": "raw_svg", "svg": self.FRAGMENT,
            "x_mm": 10, "y_mm": 10,
        }])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.svg"
            path.write_text(svg, encoding="utf-8")
            self.assertEqual(check_text_present(path, ["RAW"]), [])
            self.assertEqual(check_text_present(path, ["MISSING"]), ["MISSING"])

    def test_rejects_script(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "bad", "type": "raw_svg", "x_mm": 0, "y_mm": 0,
                "svg": '<g><script>alert(1)</script></g>',
            }]))

    def test_rejects_event_handler(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "bad", "type": "raw_svg", "x_mm": 0, "y_mm": 0,
                "svg": '<rect width="5" height="5" onclick="x()"/>',
            }]))

    def test_rejects_external_href(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "bad", "type": "raw_svg", "x_mm": 0, "y_mm": 0,
                "svg": '<image href="https://example.com/a.png" width="5" height="5"/>',
            }]))

    def test_rejects_broken_xml(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "bad", "type": "raw_svg", "x_mm": 0, "y_mm": 0,
                "svg": "<rect width='5' height='5'>",
            }]))


class TestSchemaStrictness(unittest.TestCase):
    def test_polygon_needs_three_points(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "p", "type": "polygon", "points_mm": [[0, 0], [1, 1]],
            }]))

    def test_unknown_rotation_type(self):
        with self.assertRaises(SpecError):
            _load(_spec([{
                "id": "r", "type": "rect", "x_mm": 0, "y_mm": 0,
                "w_mm": 5, "h_mm": 5, "rotation_deg": "30",
            }]))


if __name__ == "__main__":
    unittest.main()
