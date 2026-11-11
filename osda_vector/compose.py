# SPDX-License-Identifier: GPL-3.0-or-later
"""把外部 SVG 组合进画布：读 viewBox、缩放、加 id 前缀。"""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from .svg import SVG_NS


def svg_viewbox(path: str | Path) -> tuple[float, float, float, float]:
    root = etree.parse(str(path)).getroot()
    vb = root.get("viewBox")
    if vb:
        return tuple(float(v) for v in vb.replace(",", " ").split())  # type: ignore[return-value]
    width = float(str(root.get("width", "100")).rstrip("pt"))
    height = float(str(root.get("height", "100")).rstrip("pt"))
    return 0.0, 0.0, width, height


def namespace_ids(group, prefix: str) -> None:
    """给嵌入子图的 id 加前缀，并重写 url(#id) / href="#id" 引用。"""
    mapping: dict[str, str] = {}
    for el in group.iter():
        if not isinstance(el.tag, str):
            continue
        old = el.get("id")
        if old:
            new = prefix + old
            mapping[old] = new
            el.set("id", new)
    if not mapping:
        return
    for el in group.iter():
        if not isinstance(el.tag, str):
            continue
        for attr, value in list(el.attrib.items()):
            if "url(#" in value or (value.startswith("#") and len(value) > 1):
                for old, new in mapping.items():
                    value = value.replace(f"url(#{old})", f"url(#{new})")
                    if value == f"#{old}":
                        value = f"#{new}"
                el.set(attr, value)


def place_svg(canvas, svg_path: str | Path, x: float, y: float,
              box_w: float, box_h: float | None = None,
              prefix: str = "", opacity: float | None = None) -> tuple[float, float]:
    """等比放入 (x, y) 开始、宽 box_w 的框，返回实际占据的 (w, h)。"""
    vx, vy, vw, vh = svg_viewbox(svg_path)
    scale = box_w / vw
    if box_h is not None:
        scale = min(scale, box_h / vh)
    root = etree.parse(str(svg_path)).getroot()
    transform = (f"translate({x:g},{y:g}) scale({scale:.6f}) "
                 f"translate({-vx:g},{-vy:g})")
    attrs = {"transform": transform}
    if opacity is not None:
        attrs["opacity"] = f"{opacity:g}"
    group = etree.SubElement(canvas.layer, f"{{{SVG_NS}}}g", attrs)
    for child in root:
        tag = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
        if tag in ("metadata", "title", "desc"):
            continue
        if tag == "rect" and child.get("id") == "page":
            continue
        group.append(copy.deepcopy(child))
    if prefix:
        namespace_ids(group, prefix)
    return vw * scale, vh * scale
