# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene Spec -> SVG/PDF/PNG/TIFF，含后端路由、资源解析与合规校验。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from osda_render import backends
from osda_render.config import load_config
from osda_render.meta import MetaError, load_meta
from osda_vector import Canvas, export, verify_svg
from osda_vector.compose import place_svg
from osda_vector.export import convert_to_svg
from osda_vector.verify import (check_pdf_fonts, check_png_dpi, check_text_present,
                                convert_tiff)

from .layout import apply_layout
from .spec import ordered_elements, resolve_backend, SpecError

DEFAULT_TEXT_PT = 7.0


def _plot_svg(el: dict[str, Any], base: Path, workdir: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    csv_path = (base / el["csv"]).resolve() if not Path(el["csv"]).is_absolute() else Path(el["csv"])
    xs: list[float] = []
    ys: list[float] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or el["x"] not in reader.fieldnames or el["y"] not in reader.fieldnames:
            raise SpecError(f"data_plot {el['id']}: CSV 缺少列 {el['x']}/{el['y']}")
        for row in reader:
            try:
                xs.append(float(row[el["x"]]))
                ys.append(float(row[el["y"]]))
            except (TypeError, ValueError):
                continue

    width = float(el["w_mm"])
    height = float(el.get("h_mm", width * 0.62))
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial"],
        "font.size": 7,
        "axes.labelsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "axes.linewidth": 0.5,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "xtick.major.size": 2,
        "ytick.major.size": 2,
        "lines.linewidth": 0.9,
        "svg.fonttype": "none",
    })
    fig, ax = plt.subplots(figsize=(width / 25.4, height / 25.4))
    color = el.get("color", "#2867A0")
    kind = el.get("kind", "line")
    if kind == "scatter":
        ax.scatter(xs, ys, s=6, color=color)
    elif kind == "bar":
        ax.bar(xs, ys, width=(max(xs) - min(xs)) / max(len(xs), 1) * 0.6 if len(xs) > 1 else 0.6,
               color=color)
    else:
        ax.plot(xs, ys, color=color)
    if el.get("log_y"):
        ax.set_yscale("log")
    if el.get("xlabel"):
        ax.set_xlabel(el["xlabel"])
    if el.get("ylabel"):
        ax.set_ylabel(el["ylabel"])
    fig.subplots_adjust(left=0.18, right=0.97, bottom=0.2, top=0.95)
    out = workdir / "plots" / f"{el['id']}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg")
    plt.close(fig)
    return out


