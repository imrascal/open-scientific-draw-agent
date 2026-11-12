# SPDX-License-Identifier: GPL-3.0-or-later
"""把外部 SVG 组合进画布：读 viewBox、缩放、加 id 前缀、清洗危险节点。"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from lxml import etree

from .svg import SVG_NS


def _parse_length(value: str | None, default: float = 100.0) -> float:
    """从 SVG length 属性里提取数值，接受 ``80mm`` / ``2.5cm`` / ``600px`` / ``120`` 等。

    历史上用 ``rstrip("pt")`` 其实是按字符剥离 p 和 t，会把 ``80mm`` 变成 ``80mm``（没变），
    再被 float() 直接拒绝。这里用正则只吃数字部分，单位扔一边。
    """
    if value is None:
        return default
    value = str(value).strip()
    m = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", value)
    if not m:
        return default
    return float(m.group(1))


def svg_viewbox(path: str | Path) -> tuple[float, float, float, float]:
    root = etree.parse(str(path)).getroot()
    vb = root.get("viewBox")
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            return tuple(_parse_length(p) for p in parts)  # type: ignore[return-value]
    width = _parse_length(root.get("width"), 100.0)
    height = _parse_length(root.get("height"), 100.0)
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
    """等比放入 (x, y) 开始、宽 box_w 的框，返回实际占据的 (w, h)。

    嵌入前会剥离外部 SVG 里的 ``script`` / ``foreignObject`` / ``style`` 节点，
    以及所有 ``on*`` 属性，避免第三方面板在合成图里执行脚本或全局样式污染宿主。
    """
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
        if tag in ("metadata", "title", "desc", "script", "foreignObject"):
            continue
        if tag == "rect" and child.get("id") == "page":
            continue
        cloned = copy.deepcopy(child)
        _sanitize(cloned)
        group.append(cloned)
    if prefix:
        namespace_ids(group, prefix)
    return vw * scale, vh * scale


def _sanitize(el) -> None:
    """递归清理外部 SVG 里的危险节点和属性。原地修改。"""
    remove_tags = {"script", "foreignObject"}
    # 注意：style 本身不是脚本，但会污染宿主样式；保守处理只剥全局 style
    for child in list(el):
        if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] in remove_tags:
            el.remove(child)
            continue
        _sanitize(child)

    # 剥掉所有事件属性（onclick / onload / onerror ...）
    for attr in list(el.attrib.keys()):
        local = attr.rsplit("}", 1)[-1]
        if local.startswith("on"):
            del el.attrib[attr]

    # 剥掉可能的 javascript: URL（xlink:href / href）
    for attr in list(el.attrib.keys()):
        local = attr.rsplit("}", 1)[-1]
        if local in ("href",):
            val = el.attrib[attr].strip().lower()
            if val.startswith(("javascript:", "data:text/html")):
                del el.attrib[attr]
