# SPDX-License-Identifier: GPL-3.0-or-later
"""三种渲染后端：局域网服务器 / 本地 Blender / mock。

设计要点：
- mock 是默认可用的降级路径：没有 Blender、没有 GPU、没有服务器也能跑通全流程；
- 服务器不可用时**不静默**，由调用方把降级原因写进 summary.json；
- paramiko / PIL 均为惰性导入，只有真的用到该后端时才要求安装。
"""

from __future__ import annotations

import glob
import os
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import Config, RenderConfig, ServerConfig, require_server_credentials
from .naming import RENDER_PREFIX, expand_frames, parse_resolution


class RenderError(RuntimeError):
    """渲染或场景构建失败。"""


def log(step: str, msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] [{step}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Blender 定位
# ---------------------------------------------------------------------------

_WINDOWS_HINTS = (
    r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
    r"C:\Applications\Blender*\blender.exe",
)


def resolve_blender(explicit: str = "") -> str:
    """优先级：显式参数 / OSDA_BLENDER -> PATH -> 常见安装目录。"""
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise RenderError(f"指定的 Blender 不存在: {explicit}")

    found = shutil.which("blender")
    if found:
        return found

    for pattern in _WINDOWS_HINTS:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]

    raise RenderError(
        "找不到 Blender。请设置 OSDA_BLENDER 环境变量或把 blender 加入 PATH；"
        "只想验证流程可加 --renderer mock。"
    )


# ---------------------------------------------------------------------------
# 场景构建
# ---------------------------------------------------------------------------

def build_scene(blender: str, script: str, out_dir: str | Path, timeout: int) -> Path:
    """运行 build 脚本；约定脚本必须把 scene.blend 写进 out_dir。"""
    script_path = Path(script)
    if not script_path.is_file():
        raise RenderError(f"构建脚本不存在: {script_path}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cmd = [blender, "--background", "--python-exit-code", "3",
           "--python", str(script_path), "--", str(out)]
    log("BUILD", f"构建场景: {script_path.name}（超时 {timeout}s）")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"场景构建超时（>{timeout}s），请精简 build 脚本或调大 timeout") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RenderError(f"场景构建失败（exit {proc.returncode}）:\n{tail}")

    target = out / "scene.blend"
    if target.is_file():
        log("BUILD", f"完成，耗时 {time.time() - t0:.1f}s")
        return target
    blends = sorted(out.glob("*.blend"))
    if not blends:
        raise RenderError("构建脚本未生成 .blend 文件（应在输出目录保存 scene.blend）")
    if len(blends) > 1:
        raise RenderError(
            "输出目录存在多个 .blend，无法确定产物："
            + ", ".join(p.name for p in blends)
            + "。请只保存 scene.blend。"
        )
    log("BUILD", f"完成（发现 {blends[0].name}），耗时 {time.time() - t0:.1f}s")
    return blends[0]


# ---------------------------------------------------------------------------
# 服务器后端
# ---------------------------------------------------------------------------

def _ssh_client(cfg: Config):
    try:
        import paramiko
    except ImportError as exc:
        raise RenderError("服务器模式需要 paramiko：pip install paramiko") from exc

    require_server_credentials(cfg)
    s = cfg.server
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"hostname": s.host, "username": s.user, "timeout": 15}
    if s.key_file:
        kwargs["key_filename"] = os.path.expanduser(s.key_file)
        if s.password:
            kwargs["passphrase"] = s.password
    else:
        kwargs["password"] = s.password
    client.connect(**kwargs)
    return client


