# SPDX-License-Identifier: GPL-3.0-or-later
"""命令行入口：探测 -> 构建 -> 渲染 -> 元数据校验 -> 可选审核 -> summary.json。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .backends import (RenderError, build_scene, log, render_local, render_mock,
                       render_server, resolve_blender, server_status)
from .config import Config, ConfigError, load_config
from .judge import Criteria, judge_review
from .meta import AssetMeta, MetaError, check_alpha, load_meta, write_meta
from .naming import parse_resolution
from .review import review_image

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_RENDER = 3
EXIT_REVIEW = 4
EXIT_META = 5


def _configure_console() -> None:
    """Windows 控制台默认不是 UTF-8，中文日志会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    _configure_console()
    ap = argparse.ArgumentParser(
        prog="osda-render",
        description="OSDA 的 Blender 渲染桥接：.blend / build.py -> PNG -> 可选视觉审核",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--script", help="Blender Python 构建脚本")
    src.add_argument("--blend", help="已有 .blend，跳过构建")

    ap.add_argument("--renderer", choices=("auto", "server", "local", "mock"),
                    default="auto", help="渲染后端；auto=服务器可用则用，否则本地")
    ap.add_argument("--config", help="配置文件路径（默认 ~/.config/osda/render.toml）")
    ap.add_argument("--outdir", help="输出目录（默认 outputs/pipeline_<时间戳>）")
    ap.add_argument("--resolution", help="分辨率 WxH；留空用场景设置")
    ap.add_argument("--samples", type=int, help="采样数；默认服务器 128 / 本地 32")
    ap.add_argument("--frames", default=None, help="帧：'1'、'1,5' 或 '1-240'")
    ap.add_argument("--reviewer", choices=("none", "glm", "mimo"),
                    help="视觉审核引擎；默认 none")
    ap.add_argument("--no-render", action="store_true", help="只准备场景，不渲染不审核")
    ap.add_argument("--require-meta", action="store_true", help="缺少 meta.json 即失败")
    ap.add_argument("--version", action="version", version=__version__)
    return ap.parse_args(argv)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _select_renderer(args, cfg: Config) -> tuple[str, dict, list[str]]:
    """返回 (最终后端, 服务器状态, 警告列表)。降级必须可见。"""
    warnings: list[str] = []
    status = {"available": False, "reason": "未探测", "gpu_util": -1, "render_running": False}

    if args.renderer == "mock":
        return "mock", status, warnings
    if args.renderer == "local":
        return "local", status, warnings

    status = server_status(cfg)
    if status["available"]:
        return "server", status, warnings

    if args.renderer == "server":
        warnings.append(f"指定了 server 但不可用（{status['reason']}），已回退本地")
    else:
        warnings.append(f"服务器不可用（{status['reason']}），使用本地渲染")
    return "local", status, warnings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"FAIL 配置错误: {exc}")
        return EXIT_CONFIG

    if args.samples is not None:
        cfg.render.samples_server = args.samples
        cfg.render.samples_local = args.samples
    if args.frames is not None:
        cfg.render.frames = args.frames
    if args.reviewer is not None:
        cfg.review.provider = args.reviewer
    if args.require_meta:
        cfg.render.require_meta = True

    try:
        resolution = parse_resolution(args.resolution) if args.resolution else None
    except ValueError as exc:
        print(f"FAIL {exc}")
        return EXIT_CONFIG

    job_dir = (Path(args.outdir) if args.outdir else (
        Path.cwd() / "outputs" / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}")).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    iter_dir = job_dir / "iter_01"
    iter_dir.mkdir(parents=True, exist_ok=True)

    renderer, status, warnings = _select_renderer(args, cfg)
    summary: dict = {
        "osda_render_version": __version__,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "input": {"mode": "blend" if args.blend else "script",
                  "path": str(Path(args.blend or args.script).resolve())},        "renderer_requested": args.renderer,
        "renderer_used": renderer,
        "server": status,
        "warnings": warnings,
        "review": {"provider": cfg.review.provider},
        "verdict": None,
        "outputs": {},
    }
    for w in warnings:
        log("MAIN", f"WARN {w}")

    # ---- 准备场景 ----
    blend_path: Path
    try:
        if args.blend:
            src = Path(args.blend)
            if not src.is_file():
                raise RenderError(f".blend 不存在: {src}")
            blend_path = iter_dir / "scene.blend"
            shutil.copy2(src, blend_path)
            log("MAIN", f"已复制 {src.name}")
        elif renderer == "mock":
            # mock 不构建场景，直接跳过，保证无 Blender 环境可跑
            blend_path = iter_dir / "scene.blend"
            log("MOCK", "跳过场景构建")
        else:
            blender = resolve_blender(cfg.render.blender)
            blend_path = build_scene(blender, args.script, iter_dir,
                                     cfg.render.build_timeout_s)
    except RenderError as exc:
        print(f"FAIL {exc}")
        _write_json(job_dir / "summary.json", {**summary, "error": str(exc)})
        return EXIT_RENDER

    if args.no_render:
        _write_json(job_dir / "summary.json", {**summary, "renderer_used": "none"})
        print(f"\n  仅准备完成: {blend_path}\n  输出目录: {job_dir}")
        return EXIT_OK

    # ---- 渲染 ----
    try:
        if renderer == "mock":
            png = render_mock(iter_dir, resolution)
            meta = AssetMeta(asset_id=job_dir.name, resolution=resolution or (800, 600),
                             transparent=True, target_width_mm=None)
            write_meta(iter_dir / "meta.json", meta)
        elif renderer == "server":
            samples = cfg.render.samples_server
            png = render_server(cfg, blend_path, iter_dir, samples, resolution,
                                cfg.render.frames)
        else:
            samples = cfg.render.samples_local
            png = render_local(cfg, blend_path, iter_dir, samples, resolution,
                               cfg.render.frames, blender=resolve_blender(cfg.render.blender)
                               if cfg.render.blender else None)
    except RenderError as exc:
        print(f"FAIL {exc}")
        _write_json(job_dir / "summary.json", {**summary, "error": str(exc)})
        return EXIT_RENDER

    summary["outputs"]["image"] = str(png)
    summary["renderer_used"] = renderer

    # ---- meta / alpha ----
    meta_path = iter_dir / "meta.json"
    meta: AssetMeta | None = None
    if meta_path.is_file():
        try:
            meta = load_meta(meta_path)
        except MetaError as exc:
            print(f"FAIL {exc}")
            _write_json(job_dir / "summary.json", {**summary, "error": str(exc)})
            return EXIT_META
    elif cfg.render.require_meta:
        msg = f"缺少 meta.json（{meta_path}），无法回填矢量版面"
        print(f"FAIL {msg}")
        _write_json(job_dir / "summary.json", {**summary, "error": msg})
        return EXIT_META

    if meta is not None:
        summary["meta"] = meta.to_json()
        if meta.transparent:
            has_alpha, detail = check_alpha(png)
            summary["alpha"] = {"ok": has_alpha, "detail": detail}
            if has_alpha is False:
                msg = f"声明透明但实际不透明：{detail}"
                print(f"FAIL {msg}")
                _write_json(job_dir / "summary.json", {**summary, "error": msg})
                return EXIT_META

    # ---- 审核（可选）----
    verdict = None
    if cfg.review.provider != "none":
        review = review_image(cfg, png)
        if review is None:
            print("FAIL 审核未获得结果")
            _write_json(job_dir / "summary.json", {**summary, "error": "review failed"})
            return EXIT_REVIEW
        _write_json(iter_dir / "review.json", review)

        criteria = Criteria(
            overall_min=cfg.review.overall_min,
            dim_min=cfg.review.dim_min,
            dim_floor=cfg.review.dim_floor,
            veto_keywords=cfg.review.veto_keywords or Criteria().veto_keywords,
        )
        verdict = judge_review(review, criteria)

        if not verdict.passed and cfg.review.auto_retry and renderer in ("local", "server"):
            log("MAIN", "审核未通过，重渲一次（采样翻倍）")
            retry_dir = job_dir / "iter_02"
            retry_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(blend_path, retry_dir / "scene.blend")
            try:
                if renderer == "server":
                    png = render_server(cfg, retry_dir / "scene.blend", retry_dir,
                                        cfg.render.samples_server * 2, resolution,
                                        cfg.render.frames)
                else:
                    png = render_local(cfg, retry_dir / "scene.blend", retry_dir,
                                       cfg.render.samples_local * 2, resolution,
                                       cfg.render.frames)
                summary["outputs"]["image"] = str(png)
                retry_review = review_image(cfg, png)
                if retry_review:
                    _write_json(retry_dir / "review.json", retry_review)
                    verdict = judge_review(retry_review, criteria)
            except RenderError as exc:
                warnings.append(f"重渲失败: {exc}")

        summary["verdict"] = {
            "passed": verdict.passed,
            "scores": verdict.scores,
            "hard_fail": verdict.hard_fail,
            "reasons": verdict.reasons,
        }

    _write_json(job_dir / "summary.json", summary)

    print("\n" + "=" * 58)
    print(f"  后端: {summary['renderer_used']} | 产物: {png.name}")
    if verdict is not None:
        print(f"  审核: {'PASS' if verdict.passed else 'FAIL'} "
              f"| overall={verdict.scores.get('overall', 0):g}")
        for reason in verdict.reasons + verdict.hard_fail:
            print(f"    - {reason}")
    print(f"  输出目录: {job_dir}")
    print("=" * 58)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
