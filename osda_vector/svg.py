# SPDX-License-Identifier: GPL-3.0-or-later
"""最小矢量层：按毫米坐标生成 SVG。

设计原则：
- 用户单位 = 1 mm，字号/线宽一律用 pt 传入并在此换算，杜绝 pt/mm 混用；
- 下标用 <tspan dy> 实现，不依赖 Unicode 下标字符（Arial 没有 U+2082）；
- 只输出 Inkscape 能稳定处理的子集：rect/circle/line/polygon/path/text/image/marker。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
PT2MM = 25.4 / 72.0


class Canvas:
    def __init__(self, width_mm: float, height_mm: float,
                 font_family: str = "Arial"):
        self.width_mm = float(width_mm)
        self.height_mm = float(height_mm)
        self.font_family = font_family
        self.root = etree.Element(
            f"{{{SVG_NS}}}svg",
            nsmap={None: SVG_NS, "xlink": XLINK_NS},
        )
        self.root.set("width", f"{width_mm:g}mm")
        self.root.set("height", f"{height_mm:g}mm")
        self.root.set("viewBox", f"0 0 {width_mm:g} {height_mm:g}")
        self.root.set("version", "1.1")

        # 白色背景矩形：导出 PDF/PNG 时固定白底，避免透明底在不同阅读器里变黑
        etree.SubElement(self.root, f"{{{SVG_NS}}}rect", {
            "id": "page", "x": "0", "y": "0",
            "width": f"{width_mm:g}", "height": f"{height_mm:g}",
            "fill": "#FFFFFF",
        })
        self.layer = etree.SubElement(self.root, f"{{{SVG_NS}}}g", {"id": "layer1"})

    # ---------------- 基本图元 ----------------

    def rect(self, x: float, y: float, w: float, h: float, *,
             fill: str = "#FFFFFF", stroke: str = "none", stroke_pt: float = 0.5,
             rx: float = 0, opacity: float = 1.0, element_id: str | None = None):
        attrs = {
            "x": f"{x:g}", "y": f"{y:g}", "width": f"{w:g}", "height": f"{h:g}",
            "fill": fill, "stroke": stroke,
            "stroke-width": f"{stroke_pt * PT2MM:g}",
        }
        if rx:
            attrs["rx"] = f"{rx:g}"
        if opacity != 1.0:
            attrs["opacity"] = f"{opacity:g}"
        if element_id:
            attrs["id"] = element_id
        return etree.SubElement(self.layer, f"{{{SVG_NS}}}rect", attrs)

    def circle(self, cx: float, cy: float, r: float, *,
               fill: str = "#FFFFFF", stroke: str = "none", stroke_pt: float = 0.5):
        return etree.SubElement(self.layer, f"{{{SVG_NS}}}circle", {
            "cx": f"{cx:g}", "cy": f"{cy:g}", "r": f"{r:g}",
            "fill": fill, "stroke": stroke,
            "stroke-width": f"{stroke_pt * PT2MM:g}",
        })

    def polygon(self, points: Sequence[tuple[float, float]], *,
                fill: str = "#FFFFFF", stroke: str = "none", stroke_pt: float = 0.5):
        return etree.SubElement(self.layer, f"{{{SVG_NS}}}polygon", {
            "points": " ".join(f"{x:g},{y:g}" for x, y in points),
            "fill": fill, "stroke": stroke,
            "stroke-width": f"{stroke_pt * PT2MM:g}",
        })

    def path(self, d: str, *, fill: str = "none", stroke: str = "#000000",
             stroke_pt: float = 0.75, dash: str | None = None):
        attrs = {"d": d, "fill": fill, "stroke": stroke,
                 "stroke-width": f"{stroke_pt * PT2MM:g}"}
        if dash:
            attrs["stroke-dasharray"] = dash
        return etree.SubElement(self.layer, f"{{{SVG_NS}}}path", attrs)

    def line(self, x1: float, y1: float, x2: float, y2: float, *,
             stroke: str = "#000000", stroke_pt: float = 0.75,
             dash: str | None = None, arrow: bool = False):
        attrs = {
            "x1": f"{x1:g}", "y1": f"{y1:g}", "x2": f"{x2:g}", "y2": f"{y2:g}",
            "stroke": stroke, "stroke-width": f"{stroke_pt * PT2MM:g}",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        el = etree.SubElement(self.layer, f"{{{SVG_NS}}}line", attrs)
        if arrow:
            self._arrowhead(x1, y1, x2, y2, fill=stroke)
        return el

    def _arrowhead(self, x1: float, y1: float, x2: float, y2: float, *,
                   fill: str = "#000000", size_mm: float = 1.9):
        """显式三角形箭头。

        用路径而不是 <marker>：marker 不随 stroke-dashoffset 隐藏，
        在做描边动画时箭头会提前出现在终点。
        """
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            return None
        ux, uy = dx / norm, dy / norm
        px, py = -uy, ux
        half = size_mm * 0.42
        bx, by = x2 - ux * size_mm, y2 - uy * size_mm
        d = (f"M {x2:g} {y2:g} L {bx + px * half:g} {by + py * half:g} "
             f"L {bx - px * half:g} {by - py * half:g} Z")
        return etree.SubElement(self.layer, f"{{{SVG_NS}}}path", {
            "d": d, "fill": fill, "stroke": "none", "class": "arrowhead",
        })

    def curve_arrow(self, x1: float, y1: float, cx: float, cy: float,
                    x2: float, y2: float, *, stroke: str = "#000000",
                    stroke_pt: float = 0.75):
        """二次贝塞尔箭头，用于弯曲的输运/光路示意。"""
        el = etree.SubElement(self.layer, f"{{{SVG_NS}}}path", {
            "d": f"M {x1:g} {y1:g} Q {cx:g} {cy:g} {x2:g} {y2:g}",
            "fill": "none", "stroke": stroke,
            "stroke-width": f"{stroke_pt * PT2MM:g}",
        })
        self._arrowhead(cx, cy, x2, y2, fill=stroke)
        return el

    # ---------------- 文本 ----------------

    def text(self, x: float, y: float, content, *, size_pt: float = 7,
             fill: str = "#000000", anchor: str = "start",
             weight: str = "normal", runs: Iterable[dict] | None = None,
             element_id: str | None = None):
        """content 为字符串，或 runs=[{"t": "SiO"}, {"t": "2", "sub": True}]。"""
        attrs = {
            "x": f"{x:g}", "y": f"{y:g}",
            "font-family": self.font_family,
            "font-size": f"{size_pt * PT2MM:g}",
            "fill": fill,
            "text-anchor": anchor,
        }
        if weight != "normal":
            attrs["font-weight"] = weight
        if element_id:
            attrs["id"] = element_id
        el = etree.SubElement(self.layer, f"{{{SVG_NS}}}text", attrs)

        items = list(runs) if runs else [{"t": str(content)}]
        offset = 0  # 0=正常 1=下标 -1=上标
        for run in items:
            level = 1 if run.get("sub") else (-1 if run.get("sup") else 0)
            tsp = etree.SubElement(el, f"{{{SVG_NS}}}tspan")
            tsp.text = str(run.get("t", ""))
            if level:
                tsp.set("font-size", "70%")
            if run.get("bold"):
                tsp.set("font-weight", "bold")
            if level != offset:
                shift = (level - offset) * 0.32
                tsp.set("dy", f"{shift:+.2f}em")
                offset = level
        return el

    def image(self, src: str | Path, x: float, y: float, w: float,
              h: float | None = None, embed: bool = False):
        from PIL import Image
        with Image.open(src) as img:
            px_w, px_h = img.size
        height = h if h is not None else w * px_h / px_w
        el = etree.SubElement(self.layer, f"{{{SVG_NS}}}image", {
            "x": f"{x:g}", "y": f"{y:g}", "width": f"{w:g}", "height": f"{height:g}",
            "preserveAspectRatio": "xMidYMid meet",
        })
        if embed:
            import base64
            data = base64.b64encode(Path(src).read_bytes()).decode("ascii")
            el.set(f"{{{XLINK_NS}}}href", f"data:image/png;base64,{data}")
        else:
            el.set(f"{{{XLINK_NS}}}href", Path(src).resolve().as_uri())
        return el

    # ---------------- 输出 ----------------

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 防止 pretty_print 在 <text> 的 tspan 之间插入缩进空白（会被渲染成空格）
        for el in self.root.iter(f"{{{SVG_NS}}}text"):
            if el.text is None:
                el.text = ""
            for child in el:
                if child.tail is None:
                    child.tail = ""
        p.write_bytes(etree.tostring(self.root, pretty_print=True,
                                     xml_declaration=True, encoding="UTF-8"))
        return p