def server_status(cfg: Config) -> dict:
    """探测服务器是否空闲。任何异常都转成不可用，不抛出。"""
    if not cfg.server.enabled:
        return {"available": False, "reason": "未启用服务器（server.enabled=false）",
                "gpu_util": -1, "render_running": False}
    try:
        client = _ssh_client(cfg)
    except Exception as exc:
        return {"available": False, "reason": f"SSH 连接失败: {exc}",
                "gpu_util": -1, "render_running": False}
    try:
        _, out, _ = client.exec_command(
            f"docker ps --filter ancestor={shlex.quote(cfg.server.docker_image)} --format '{{{{.Names}}}}'",
            timeout=15)
        render_running = bool(out.read().decode().strip())

        _, out, err = client.exec_command(
            "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits", timeout=15)
        raw = out.read().decode().strip()
        err_text = err.read().decode().strip()
        if err_text:
            return {"available": False, "reason": f"nvidia-smi 错误: {err_text}",
                    "gpu_util": -1, "render_running": render_running}

        utils: list[float] = []
        for line in raw.splitlines():
            try:
                utils.append(float(line.strip()))
            except ValueError:
                utils.append(100.0)
        avg = sum(utils) / len(utils) if utils else 0.0

        if render_running:
            return {"available": False, "reason": "服务器有渲染任务在跑",
                    "gpu_util": avg, "render_running": True}
        if avg >= cfg.server.gpu_idle_max_util:
            return {"available": False,
                    "reason": f"GPU 利用率 {avg:.1f}% 超过阈值 {cfg.server.gpu_idle_max_util:.1f}%",
                    "gpu_util": avg, "render_running": False}
        return {"available": True, "reason": f"GPU 空闲 (util={avg:.1f}%)",
                "gpu_util": avg, "render_running": False}
    except Exception as exc:
        return {"available": False, "reason": f"探测失败: {exc}",
                "gpu_util": -1, "render_running": False}
    finally:
        client.close()


def render_server(cfg: Config, blend_path: str | Path, out_dir: str | Path,
                  samples: int, resolution: tuple[int, int] | None,
                  frames: str) -> Path:
    s = cfg.server
    client = _ssh_client(cfg)
    sftp = None
    job_name = f"osda_{datetime.now():%Y%m%d_%H%M%S}"
    remote_job = f"{s.remote_work.rstrip('/')}/jobs/{job_name}"
    remote_input, remote_output = f"{remote_job}/input", f"{remote_job}/output"
    container_input = f"/work/jobs/{job_name}/input"
    container_output = f"/work/jobs/{job_name}/output"

    try:
        sftp = client.open_sftp()
        _, out, err = client.exec_command(f"mkdir -p {shlex.quote(remote_input)} {shlex.quote(remote_output)}",
                                          timeout=15)
        out.read()
        mk_err = err.read().decode().strip()
        if mk_err:
            log("SERVER", f"WARN mkdir: {mk_err}")

        scene_name = Path(blend_path).name
        log("SERVER", f"上传 {scene_name}")
        sftp.put(str(blend_path), f"{remote_input}/{scene_name}")

        expr = "import bpy; s=bpy.context.scene;"
        if samples:
            expr += f"s.cycles.samples={samples};"
        if resolution:
            expr += f"s.render.resolution_x={resolution[0]}; s.render.resolution_y={resolution[1]};"
        expr_arg = f"--python-expr {shlex.quote(expr)}"

        device = str(cfg.render.device).upper()
        gpu_args = "--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all" if device != "CPU" else ""
        cmd = (
            f"docker run --rm {gpu_args} -v {shlex.quote(s.remote_work)}:/work -w /work "
            f"{shlex.quote(s.docker_image)} "
            f"-b {shlex.quote(container_input + '/' + scene_name)} "
            f"-o {shlex.quote(container_output + '/' + RENDER_PREFIX)} "
            f"-F PNG {expr_arg} -f {expand_frames(frames)} "
            f"-- --cycles-device {device}"
        )
        log("SERVER", f"{device} 渲染（{samples} spp）")
        t0 = time.time()
        _, out, err = client.exec_command(cmd, timeout=cfg.render.timeout_server_s)
        out.read()
        err_text = err.read().decode()
        elapsed = time.time() - t0

        files: list[str] = []
        for _ in range(30):
            try:
                files = sorted(sftp.listdir(remote_output))
                if files:
                    break
            except OSError:
                pass
            time.sleep(1)
        if not files:
            raise RenderError("服务器输出目录为空\n" + err_text[-1000:])

        local_out = Path(out_dir)
        local_out.mkdir(parents=True, exist_ok=True)
        for name in files:
            sftp.get(f"{remote_output}/{name}", str(local_out / name))
        log("SERVER", f"完成，耗时 {elapsed:.1f}s")
        pngs = [n for n in files if n.endswith(".png")]
        if not pngs:
            raise RenderError("服务器未产出 PNG")
        return local_out / pngs[0]
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        try:
            client.exec_command(f"rm -rf {shlex.quote(remote_job)}", timeout=15)
        except Exception:
            pass
        client.close()


