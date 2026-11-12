# SPDX-License-Identifier: GPL-3.0-or-later
"""OSDA Scene Spec：JSON 声明式绘图、布局、progressive、swarm。"""

__version__ = "0.3.0"

from .progressive import run_progressive
from .render import build_canvas, prepare_elements, render_scene
from .spec import SpecError, load_spec, ordered_elements, resolve_backend
from .swarm import build_swarm_html

__all__ = ["load_spec", "render_scene", "prepare_elements", "build_canvas",
           "run_progressive", "build_swarm_html", "ordered_elements",
           "resolve_backend", "SpecError"]

