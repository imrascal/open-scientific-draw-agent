# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene Spec 加载、校验与默认值归一化。

JSON Schema 负责结构；本模块负责结构表达不了的语义：
id 唯一、引用存在、资源文件存在、元素不要整体跑到画布外。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "scene.schema.json"

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
    spec = _merge_defaults(spec)
    _validate_schema(spec)
    _validate_semantics(spec, base=p.parent)
    return spec


def _merge_defaults(spec: dict[str, Any]) -> dict[str, Any]:
    for key, value in DEFAULTS.items():
        if key not in spec:
            spec[key] = json.loads(json.dumps(value))
        elif isinstance(value, dict):
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

    ids = [el["id"] for el in elements]
    if len(ids) != len(set(ids)):
        raise SpecError("元素 id 必须唯一")

    order = spec["layout"].get("order") or []
    unknown = [oid for oid in order if oid not in ids]
    if unknown:
        raise SpecError("layout.order 引用了不存在的元素: " + ", ".join(unknown))

    grid = spec["layout"]["mode"] == "grid"
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

        bbox = _bbox(el)
        if bbox:
            x, y, w, h = bbox
            if x + w < 0 or y + h < 0 or x > width or y > height:
                raise SpecError(f"元素 {el['id']} 完全落在画布外")

    # 后端与元素类型必须自洽
    kinds = {el["type"] for el in elements}
    if spec["backend"] == "inkscape" and ({"data_plot", "blender_asset"} & kinds):
        raise SpecError("backend=inkscape 不能包含 data_plot/blender_asset，请用 composite")
    if spec["backend"] == "blender" and ({"data_plot", "rect", "text"} & kinds):
        raise SpecError("backend=blender 只用于纯 3D 素材，请改用 composite")


def _require_file(rel: str, base: Path, element_id: str) -> None:
    path = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
    if not path.is_file():
        raise SpecError(f"元素 {element_id} 引用的文件不存在: {path}")


def _bbox(el: dict) -> tuple[float, float, float, float] | None:
    kind = el["type"]
    if kind == "rect":
        return el["x_mm"], el["y_mm"], el["w_mm"], el["h_mm"]
    if kind == "circle":
        return (el["cx_mm"] - el["r_mm"], el["cy_mm"] - el["r_mm"],
                2 * el["r_mm"], 2 * el["r_mm"])
    if kind in ("line", "arrow"):
        x0, y0 = el["x1_mm"], el["y1_mm"]
        x1, y1 = el["x2_mm"], el["y2_mm"]
        return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
    if kind == "image":
        return el.get("x_mm", 0), el.get("y_mm", 0), el["w_mm"], el.get("h_mm", 0)
    if kind == "panel":
        return el.get("x_mm", 0), el.get("y_mm", 0), el["w_mm"], el.get("h_mm", 0)
    if kind == "data_plot":
        return el.get("x_mm", 0), el.get("y_mm", 0), el["w_mm"], el.get("h_mm", 0)
    if kind == "blender_asset":
        return el.get("x_mm", 0), el.get("y_mm", 0), el["w_mm"], 0
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