# ---------------------------------------------------------------------------
# 本地后端
# ---------------------------------------------------------------------------

def render_local(cfg: Config, blend_path: str | Path, out_dir: str | Path,
                 samples: int, resolution: tuple[int, int] | None,
                 frames: str, blender: str | None = None) -> Path:
    r = cfg.render
    exe = blender or resolve_blender(r.blender)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    cmd = [exe, "--background", "--engine", "CYCLES"]
    if r.local_threads > 0:
        cmd += ["--threads", str(r.local_threads)]
    cmd += [str(blend_path), "-o", str(out / RENDER_PREFIX), "-F", "PNG"]

    expr = "import bpy; s=bpy.context.scene;"
    if samples:
        expr += f"s.cycles.samples={samples};"
    if resolution:
        expr += f"s.render.resolution_x={resolution[0]}; s.render.resolution_y={resolution[1]};"
    if expr != "import bpy; s=bpy.context.scene;":
        # 必须放在 -f 之前：-f 一出现就会立刻触发渲染，之后的参数不再生效
        cmd += ["--python-expr", expr]
    cmd += ["-f", expand_frames(frames), "--", "--cycles-device", "CPU"]

    log("LOCAL", f"CPU 渲染（{samples} spp）")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=r.timeout_local_s)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"本地渲染超时（>{r.timeout_local_s}s）") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RenderError(f"本地渲染失败（exit {proc.returncode}）:\n{tail}")

    target = out / f"{RENDER_PREFIX}0001.png"
    if not target.is_file():
        candidates = sorted(out.glob("*.png"))
        if not candidates:
            raise RenderError("本地渲染结束但找不到 PNG")
        target = candidates[0]
    log("LOCAL", f"完成，耗时 {time.time() - t0:.1f}s")
    return target


# ---------------------------------------------------------------------------
# mock 后端
# ---------------------------------------------------------------------------

def render_mock(out_dir: str | Path, resolution: tuple[int, int] | None = None) -> Path:
    """不调用 Blender，生成一张带透明背景的占位图，用于跑通排版与 CI。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RenderError("mock 模式需要 Pillow：pip install Pillow") from exc

    width, height = resolution or (800, 600)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(4, width // 40)
    draw.rectangle([margin, margin, width - margin, height - margin],
                   outline=(120, 120, 120, 255), width=max(1, width // 400))
    draw.rectangle([width * 0.15, height * 0.45, width * 0.85, height * 0.75],
                   fill=(74, 144, 217, 220), outline=(44, 95, 138, 255))
    draw.rectangle([width * 0.25, height * 0.3, width * 0.75, height * 0.45],
                   fill=(232, 197, 71, 220), outline=(184, 150, 15, 255))
    draw.multiline_text((margin * 2, margin * 2),
                        f"MOCK {width}x{height}\nnot a real render",
                        fill=(60, 60, 60, 255))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{RENDER_PREFIX}0001.png"
    img.save(target, "PNG")
    log("MOCK", f"已生成占位图 {target.name}（未调用 Blender）")
    return target
