# SPDX-License-Identifier: GPL-3.0-or-later
"""布局：free 原样使用坐标；grid 按单元格自动摆放。"""

from __future__ import annotations

import math
from typing import Any

GRID_TYPES = {"rect", "circle", "text", "image", "panel", "data_plot", "blender_asset"}


def apply_layout(spec: dict[str, Any]) -> list[dict[str, Any]]:
    layout = spec["layout"]
    if layout["mode"] != "grid":
        return spec["elements"]

    width = spec["canvas"]["width_mm"]
    height = spec["canvas"]["height_mm"]
    cols = int(layout["cols"])
    gap = float(layout["gap_mm"])
    margin = float(layout["margin_mm"])

    targets = [el for el in spec["elements"]
               if el["type"] in GRID_TYPES and ("x_mm" not in el or "y_mm" not in el)]
    explicit = [el for el in targets if el.get("cell")]
    rows = max([el["cell"][0] + 1 for el in explicit] + [1])
    rows = max(rows, math.ceil(len(targets) / cols))

    cell_w = (width - 2 * margin - (cols - 1) * gap) / cols
    cell_h = (height - 2 * margin - (rows - 1) * gap) / rows
    if cell_w <= 0 or cell_h <= 0:
        raise ValueError("grid 布局的单元格尺寸为负：检查 cols/margin/gap")

    occupied: set[tuple[int, int]] = {tuple(el["cell"]) for el in explicit}
    cursor = 0

    for el in targets:
        if el.get("cell"):
            row, col = el["cell"]
        else:
            while (cursor // cols, cursor % cols) in occupied:
                cursor += 1
            row, col = cursor // cols, cursor % cols
            occupied.add((row, col))
            cursor += 1

        x0 = margin + col * (cell_w + gap)
        y0 = margin + row * (cell_h + gap)
        _place(el, x0, y0, cell_w, cell_h)
    return spec["elements"]


def _place(el: dict[str, Any], x0: float, y0: float,
           cell_w: float, cell_h: float) -> None:
    kind = el["type"]
    if kind == "rect":
        w = float(el.get("w_mm", cell_w))
        h = float(el.get("h_mm", cell_h))
        el["w_mm"], el["h_mm"] = w, h
        el.setdefault("x_mm", x0 + (cell_w - w) / 2)
        el.setdefault("y_mm", y0 + (cell_h - h) / 2)
    elif kind == "circle":
        el.setdefault("cx_mm", x0 + cell_w / 2)
        el.setdefault("cy_mm", y0 + cell_h / 2)
    elif kind == "text":
        el.setdefault("x_mm", x0 + 1.0)
        el.setdefault("y_mm", y0 + float(el.get("size_pt", 7)) * 25.4 / 72 + 1.0)
    elif kind in ("image", "panel", "data_plot", "blender_asset"):
        w = float(el.get("w_mm", cell_w))
        el["w_mm"] = w
        el.setdefault("x_mm", x0 + (cell_w - w) / 2)
        el.setdefault("y_mm", y0)
        if kind in ("panel", "data_plot"):
            el.setdefault("h_mm", float(el.get("h_mm", cell_h)))
