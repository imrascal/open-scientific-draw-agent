# SPDX-License-Identifier: GPL-3.0-or-later
"""OSDA 矢量层：按毫米坐标生成 SVG，经 Inkscape 导出 PDF/PNG 并自检。"""

__version__ = "0.2.0"

from .export import ExportError, export, find_inkscape
from .svg import Canvas
from .verify import check_text_present, verify_svg

__all__ = ["Canvas", "export", "find_inkscape", "ExportError",
           "verify_svg", "check_text_present"]
