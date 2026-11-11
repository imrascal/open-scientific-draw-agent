# SPDX-License-Identifier: GPL-3.0-or-later
"""SVG 合规与完整性检查：画布尺寸、字号、线宽、文本、图片引用。"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from .svg import PT2MM, SVG_NS, XLINK_NS


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_mm(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("mm"):
        return float(text[:-2])
    if text.endswith("px"):
        return float(text[:-2]) * 25.4 / 96.0
    if text.endswith("pt"):
        return float(text[:-2]) * PT2MM
    try:
        return float(text)
    except ValueError:
        return None


def verify_svg(path: str | Path, *, expected_size_mm: tuple[float, float] | None = None,
               min_font_pt: float = 7.0, min_stroke_pt: float = 0.5,
               tolerance_mm: float = 0.2) -> dict:
    svg = Path(path)
    tree = etree.parse(str(svg))
    root = tree.getroot()

    errors: list[str] = []
    warnings: list[str] = []

    width = _to_mm(root.get("width"))
    height = _to_mm(root.get("height"))
    if width is None or height is None:
        errors.append("缺少以物理单位声明的 width/height（如 85mm）")
    if expected_size_mm and width is not None and height is not None:
        for name, got, want in (("宽", width, expected_size_mm[0]),
                                ("高", height, expected_size_mm[1])):
            if abs(got - want) > tolerance_mm:
                errors.append(f"画布{name}度 {got:.2f}mm 与预期 {want:.2f}mm 不符")

    texts: list[str] = []
    font_sizes_pt: list[float] = []
    stroke_pts: list[float] = []
    ids: list[str] = []
    missing_images: list[str] = []

    for el in root.iter():
        if not isinstance(el.tag, str):  # 跳过注释/处理指令
            continue
        name = _local(el.tag)
        if el.get("id"):
            ids.append(el.get("id"))

        if name == "text":
            texts.append("".join(el.itertext()).strip())
            raw = el.get("font-size")
            size_mm = _to_mm(raw)
            if size_mm is not None:
                font_sizes_pt.append(size_mm / PT2MM)
            else:
                warnings.append("存在未声明 font-size 的 text")

        if name in ("rect", "circle", "line", "polygon", "path"):
            stroke = el.get("stroke")
            if stroke and stroke != "none":
                raw = el.get("stroke-width", "1")
                sw_mm = _to_mm(raw)
                if sw_mm is not None:
                    stroke_pts.append(sw_mm / PT2MM)
                else:
                    warnings.append(f"无法解析 stroke-width: {raw!r}")

        if name == "image":
            href = el.get(f"{{{XLINK_NS}}}href") or el.get("href")
            if href and href.startswith("file://"):
                ref = Path(_uri_to_path(href))
                if not ref.is_file():
                    missing_images.append(str(ref))

    if any(t == "" for t in texts):
        warnings.append("存在空文本节点")
    if font_sizes_pt and min(font_sizes_pt) < min_font_pt - 1e-3:
        errors.append(f"最小字号 {min(font_sizes_pt):.2f}pt < {min_font_pt}pt")
    if stroke_pts and min(stroke_pts) < min_stroke_pt - 1e-3:
        errors.append(f"最小线宽 {min(stroke_pts):.2f}pt < {min_stroke_pt}pt")
    if len(ids) != len(set(ids)):
        errors.append("存在重复的 id")
    if missing_images:
        errors.append("图片引用不存在: " + ", ".join(missing_images))

    return {
        "ok": not errors,
        "size_mm": [width, height],
        "texts": texts,
        "min_font_pt": min(font_sizes_pt) if font_sizes_pt else None,
        "min_stroke_pt": min(stroke_pts) if stroke_pts else None,
        "images_missing": missing_images,
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
    }


def check_text_present(path: str | Path, expected: list[str]) -> list[str]:
    """返回缺失的文本（按去空白后比较）。"""
    tree = etree.parse(str(path))
    found = []
    for el in tree.getroot().iter():
        if isinstance(el.tag, str) and _local(el.tag) == "text":
            found.append("".join(el.itertext()).strip())
    normalized = {_norm(t) for t in found}
    return [e for e in expected if _norm(e) not in normalized]


def _norm(text: str) -> str:
    return "".join(str(text).split())


def _uri_to_path(href: str) -> str:
    """file:///C:/a%20b.png -> C:/a b.png（跨平台处理百分号编码与盘符）。"""
    from urllib.parse import unquote

    raw = unquote(href[len("file://"):])
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    return raw


def check_png_dpi(path: str | Path) -> dict:
    """读取 PNG 的 pHYs 元数据。返回 dpi=None 表示文件没写 DPI。"""
    try:
        from PIL import Image
    except ImportError:
        return {"ok": None, "dpi": None, "detail": "未安装 Pillow"}
    try:
        with Image.open(path) as img:
            dpi = img.info.get("dpi")
        if not dpi:
            return {"ok": False, "dpi": None, "detail": "PNG 未写入 DPI 元数据"}
        return {"ok": True, "dpi": [round(float(dpi[0]), 1), round(float(dpi[1]), 1)],
                "detail": "pHYs"}
    except Exception as exc:
        return {"ok": None, "dpi": None, "detail": f"读取失败: {exc}"}


def check_pdf_fonts(path: str | Path) -> dict:
    """检查 PDF 是否嵌入字体（启发式：查找 /FontFile 系列键）。

    只做字节级检索，不解析对象树；对压缩对象流可能漏检，
    因此结果标注 heuristic=true，不作为唯一判据。
    """
    data = Path(path).read_bytes()
    markers = {name: data.count(name.encode()) for name in
               ("/FontFile", "/FontFile2", "/FontFile3")}
    total = sum(markers.values())
    has_font = b"/Font" in data
    return {
        "ok": total > 0 if has_font else None,
        "embedded": total > 0,
        "hits": markers,
        "heuristic": True,
    }


def convert_tiff(png_path: str | Path, tiff_path: str | Path, *,
                 dpi: int, color_mode: str = "RGB") -> Path:
    """PNG -> TIFF。CMYK 用于印刷，RGB 用于常规投稿。"""
    from PIL import Image

    src = Path(png_path)
    dst = Path(tiff_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        out = img.convert("CMYK" if color_mode.upper() == "CMYK" else "RGB")
        out.save(dst, "TIFF", compression="tiff_lzw", dpi=(dpi, dpi))
    return dst
