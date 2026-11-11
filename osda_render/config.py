# SPDX-License-Identifier: GPL-3.0-or-later
"""配置加载：默认值 < 配置文件 < 环境变量 < 命令行参数。

原则：任何凭据都没有默认值。缺失即报错，不静默使用别人的账号。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "osda" / "render.toml"

# 允许的审核服务商。none = 不审核（默认）。
PROVIDERS = ("none", "glm", "mimo")


class ConfigError(ValueError):
    """配置缺失或非法。"""


@dataclass
class ServerConfig:
    enabled: bool = False
    host: str = ""
    user: str = ""
    password: str = ""
    key_file: str = ""
    gpu_idle_max_util: float = 5.0
    docker_image: str = "blender-gpu"
    remote_work: str = "/data/blender/work"


@dataclass
class RenderConfig:
    blender: str = ""
    samples_server: int = 128
    samples_local: int = 32
    device: str = "optix"
    local_threads: int = 0
    build_timeout_s: int = 300
    timeout_server_s: int = 3600
    timeout_local_s: int = 900
    frames: str = "1"
    require_meta: bool = False


@dataclass
class ReviewConfig:
    provider: str = "none"
    glm_model: str = "glm-4.6v"
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    mimo_model: str = "mimo-v2.5"
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    max_image_px: int = 2048
    overall_min: float = 8.0
    dim_min: float = 6.0
    dim_floor: float = 4.0
    auto_retry: bool = True
    veto_keywords: tuple[str, ...] = ()


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)


def _coerce(field_type: str, value: Any) -> Any:
    """按 dataclass 字段类型做最小转换，避免 tomllib 与字符串 env 类型错位。"""
    if field_type is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if field_type is int:
        return int(value)
    if field_type is float:
        return float(value)
    if field_type is str:
        return str(value)
    return value


_SIMPLE_TYPES = {"bool": bool, "int": int, "float": float, "str": str}


def _apply_section(obj: Any, data: dict[str, Any], section: str) -> None:
    allowed = {f.name: f.type for f in fields(obj)}
    for key, value in data.items():
        if key not in allowed:
            raise ConfigError(f"配置项 [{section}].{key} 不存在")
        # dataclass + `from __future__ import annotations` 下 f.type 是字符串
        ftype = _SIMPLE_TYPES.get(str(allowed[key]))
        if ftype is not None:
            setattr(obj, key, _coerce(ftype, value))
        elif key == "veto_keywords":
            if not isinstance(value, list):
                raise ConfigError("[review].veto_keywords 必须是字符串数组")
            obj.veto_keywords = tuple(str(v) for v in value)
        else:
            raise ConfigError(f"配置项 [{section}].{key} 类型不受支持")


def load_config(path: str | Path | None = None) -> Config:
    """加载配置。文件不存在时使用默认值（不报错）。"""
    cfg = Config()
    candidate = Path(path) if path else DEFAULT_CONFIG_PATH
    if path and not candidate.is_file():
        raise ConfigError(f"配置文件不存在: {candidate}")
    if candidate.is_file():
        with open(candidate, "rb") as f:
            data = tomllib.load(f)
        for section, obj in (
            ("server", cfg.server),
            ("render", cfg.render),
            ("review", cfg.review),
        ):
            if section in data:
                if not isinstance(data[section], dict):
                    raise ConfigError(f"[{section}] 必须是表")
                _apply_section(obj, data[section], section)
    _apply_env(cfg)
    return cfg


_ENV_FIELDS = (
    ("OSDA_SERVER_ENABLED", "server", "enabled", bool),
    ("OSDA_SERVER_HOST", "server", "host", str),
    ("OSDA_SERVER_USER", "server", "user", str),
    ("OSDA_SERVER_PASSWORD", "server", "password", str),
    ("OSDA_SSH_KEY", "server", "key_file", str),
    ("OSDA_GPU_IDLE_MAX_UTIL", "server", "gpu_idle_max_util", float),
    ("OSDA_DOCKER_IMAGE", "server", "docker_image", str),
    ("OSDA_REMOTE_WORK", "server", "remote_work", str),
    ("OSDA_BLENDER", "render", "blender", str),
    ("OSDA_SAMPLES_SERVER", "render", "samples_server", int),
    ("OSDA_SAMPLES_LOCAL", "render", "samples_local", int),
    ("OSDA_BUILD_TIMEOUT", "render", "build_timeout_s", int),
    ("OSDA_TIMEOUT_SERVER", "render", "timeout_server_s", int),
    ("OSDA_TIMEOUT_LOCAL", "render", "timeout_local_s", int),
    ("OSDA_LOCAL_THREADS", "render", "local_threads", int),
    ("OSDA_REQUIRE_META", "render", "require_meta", bool),
    ("OSDA_REVIEWER", "review", "provider", str),
    ("OSDA_REVIEW_AUTO_RETRY", "review", "auto_retry", bool),
)


def _apply_env(cfg: Config) -> None:
    for env_name, section, attr, ftype in _ENV_FIELDS:
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        target = getattr(cfg, section)
        setattr(target, attr, _coerce(ftype, raw))


def require_server_credentials(cfg: Config) -> None:
    """服务器模式必须显式提供连接信息，缺一即报错。"""
    missing = [k for k, v in (
        ("host", cfg.server.host),
        ("user", cfg.server.user),
    ) if not v]
    if not cfg.server.password and not cfg.server.key_file:
        missing.append("password 或 key_file")
    if missing:
        raise ConfigError(
            "服务器模式缺少配置: " + ", ".join(missing)
            + "。请设置 OSDA_SERVER_HOST / OSDA_SERVER_USER / "
              "OSDA_SERVER_PASSWORD 或 OSDA_SSH_KEY，或改用 --renderer local/mock"
        )


def require_review_credentials(cfg: Config) -> tuple[str, str]:
    """返回 (api_key, base_url)。缺失即报错，绝不内置默认 key。"""
    if cfg.review.provider == "glm":
        key = os.environ.get("GLM_API_KEY", "")
        if not key:
            raise ConfigError("审核引擎 glm 需要环境变量 GLM_API_KEY")
        return key, cfg.review.glm_base_url
    if cfg.review.provider == "mimo":
        key = os.environ.get("MIMO_API_KEY", "")
        if not key:
            raise ConfigError("审核引擎 mimo 需要环境变量 MIMO_API_KEY")
        return key, cfg.review.mimo_base_url
    raise ConfigError(f"未知审核引擎: {cfg.review.provider}")
