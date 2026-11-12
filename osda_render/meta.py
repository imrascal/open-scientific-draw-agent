# SPDX-License-Identifier: GPL-3.0-or-later
"""素材元数据契约。

3D 渲染只回传一张 PNG 是不够的：没有相机尺度就无法把图贴回矢量版面，
没有透明背景信息就会在彩色底上出现白块。meta.json 由 build 脚本写出，
本模块负责读取、校验与 alpha 检查。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class MetaError(ValueError):
    """meta.json 缺失字段或格式错误。"""


@dataclass
class AssetMeta:
    asset_id: str = ""
    resolution: tuple[int, int] | None = None
    ortho_scale_mm: float | None = None
    transparent: bool = False
    target_width_mm: float | None = None
    blender_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra") or {}
        data.update(extra)
        if self.resolution is not None:
            data["resolution"] = list(self.resolution)
        return data


def write_meta(path: str | Path, meta: AssetMeta) -> Path:
    """由 build 脚本调用，写入 UTF-8 JSON。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def sync_meta_resolution(meta_path: str | Path,
                         png_path: str | Path | None = None,
                         requested: tuple[int, int] | None = None) -> bool:
    """把 meta.resolution 对齐到最终 PNG 的实际尺寸。

    build 脚本里的分辨率只是构建时的默认值；CLI / Scene Spec 可以在渲染时覆盖它，
    因此渲染完成后必须回写 meta，否则 summary 和下游会把 1600x1200 当成实际尺寸。
    优先读 PNG 真实尺寸（Pillow），读不到时退回请求的分辨率。meta 缺失就跳过。
    """
    p = Path(meta_path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    size = requested
    if png_path is not None:
        try:
            from PIL import Image
            with Image.open(png_path) as img:
                size = img.size
        except Exception:
            pass
    if not size:
        return False
    data["resolution"] = [int(size[0]), int(size[1])]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def load_meta(path: str | Path) -> AssetMeta:
    p = Path(path)
    if not p.is_file():
        raise MetaError(f"缺少 meta.json: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MetaError(f"meta.json 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MetaError("meta.json 顶层必须是对象")

    known = {"asset_id", "resolution", "ortho_scale_mm", "transparent",
             "target_width_mm", "blender_version"}
    resolution = data.get("resolution")
    if resolution is not None:
        if (not isinstance(resolution, (list, tuple)) or len(resolution) != 2
                or not all(isinstance(v, int) and v > 0 for v in resolution)):
            raise MetaError("meta.resolution 必须是两个正整数")

    transparent = data.get("transparent", False)
    if not isinstance(transparent, bool):
        raise MetaError("meta.transparent 必须是布尔值")

    target = data.get("target_width_mm")
    if target is not None and (not isinstance(target, (int, float)) or target <= 0):
        raise MetaError("meta.target_width_mm 必须为正数")

    return AssetMeta(
        asset_id=str(data.get("asset_id", "")),
        resolution=tuple(resolution) if resolution else None,
        ortho_scale_mm=data.get("ortho_scale_mm"),
        transparent=transparent,
        target_width_mm=float(target) if target is not None else None,
        blender_version=str(data.get("blender_version", "")),
        extra={k: v for k, v in data.items() if k not in known},
    )


def check_alpha(png_path: str | Path) -> tuple[bool | None, str]:
    """检查 PNG 是否真的带透明通道。

    返回 (是否带透明像素, 说明)。None 表示无法判断（缺 Pillow 或读图失败）。
    """
    try:
        from PIL import Image
    except ImportError:
        return None, "未安装 Pillow，跳过 alpha 检查"
    try:
        with Image.open(png_path) as img:
            if img.mode not in ("RGBA", "LA"):
                return False, f"颜色模式为 {img.mode}，无 alpha 通道"
            alpha = img.getchannel("A")
            low, high = alpha.getextrema()
            if high == 0:
                return False, "图像全透明"
            if low == 255:
                return False, "alpha 全为 255（实际不透明）"
            return True, f"alpha 范围 {low}-{high}"
    except Exception as exc:  # 读图失败不应让整条流水线崩掉
        return None, f"读取图片失败: {exc}"
