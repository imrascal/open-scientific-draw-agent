# SPDX-License-Identifier: GPL-3.0-or-later
"""Inkscape 导出封装。

两个必须记住的坑（实测）：
1. 必须调用 inkscape.com，而不是 inkscape.exe——后者是 GUI 子系统进程，
   会把参数投递给已有实例后立刻返回 0，产物根本不生成；
2. 路径必须逐个作为独立参数传入，不要拼字符串，否则含空格的路径会被拆开。
"""

from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

DEFAULT_HINTS = (
    r"C:\Program Files\Inkscape\bin\inkscape.com",
    r"C:\Applications\Inkscape\bin\inkscape.com",
)


class ExportError(RuntimeError):
    pass


def find_inkscape(explicit: str = "") -> str:
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise ExportError(f"Inkscape 不存在: {explicit}")
    found = shutil.which("inkscape.com") or shutil.which("inkscape")
    if found:
        return found
    for hint in DEFAULT_HINTS:
        if Path(hint).is_file():
            return hint
    raise ExportError("找不到 Inkscape，请设置 OSDA_INKSCAPE 或把 inkscape.com 加入 PATH")


def convert_to_svg(src: str | Path, target: str | Path,
                   inkscape: str = "") -> Path:
    """PDF/EPS/EMF 等矢量格式转 SVG（Origin 导出常用 PDF/EPS）。"""
    exe = find_inkscape(inkscape)
    source = Path(src)
    out = Path(target)
    if not source.is_file():
        raise ExportError(f"源文件不存在: {source}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    proc = subprocess.run(
        [exe, str(source), "--export-type=svg", f"--export-filename={out}"],
        capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file():
        raise ExportError(
            f"转 SVG 失败（exit {proc.returncode}）\n"
            + (proc.stderr or proc.stdout or "")[-800:])
    return out


def export(svg_path: str | Path, out_dir: str | Path,
           formats: tuple[str, ...] = ("pdf", "png"),
           dpi: int = 600, inkscape: str = "") -> dict[str, Path]:
    """把 SVG 导出为 PDF/PNG，并用"退出码 + 文件存在"双重判定。"""
    exe = find_inkscape(inkscape)
    svg = Path(svg_path)
    if not svg.is_file():
        raise ExportError(f"SVG 不存在: {svg}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path] = {}
    for fmt in formats:
        target = out / f"{svg.stem}.{fmt}"
        target.unlink(missing_ok=True)
        cmd = [exe, str(svg), "--export-area-page", "--export-type", fmt,
               f"--export-filename={target}"]
        if fmt == "png":
            cmd.insert(3, f"--export-dpi={dpi}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not target.is_file():
            raise ExportError(
                f"导出 {fmt} 失败（exit {proc.returncode}）\n"
                + (proc.stderr or proc.stdout or "")[-800:]
            )
        results[fmt] = target
    return results
