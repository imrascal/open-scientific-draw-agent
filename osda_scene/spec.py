# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene Spec 加载、校验与默认值归一化。

JSON Schema 负责结构；本模块负责结构表达不了的语义：
id 唯一、引用存在、资源文件存在、元素不要整体跑到画布外。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "scene.schema.json"
SVG_NS = "http://www.w3.org/2000/svg"
FORBIDDEN_SVG_TAGS = {"script", "foreignobject", "iframe", "object", "embed",
                      "style", "animate", "set"}

DEFAULTS = {
    "backend": "auto",
    "journal": {"font_family": "Arial", "min_font_pt": 7, "min_stroke_pt": 0.5, "dpi": 600},
    "layout": {"mode": "free", "cols": 2, "gap_mm": 4, "margin_mm": 5, "order": []},
    "progressive": {"enabled": False, "step": 1, "hold_ms": 600, "dpi": 200, "gif": True},
    "swarm": {"enabled": False, "cursors": 8, "trail": 20, "mode": "spatial",
              "duration_s": 12, "presentation_only": True},
    "output": {"formats": ["pdf", "png"], "dpi": 600, "color_mode": "RGB",
               "verify_text": True},
}

PLACED_TYPES = {"rect", "circle", "text", "image", "panel", "data_plot", "blender_asset"}


class SpecError(ValueError):
    """Spec 结构或语义不合法。"""


