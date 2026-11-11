# SPDX-License-Identifier: GPL-3.0-or-later
"""命令行：python -m osda_scene --spec scene.json"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .layout import apply_layout
from .progressive import run_progressive
from .render import prepare_elements, render_scene
from .spec import SpecError, load_spec, resolve_backend
from .swarm import build_swarm_html

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_SPEC = 2
EXIT_RENDER = 3


def _configure_console() -> None:
    """Windows 控制台默认不是 UTF-8，中文日志会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    _configure_console()
    ap = argparse.ArgumentParser(prog="osda-scene",
                                 description="OSDA Scene Spec 渲染器")
    ap.add_argument("--spec", required=True, help="scene JSON")
    ap.add_argument("--outdir")
    ap.add_argument("--renderer", choices=("auto", "server", "local", "mock"),
                    help="3D 素材渲染后端（覆盖 spec 内设置）")
    ap.add_argument("--formats", help="逗号分隔：svg,pdf,png,tiff")
    ap.add_argument("--dpi", type=int)
    ap.add_argument("--color-mode", choices=("RGB", "CMYK"))
    ap.add_argument("--no-progressive", action="store_true")
    ap.add_argument("--no-swarm", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        spec = load_spec(args.spec)
    except SpecError as exc:
        print(f"FAIL {exc}")
        return EXIT_SPEC

    spec["_base"] = str(Path(args.spec).resolve().parent)
    apply_layout(spec)

    name = spec.get("name", "figure")
    out = Path(args.outdir) if args.outdir else Path(
        spec["output"].get("dir") or (Path.cwd() / "outputs" / name))
    out = out.resolve()
    work = out / "_work"

    formats = tuple(f.strip() for f in args.formats.split(",")) if args.formats else None
    try:
        elements = prepare_elements(spec, work, args.renderer)
        result = render_scene(spec, out, workdir=work, elements=elements,
                              formats=formats, dpi=args.dpi,
                              color_mode=args.color_mode)
    except SpecError as exc:
        print(f"FAIL {exc}")
        return EXIT_SPEC
    except Exception as exc:  # 渲染/导出阶段的失败统一为退出码 3
        print(f"FAIL 渲染失败: {type(exc).__name__}: {exc}")
        return EXIT_RENDER

    summary = {**result, "backend": resolve_backend(spec)}
    svg_path = out / f"{name}.svg"

    if spec["progressive"]["enabled"] and not args.no_progressive:
        summary["progressive"] = run_progressive(spec, out, workdir=work,
                                                 elements=elements)

    if spec["swarm"]["enabled"] and not args.no_swarm:
        summary["swarm"] = build_swarm_html(svg_path, spec, elements,
                                            out / f"{name}_swarm.html")

    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return EXIT_OK if result["ok"] else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
