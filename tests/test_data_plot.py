# SPDX-License-Identifier: GPL-3.0-or-later
"""多序列数据图与误差棒测试。"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_scene.render import _plot_svg
from osda_scene.spec import SpecError, load_spec

CSV_ROWS = [
    ("x", "y1", "y2", "e1", "e2"),
    ("0", "1.0", "2.0", "0.10", "0.20"),
    ("1", "2.0", "3.0", "0.10", "0.20"),
    ("2", "3.0", "4.0", "0.10", "0.20"),
]


def _write_csv(base: Path, name: str = "d.csv") -> Path:
    path = base / name
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(CSV_ROWS)
    return path


def _element(**over):
    el = {"id": "plot", "type": "data_plot", "csv": "d.csv", "x": "x",
          "w_mm": 40, "h_mm": 28}
    el.update(over)
    return el


class TestPlot(unittest.TestCase):
    def test_multi_series_with_errorbars(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_csv(base)
            svg = _plot_svg(_element(series=[
                {"y": "y1", "label": "forward", "yerr": "e1"},
                {"y": "y2", "label": "reverse", "yerr": "e2", "dash": True},
            ]), base, base / "work")
            text = svg.read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("forward", text)
            self.assertIn("reverse", text)

    def test_single_series_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_csv(base)
            svg = _plot_svg(_element(y="y1", color="#2867A0"), base, base / "work")
            self.assertTrue(svg.is_file())

    def test_missing_column_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_csv(base)
            with self.assertRaises(SpecError):
                _plot_svg(_element(series=[{"y": "nope"}]), base, base / "work")

    def test_xlim_ylim_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_csv(base)
            svg = _plot_svg(_element(y="y1", xlim=[0, 2], ylim=[0, 5]),
                            base, base / "work")
            self.assertTrue(svg.is_file())


class TestPlotSchema(unittest.TestCase):
    def _load(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_csv(base)
            path = base / "s.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_spec(path)

    def _spec(self, element):
        return {
            "version": "1.0", "name": "p",
            "canvas": {"width_mm": 60, "height_mm": 40},
            "layout": {"mode": "free"},
            "output": {"formats": ["svg"]},
            "elements": [element],
        }

    def test_series_requires_y(self):
        with self.assertRaises(SpecError):
            self._load(self._spec({
                "id": "p", "type": "data_plot", "csv": "d.csv", "x": "x",
                "w_mm": 40, "x_mm": 5, "y_mm": 5,
                "series": [{"label": "no column"}],
            }))

    def test_requires_y_or_series(self):
        with self.assertRaises(SpecError):
            self._load(self._spec({
                "id": "p", "type": "data_plot", "csv": "d.csv", "x": "x",
                "w_mm": 40, "x_mm": 5, "y_mm": 5,
            }))

    def test_series_accepted(self):
        spec = self._load(self._spec({
            "id": "p", "type": "data_plot", "csv": "d.csv", "x": "x",
            "w_mm": 40, "x_mm": 5, "y_mm": 5,
            "series": [{"y": "y1", "yerr": "e1"}],
        }))
        self.assertEqual(spec["elements"][0]["series"][0]["y"], "y1")


if __name__ == "__main__":
    unittest.main()