def load_spec(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise SpecError(f"spec 文件不存在: {p}")
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec 不是合法 JSON: {exc}") from exc
    except OSError as exc:
        raise SpecError(f"spec 读失败: {exc}") from exc
    try:
        spec = _merge_defaults(spec)
        _validate_schema(spec)
        _validate_semantics(spec, base=p.parent)
    except SpecError:
        raise
    except Exception as exc:
        # 收敛 KeyError / AttributeError / TypeError 等结构问题，不让 traceback 漏到 CLI
        raise SpecError(f"spec 加载异常: {type(exc).__name__}: {exc}") from exc
    return spec


def _merge_defaults(spec: dict[str, Any]) -> dict[str, Any]:
    for key, value in DEFAULTS.items():
        if key not in spec:
            spec[key] = json.loads(json.dumps(value))
        elif isinstance(value, dict):
            if not isinstance(spec[key], dict):
                # 类型错误交给 schema / 语义校验处理，这里不要再 AttributeError
                continue
            for sub, sub_value in value.items():
                spec[key].setdefault(sub, sub_value)
    return spec


def _validate_schema(spec: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:
        if "elements" not in spec or "canvas" not in spec:
            raise SpecError("缺少 elements/canvas，且未安装 jsonschema 无法完整校验")
        return
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(spec), key=lambda e: list(e.path))
    if not errors:
        return
    lines = []
    for err in errors[:8]:
        where = "/".join(str(p) for p in err.path) or "(root)"
        lines.append(f"{where}: {err.message}")
    raise SpecError("spec 校验失败:\n  " + "\n  ".join(lines))


def _validate_semantics(spec: dict[str, Any], base: Path) -> None:
    width = spec["canvas"]["width_mm"]
    height = spec["canvas"]["height_mm"]
    elements = spec["elements"]

    layout = spec.get("layout")
    if layout is None:
        spec["layout"] = {"mode": "free"}
        layout = spec["layout"]
    if not isinstance(layout, dict):
        raise SpecError(f"layout 必须是对象，实际是 {type(layout).__name__}")
    grid = layout.get("mode") == "grid"

    ids = [el["id"] for el in elements]
    if len(ids) != len(set(ids)):
        raise SpecError("元素 id 必须唯一")

    layout = spec.get("layout", {}) if isinstance(spec.get("layout"), dict) else {}
    order = layout.get("order") or []
    unknown = [oid for oid in order if oid not in ids]
    if unknown:
        raise SpecError("layout.order 引用了不存在的元素: " + ", ".join(unknown))

    for el in elements:
        kind = el["type"]
        if kind in PLACED_TYPES and not grid and ("x_mm" not in el or "y_mm" not in el):
            raise SpecError(f"元素 {el['id']} 在 free 布局下缺少 x_mm/y_mm")

        if kind == "image":
            _require_file(el["src"], base, el["id"])
        elif kind == "panel":
            _require_file(el["src"], base, el["id"])
        elif kind == "data_plot":
            _require_file(el["csv"], base, el["id"])
        elif kind == "blender_asset":
            asset = (base / el["asset_dir"]).resolve()
            if not asset.is_dir():
                raise SpecError(f"元素 {el['id']} 的 asset_dir 不存在: {asset}")
        elif kind == "raw_svg":
            _check_raw_svg(el)

        if "rotation_deg" in el and not isinstance(el["rotation_deg"], (int, float)):
            raise SpecError(f"元素 {el['id']} 的 rotation_deg 必须是数字")
        if "rotate_about_mm" in el:
            pivot = el["rotate_about_mm"]
            if (not isinstance(pivot, list) or len(pivot) != 2
                    or not all(isinstance(v, (int, float)) for v in pivot)):
                raise SpecError(f"元素 {el['id']} 的 rotate_about_mm 必须是 [x, y]")

        # grid 布局下坐标由 apply_layout 生成，这一步还没有，跳过 bbox
        if grid and "cell" in el and "x_mm" not in el:
            continue
        bbox = _bbox(el)
        if bbox:
            x, y, w, h = bbox
            if x + w < 0 or y + h < 0 or x > width or y > height:
                raise SpecError(f"元素 {el['id']} 完全落在画布外")

    # 后端与元素类型必须自洽
    kinds = {el["type"] for el in elements}
    if spec.get("backend") == "inkscape" and ({"data_plot", "blender_asset"} & kinds):
        raise SpecError("backend=inkscape 不能包含 data_plot/blender_asset，请用 composite")
    if spec.get("backend") == "blender" and ({"data_plot", "rect", "text"} & kinds):
        raise SpecError("backend=blender 只用于纯 3D 素材，请改用 composite")


def _require_file(rel: str, base: Path, element_id: str) -> None:
    path = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
    if not path.is_file():
        raise SpecError(f"元素 {element_id} 引用的文件不存在: {path}")


def _check_raw_svg(el: dict) -> None:
    """内联片段只允许静态、自包含的 SVG。"""
    fragment = el.get("svg", "")
    eid = el["id"]
    try:
        root = etree.fromstring(f'<svg xmlns="{SVG_NS}">{fragment}</svg>')
    except etree.XMLSyntaxError as exc:
        raise SpecError(f"raw_svg {eid} 不是合法 SVG 片段: {exc}") from exc

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in FORBIDDEN_SVG_TAGS:
            raise SpecError(f"raw_svg {eid} 含不允许的标签 <{tag}>")
        for attr, value in node.attrib.items():
            name = attr.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                raise SpecError(f"raw_svg {eid} 含事件属性 {name}")
            if name in ("href", "src") and value and not value.startswith(("#", "data:")):
                raise SpecError(f"raw_svg {eid} 只允许 # 引用或 data: URI，收到 {value[:40]}")
            if name == "style" and "url(" in value and "url(#" not in value:
                raise SpecError(f"raw_svg {eid} 的 style 含外部 url() 引用")


def _bbox(el: dict) -> tuple[float, float, float, float] | None:
    kind = el["type"]
    if kind == "rect":
        if not all(k in el for k in ("x_mm", "y_mm", "w_mm", "h_mm")):
            return None
        return el["x_mm"], el["y_mm"], el["w_mm"], el["h_mm"]
    if kind == "circle":
        if not all(k in el for k in ("cx_mm", "cy_mm", "r_mm")):
            return None
        return (el["cx_mm"] - el["r_mm"], el["cy_mm"] - el["r_mm"],
                2 * el["r_mm"], 2 * el["r_mm"])
    if kind == "ellipse":
        if not all(k in el for k in ("cx_mm", "cy_mm", "rx_mm", "ry_mm")):
            return None
        return (el["cx_mm"] - el["rx_mm"], el["cy_mm"] - el["ry_mm"],
                2 * el["rx_mm"], 2 * el["ry_mm"])
    if kind == "polygon":
        points = el.get("points_mm")
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    if kind == "raw_svg":
        return el.get("x_mm", 0) or 0, el.get("y_mm", 0) or 0, 0, 0
    if kind in ("line", "arrow"):
        if not all(k in el for k in ("x1_mm", "y1_mm", "x2_mm", "y2_mm")):
            return None
        x0, y0 = el["x1_mm"], el["y1_mm"]
        x1, y1 = el["x2_mm"], el["y2_mm"]
        return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
    if kind == "image":
        x = el.get("x_mm"); y = el.get("y_mm"); w = el.get("w_mm"); h = el.get("h_mm")
        if None in (w, h):
            return None
        return x or 0, y or 0, w, h or 0
    if kind == "panel":
        x = el.get("x_mm"); y = el.get("y_mm"); w = el.get("w_mm"); h = el.get("h_mm")
        if None in (w, h):
            return None
        return x or 0, y or 0, w, h or 0
    if kind == "data_plot":
        x = el.get("x_mm"); y = el.get("y_mm"); w = el.get("w_mm"); h = el.get("h_mm")
        if None in (w, h):
            return None
        return x or 0, y or 0, w, h or 0
    if kind == "blender_asset":
        x = el.get("x_mm"); y = el.get("y_mm"); w = el.get("w_mm")
        if w is None:
            return None
        return x or 0, y or 0, w, 0
    return None


def ordered_elements(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """按 layout.order 排序，未列出的保持文档顺序。"""
    order = spec["layout"].get("order") or []
    if not order:
        return list(spec["elements"])
    index = {eid: i for i, eid in enumerate(order)}
    return sorted(spec["elements"],
                  key=lambda el: (index.get(el["id"], len(order)),
                                  spec["elements"].index(el)))


def required_backend(spec: dict[str, Any]) -> str:
    kinds = {el["type"] for el in spec["elements"]}
    if "blender_asset" in kinds:
        return "composite"
    if "data_plot" in kinds:
        return "composite" if kinds - {"data_plot", "text"} else "matplotlib"
    return "inkscape"


def resolve_backend(spec: dict[str, Any]) -> str:
    declared = spec.get("backend", "auto")
    needed = required_backend(spec)
    if declared == "auto":
        return needed
    return declared
