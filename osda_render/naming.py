# SPDX-License-Identifier: GPL-3.0-or-later
"""命名与尺寸换算：所有后端共用一套产物命名，杜绝 preview_/frame_ 双标准。"""

from __future__ import annotations

from pathlib import Path

RENDER_PREFIX = "render_"
RENDER_GLOB = "render_*.png"


def parse_resolution(text: str) -> tuple[int, int]:
    """'1920x1080' -> (1920, 1080)。大小写不敏感。"""
    try:
        w, h = text.lower().split("x")
        width, height = int(w), int(h)
    except ValueError as exc:
        raise ValueError(f"分辨率格式应为 WxH，收到: {text!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"分辨率必须为正数: {text!r}")
    return width, height


def expand_frames(spec: str) -> str:
    """'1-3,7' -> '1,2,3,7'。单帧原样返回。"""
    parts: list[str] = []
    for chunk in str(spec).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            start, end = int(a), int(b)
            if end < start:
                raise ValueError(f"帧范围倒置: {chunk!r}")
            parts.extend(str(i) for i in range(start, end + 1))
        else:
            parts.append(str(int(chunk)))
    if not parts:
        raise ValueError("帧参数为空")
    return ",".join(parts)


def find_render_output(directory: str | Path) -> Path | None:
    """在目录里找渲染产物。只认统一命名，按文件名排序取第一张。"""
    files = sorted(Path(directory).glob(RENDER_GLOB))
    return files[0] if files else None


def mm_to_px(mm: float, dpi: int) -> int:
    """物理尺寸转像素：85 mm @ 600 dpi -> 2008 px。"""
    return int(round(mm / 25.4 * dpi))
