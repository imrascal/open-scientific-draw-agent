# SPDX-License-Identifier: GPL-3.0-or-later
"""示例：2x2 多图排版（双栏 180 mm）。

组合内容：
  (a)(b) matplotlib 数据图（SVG 矢量，Arial 7pt）
  (c)    本仓库矢量层画的器件截面
  (d)    Blender 渲染位图（带透明背景）

运行：
    python examples/fig_panel.py --asset3d <render_0001.png> --outdir outputs/fig_panel
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples import fig_stack
from osda_vector import Canvas, export, verify_svg
from osda_vector.svg import SVG_NS

W, H = 180.0, 130.0
COL_W, ROW_H = 80.0, 56.0
X1, X2 = 8.0, 92.0
Y1, Y2 = 8.0, 68.0

PALETTE = ["#2867A0", "#C9A227", "#3C8D5A"]


def _style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial"],
        "font.size": 7,
        "axes.labelsize": 7,
        "axes.titlesize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "legend.frameon": False,
        "axes.linewidth": 0.5,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "xtick.major.size": 2,
        "ytick.major.size": 2,
        "lines.linewidth": 0.9,
        "svg.fonttype": "none",
        "figure.dpi": 100,
    })


def _transfer_svg(path: Path) -> None:
    vg = np.linspace(-20, 20, 161)
    on = 1e-9 + 1e-7 / (1 + np.exp(-(vg - 2) / 2.2))
    off = 1e-12 + 2e-13 * np.exp(vg / 9.0)

    fig, ax = plt.subplots(figsize=(COL_W / 25.4, 50 / 25.4))
    ax.semilogy(vg, on, color=PALETTE[0], label="forward")
    ax.semilogy(vg, off, color=PALETTE[0], ls="--", label="reverse")
    ax.set_xlabel("$V_{g}$ (V)")
    ax.set_ylabel("$I_{d}$ (A)")
    ax.set_xlim(-20, 20)
    ax.legend(loc="center right")
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.18, top=0.95)
    fig.savefig(path, format="svg")
    plt.close(fig)


def _output_svg(path: Path) -> None:
    vd = np.linspace(0, 2, 101)
    fig, ax = plt.subplots(figsize=(COL_W / 25.4, 50 / 25.4))
    for i, vg in enumerate((-10, 0, 10)):
        ids = 2e-6 * vd / (1 + vd / 1.6) * (1 + 0.25 * i)
        ax.plot(vd, ids * 1e6, color=PALETTE[i], label=f"$V_g$ = {vg} V")
    ax.set_xlabel("$V_{d}$ (V)")
    ax.set_ylabel("$I_{d}$ (µA/µm)")
    ax.set_xlim(0, 2)
    ax.legend(loc="lower right")
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.18, top=0.95)
    fig.savefig(path, format="svg")
    plt.close(fig)


def _namespace_ids(group, prefix: str) -> None:
    """给嵌入子图的 id 加前缀，避免两幅 matplotlib 图的 id 冲突。"""
    ids: dict[str, str] = {}
    for el in group.iter():
        if not isinstance(el.tag, str):
            continue
        old = el.get("id")
        if old:
            new = prefix + old
            ids[old] = new
            el.set("id", new)
    if not ids:
        return
    for el in group.iter():
        if not isinstance(el.tag, str):
            continue
        for attr, value in list(el.attrib.items()):
            if "url(#" in value or (value.startswith("#") and len(value) > 1):
                for old, new in ids.items():
                    value = value.replace(f"url(#{old})", f"url(#{new})")
                    if value == f"#{old}":
                        value = f"#{new}"
                el.set(attr, value)


def _place_svg(canvas: Canvas, svg_path: Path, x: float, y: float,
               box_w: float, box_h: float, prefix: str = "") -> float:
    root = etree.parse(str(svg_path)).getroot()
    vb = root.get("viewBox")
    if vb:
        vx, vy, vw, vh = (float(v) for v in vb.replace(",", " ").split())
    else:
        vw = float(root.get("width", "100").rstrip("pt"))
        vh = float(root.get("height", "100").rstrip("pt"))
        vx = vy = 0.0
    scale = min(box_w / vw, box_h / vh)
    transform = (f"translate({x:g},{y:g}) scale({scale:.6f}) "
                 f"translate({-vx:g},{-vy:g})")
    group = etree.SubElement(canvas.layer, f"{{{SVG_NS}}}g", {"transform": transform})
    for child in root:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "metadata":
            continue
        if tag == "rect" and child.get("id") == "page":
            continue
        group.append(copy.deepcopy(child))
    if prefix:
        _namespace_ids(group, prefix)
    return scale


def build(asset3d: Path, workdir: Path) -> Canvas:
    _style()
    transfer = workdir / "panel_a.svg"
    output = workdir / "panel_b.svg"
    _transfer_svg(transfer)
    _output_svg(output)

    schematic = fig_stack.build().save(workdir / "panel_c.svg")

    c = Canvas(W, H)
    _place_svg(c, transfer, X1, Y1, COL_W, 50, prefix="a_")
    _place_svg(c, output, X2, Y1, COL_W, 50, prefix="b_")
    _place_svg(c, schematic, X1, Y2, COL_W, ROW_H, prefix="c_")

    img_w = ROW_H * 4 / 3
    c.image(asset3d, X2 + (COL_W - img_w) / 2, Y2, img_w, ROW_H, embed=True)

    for letter, x, y in (("a", X1, Y1 - 1.6), ("b", X2, Y1 - 1.6),
                         ("c", X1, Y2 - 1.6), ("d", X2, Y2 - 1.6)):
        c.text(x, y, letter, size_pt=9, weight="bold")
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset3d", required=True, help="3D 渲染出的 render_0001.png")
    ap.add_argument("--outdir", default="outputs/fig_panel")
    ap.add_argument("--dpi", type=int, default=600)
    args = ap.parse_args()

    asset = Path(args.asset3d)
    if not asset.is_file():
        print(f"FAIL 3D 素材不存在: {asset}")
        return 2

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        canvas = build(asset, Path(tmp))
        svg = canvas.save(out / "fig_panel.svg")
    files = export(svg, out, formats=("pdf", "png"), dpi=args.dpi)
    # 嵌入式子图的字号受外层缩放影响，这里只查画布/文本/图片引用
    report = verify_svg(svg, expected_size_mm=(W, H), min_font_pt=0, min_stroke_pt=0)

    print(json.dumps({**report, "files": {k: str(v) for k, v in files.items()}},
                     ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
