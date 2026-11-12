# SPDX-License-Identifier: GPL-3.0-or-later
"""示例：vdW 异质结器件截面（单栏 85 mm）。

运行：
    python examples/fig_stack.py --outdir outputs/fig_stack
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_vector import Canvas, export, verify_svg

W, H = 80.0, 56.0

COLORS = {
    "si": "#D8D8D8",
    "sio2": "#F2F2F2",
    "hbn": "#C9D6E8",
    "mos2": "#4A90D9",
    "wse2": "#E8C547",
    "au": "#C9A227",
    "edge": "#333333",
}


def build() -> Canvas:
    c = Canvas(W, H)

    # --- 堆叠结构（x 向右，y 向下）---
    c.rect(8, 42, 47, 9, fill=COLORS["si"], stroke=COLORS["edge"], stroke_pt=0.75,
           element_id="si_substrate")
    c.rect(8, 37, 47, 5, fill=COLORS["sio2"], stroke=COLORS["edge"], stroke_pt=0.5,
           element_id="sio2")
    c.rect(14, 34, 33, 3, fill=COLORS["hbn"], stroke=COLORS["edge"], stroke_pt=0.5,
           element_id="hbn_bottom")
    c.rect(17, 31.5, 26, 2.5, fill=COLORS["mos2"], stroke="#2C5F8A", stroke_pt=0.5,
           element_id="mos2")
    c.rect(21, 29, 18, 2.5, fill=COLORS["wse2"], stroke="#B8960F", stroke_pt=0.5,
           element_id="wse2")
    c.rect(24, 26.5, 12, 2.5, fill=COLORS["hbn"], stroke=COLORS["edge"], stroke_pt=0.5,
           element_id="hbn_top")

    # --- 电极：轮廓沿 WSe2/MoS2/底部 hBN 的台阶共形贴合 ---
    # 电极只与各层侧壁接触，不覆盖任何二维材料的顶面；底部落在 SiO2（y=37）。
    c.polygon([(8, 29), (21, 29), (21, 31.5), (17, 31.5),
               (17, 34), (14, 34), (14, 37), (8, 37)],
              fill=COLORS["au"], stroke="#8A6D12", stroke_pt=0.5,
              element_id="source")
    c.polygon([(39, 29), (52, 29), (52, 37), (47, 37),
               (47, 34), (43, 34), (43, 31.5), (39, 31.5)],
              fill=COLORS["au"], stroke="#8A6D12", stroke_pt=0.5,
              element_id="drain")

    # --- 引导线与标签（斜引导线，避免 2.5 mm 层厚导致标签挤在一起）---
    labels = [
        ("hbn_top", 27.75, 26.5, [{"t": "hBN"}]),
        ("wse2", 30.25, 30.0, [{"t": "WSe"}, {"t": "2", "sub": True}]),
        ("mos2", 32.75, 33.5, [{"t": "MoS"}, {"t": "2", "sub": True}]),
        ("hbn_bottom", 35.5, 37.0, [{"t": "hBN"}]),
        ("sio2", 39.5, 40.5, [{"t": "SiO"}, {"t": "2", "sub": True}]),
        ("si_substrate", 46.5, 47.5, [{"t": "Si substrate"}]),
    ]
    for _, y_from, y_label, runs in labels:
        c.line(56, y_from, 62, y_label, stroke="#666666", stroke_pt=0.5)
        c.text(63, y_label + 0.9, "", size_pt=7, runs=runs)

    # 电极标签直接放在色块里，避开叠层与右侧引线
    c.text(9.4, 35.2, "Au", size_pt=7, fill="#FFFFFF", weight="bold")
    c.text(48.0, 35.2, "Au", size_pt=7, fill="#FFFFFF", weight="bold")

    # 不再标注 "vdW gap"：电极与二维叠层之间是直接接触，
    # 真正的范德华界面是层间界面，在截面里不适合用一条斜箭头笼统表示。

    # --- 面板内标题 ---
    c.text(8, 10, "vdW heterostructure FET", size_pt=8, weight="bold")
    c.text(8, 15, "cross-section, not to scale", size_pt=7, fill="#555555")

    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="outputs/fig_stack")
    ap.add_argument("--dpi", type=int, default=600)
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    svg = build().save(out / "fig_stack.svg")
    files = export(svg, out, formats=("pdf", "png"), dpi=args.dpi)
    report = verify_svg(svg, expected_size_mm=(W, H), min_font_pt=7, min_stroke_pt=0.5)

    print(json.dumps({**report, "files": {k: str(v) for k, v in files.items()}},
                     ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
