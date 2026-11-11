# SPDX-License-Identifier: GPL-3.0-or-later
"""Progressive：按绘制顺序逐元素出帧，再合成 GIF。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from osda_vector import export

from .render import build_canvas, prepare_elements


def run_progressive(spec: dict[str, Any], outdir: str | Path, *,
                    workdir: str | Path | None = None,
                    renderer_override: str | None = None,
                    elements: list[dict[str, Any]] | None = None) -> dict:
    out = Path(outdir)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    work = Path(workdir) if workdir else out / "_work"
    work.mkdir(parents=True, exist_ok=True)

    if elements is None:
        elements = prepare_elements(spec, work, renderer_override)
    step = max(1, int(spec["progressive"]["step"]))
    hold = max(50, int(spec["progressive"]["hold_ms"]))
    dpi = int(spec["progressive"].get("dpi", 200))

    limits = list(range(step, len(elements) + 1, step))
    if not limits or limits[-1] != len(elements):
        limits.append(len(elements))

    frames: list[Path] = []
    for idx, limit in enumerate(limits, start=1):
        canvas = build_canvas(spec, elements, limit=limit)
        svg = canvas.save(frames_dir / f"frame_{idx:03d}.svg")
        png = export(svg, frames_dir, formats=("png",), dpi=dpi)["png"]
        frames.append(png)

    # 最后一帧同时作为矢量成品
    final_svg = (out / f"{spec.get('name', 'figure')}.svg")
    final_svg.write_bytes((frames_dir / f"frame_{len(frames):03d}.svg").read_bytes())

    gif_path = None
    if spec["progressive"].get("gif", True) and len(frames) > 1:
        gif_path = make_gif(frames, out / f"{spec.get('name', 'figure')}_build.gif", hold)
    return {"frames": len(frames), "gif": str(gif_path) if gif_path else None,
            "svg": str(final_svg), "dpi": dpi}


def make_gif(frames: list[Path], target: str | Path, hold_ms: int) -> Path:
    from PIL import Image

    images = []
    for frame in frames:
        with Image.open(frame) as img:
            images.append(img.convert("RGB").copy())
    if not images:
        raise ValueError("没有可用于合成 GIF 的帧")
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(dst, "GIF", save_all=True, append_images=images[1:],
                   duration=hold_ms, loop=0, optimize=True)
    return dst