def _blender_png(el: dict[str, Any], base: Path, workdir: Path,
                 renderer_override: str | None) -> tuple[Path, float | None]:
    asset_dir = (base / el["asset_dir"]).resolve()
    build = asset_dir / el.get("build", "build.py")
    if not build.is_file():
        raise SpecError(f"blender_asset {el['id']}: 找不到构建脚本 {build}")

    outdir = workdir / "assets" / el["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    resolution = tuple(el.get("resolution", [1600, 1200]))
    renderer = renderer_override or el.get("renderer", "auto")
    cfg = load_config()

    try:
        if renderer == "mock":
            png = backends.render_mock(outdir, resolution)
        else:
            blender = backends.resolve_blender(cfg.render.blender)
            blend = backends.build_scene(blender, str(build), outdir,
                                         cfg.render.build_timeout_s)
            if renderer == "auto":
                status = backends.server_status(cfg)
                renderer = "server" if status["available"] else "local"
            samples = el.get("samples") or (
                cfg.render.samples_server if renderer == "server" else cfg.render.samples_local)
            if renderer == "server":
                png = backends.render_server(cfg, blend, outdir, samples,
                                             resolution, "1")
            else:
                png = backends.render_local(cfg, blend, outdir, samples,
                                            resolution, "1", blender=blender)
    except backends.RenderError as exc:
        raise SpecError(f"blender_asset {el['id']} 渲染失败: {exc}") from exc

    width = el.get("w_mm")
    meta_path = outdir / "meta.json"
    if meta_path.is_file():
        try:
            meta = load_meta(meta_path)
            # spec 里给了物理宽度就以 spec 为准；meta 只作为缺省建议
            if width is None and meta.target_width_mm:
                width = meta.target_width_mm
        except MetaError:
            pass
    return png, width


def _panel_source(el: dict[str, Any], base: Path, workdir: Path) -> Path:
    src = Path(el["src"])
    src = src if src.is_absolute() else (base / src)
    if not src.is_file():
        raise SpecError(f"panel {el['id']}: 文件不存在 {src}")
    if src.suffix.lower() in (".pdf", ".eps", ".ps", ".emf", ".wmf"):
        target = workdir / "panels" / f"{el['id']}.svg"
        return convert_to_svg(src, target)
    return src


def prepare_elements(spec: dict[str, Any], workdir: Path,
                     renderer_override: str | None = None) -> list[dict[str, Any]]:
    """把 data_plot / blender_asset / PDF panel 解析成可直接绘制的 SVG 或 PNG。"""
    base = Path(spec.get("_base", "."))
    resolved: list[dict[str, Any]] = []
    for el in ordered_elements(spec):
        kind = el["type"]
        if kind == "data_plot":
            svg = _plot_svg(el, base, workdir)
            resolved.append({**el, "type": "panel", "src": str(svg)})
        elif kind == "blender_asset":
            png, width = _blender_png(el, base, workdir, renderer_override)
            resolved.append({**el, "type": "image", "src": str(png),
                             "w_mm": width or el["w_mm"], "embed": True})
        elif kind == "panel":
            resolved.append({**el, "src": str(_panel_source(el, base, workdir))})
        else:
            resolved.append(el)
    return resolved


def build_canvas(spec: dict[str, Any], elements: list[dict[str, Any]],
                 limit: int | None = None,
                 font_family: str | None = None) -> Canvas:
    from lxml import etree

    from osda_vector.svg import SVG_NS

    canvas = Canvas(spec["canvas"]["width_mm"], spec["canvas"]["height_mm"],
                    font_family=font_family or spec["journal"]["font_family"])
    drawn = elements if limit is None else elements[:limit]
    for i, el in enumerate(drawn):
        # 每个元素包一层 g，便于 progressive 与 swarm 按元素动画
        group = etree.SubElement(canvas.layer, f"{{{SVG_NS}}}g",
                                 {"id": f"el_{el['id']}"})
        outer = canvas.layer
        canvas.layer = group
        try:
            _draw(canvas, el, prefix=f"e{i}_")
        finally:
            canvas.layer = outer
    return canvas


def _draw(canvas: Canvas, el: dict[str, Any], prefix: str) -> None:
    kind = el["type"]
    if kind == "rect":
        canvas.rect(el["x_mm"], el["y_mm"], el["w_mm"], el["h_mm"],
                    fill=el.get("fill", "#FFFFFF"), stroke=el.get("stroke", "none"),
                    stroke_pt=el.get("stroke_pt", 0.5), rx=el.get("rx", 0),
                    opacity=el.get("opacity", 1.0), element_id=prefix + el["id"])
    elif kind == "circle":
        canvas.circle(el["cx_mm"], el["cy_mm"], el["r_mm"],
                      fill=el.get("fill", "#FFFFFF"), stroke=el.get("stroke", "none"),
                      stroke_pt=el.get("stroke_pt", 0.5))
    elif kind == "line":
        canvas.line(el["x1_mm"], el["y1_mm"], el["x2_mm"], el["y2_mm"],
                    stroke=el.get("stroke", "#000000"),
                    stroke_pt=el.get("stroke_pt", 0.75),
                    dash=el.get("dash"))
    elif kind == "arrow":
        if "cx_mm" in el and "cy_mm" in el:
            canvas.curve_arrow(el["x1_mm"], el["y1_mm"], el["cx_mm"], el["cy_mm"],
                               el["x2_mm"], el["y2_mm"],
                               stroke=el.get("stroke", "#000000"),
                               stroke_pt=el.get("stroke_pt", 0.75))
        else:
            canvas.line(el["x1_mm"], el["y1_mm"], el["x2_mm"], el["y2_mm"],
                        stroke=el.get("stroke", "#000000"),
                        stroke_pt=el.get("stroke_pt", 0.75),
                        dash=el.get("dash"), arrow=True)
    elif kind == "path":
        canvas.path(el["d"], fill=el.get("fill", "none"),
                    stroke=el.get("stroke", "#000000"),
                    stroke_pt=el.get("stroke_pt", 0.75), dash=el.get("dash"))
    elif kind == "text":
        size = el.get("size_pt", DEFAULT_TEXT_PT)
        canvas.text(el["x_mm"], el["y_mm"], el.get("content", ""),
                    size_pt=size, fill=el.get("fill", "#000000"),
                    anchor=el.get("anchor", "start"),
                    weight=el.get("weight", "normal"),
                    runs=el.get("runs"), element_id=prefix + el["id"])
    elif kind == "image":
        canvas.image(el["src"], el["x_mm"], el["y_mm"], el["w_mm"],
                     el.get("h_mm"), embed=el.get("embed", False))
    elif kind == "panel":
        place_svg(canvas, el["src"], el["x_mm"], el["y_mm"],
                  el["w_mm"], el.get("h_mm"), prefix=prefix + el["id"] + "_")
    else:
        raise SpecError(f"未知或未解析的元素类型: {kind}")

    if el.get("label") and kind in ("panel", "image"):
        size = el.get("label_pt", DEFAULT_TEXT_PT + 1)
        top = float(el.get("y_mm", 0))
        # 太靠近上边缘时把标签放进面板内，避免被裁切
        above = top > size * 0.5 + 2.0
        canvas.text(float(el.get("x_mm", 0)),
                    top - 1.2 if above else top + size * 0.4 + 0.8,
                    el["label"], size_pt=size, weight="bold")


def _element_text(el: dict[str, Any]) -> str:
    if el.get("runs"):
        return "".join(str(run.get("t", "")) for run in el["runs"])
    return str(el.get("content", ""))


def render_scene(spec: dict[str, Any], outdir: str | Path, *,
                 workdir: str | Path | None = None,
                 renderer_override: str | None = None,
                 formats: tuple[str, ...] | None = None,
                 dpi: int | None = None,
                 color_mode: str | None = None,
                 elements: list[dict[str, Any]] | None = None) -> dict:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(workdir) if workdir else out / "_work"
    work.mkdir(parents=True, exist_ok=True)

    apply_layout(spec)
    if elements is None:
        elements = prepare_elements(spec, work, renderer_override)
    canvas = build_canvas(spec, elements)

    name = spec.get("name", "figure")
    svg = canvas.save(out / f"{name}.svg")

    dpi = dpi or spec["output"].get("dpi", 600)
    color_mode = color_mode or spec["output"].get("color_mode", "RGB")
    fmts = list(formats or spec["output"].get("formats", ["pdf", "png"]))
    vector_fmts = tuple(f for f in fmts if f in ("pdf", "png", "svg"))
    files = export(svg, out, formats=vector_fmts, dpi=dpi) if vector_fmts else {"svg": svg}

    if "tiff" in fmts:
        png = files.get("png") or export(svg, out, formats=("png",), dpi=dpi)["png"]
        files["tiff"] = convert_tiff(png, out / f"{name}.tiff", dpi=dpi,
                                     color_mode=color_mode)

    report = verify_svg(svg,
                        expected_size_mm=(spec["canvas"]["width_mm"],
                                          spec["canvas"]["height_mm"]),
                        min_font_pt=spec["journal"]["min_font_pt"],
                        min_stroke_pt=spec["journal"]["min_stroke_pt"])
    checks: dict[str, Any] = {}
    if spec["output"].get("verify_text", True):
        expected = [_element_text(el) for el in elements if el["type"] == "text"]
        expected = [t for t in expected if t]
        missing = check_text_present(svg, expected) if expected else []
        checks["text_missing"] = missing
        if missing:
            report["errors"].append("以下文本在输出中缺失: " + ", ".join(missing))
            report["ok"] = False
    if "png" in files:
        checks["png_dpi"] = check_png_dpi(files["png"])
        if checks["png_dpi"].get("dpi") and checks["png_dpi"]["dpi"][0] < dpi - 1:
            report["errors"].append(
                f"PNG DPI {checks['png_dpi']['dpi'][0]} 低于要求 {dpi}")
            report["ok"] = False
    if "pdf" in files:
        checks["pdf_fonts"] = check_pdf_fonts(files["pdf"])
        if checks["pdf_fonts"].get("ok") is False:
            report["warnings"].append("PDF 中未检测到嵌入字体（启发式判断）")

    return {
        "ok": report["ok"],
        "backend": resolve_backend(spec),
        "name": name,
        "files": {k: str(v) for k, v in files.items()},
        "report": report,
        "checks": checks,
    }
