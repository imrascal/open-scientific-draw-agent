# SPDX-License-Identifier: GPL-3.0-or-later
"""视觉审核调用（OpenAI 兼容 chat/completions 多模态接口）。

密钥只从环境变量读取，仓库内不存放任何默认值。
"""

from __future__ import annotations

import base64
import json
import re
import tempfile
import time
from pathlib import Path

from .config import Config, require_review_credentials

REVIEW_PROMPT = """\
你是科学可视化质量审核专家。
禁止描述图片内容，禁止分析过程，禁止多余文字。
只输出一个 JSON 对象，不要 markdown 代码块标记。

评分维度（0-10）：
- science: 科学信息是否清晰、结构是否可识别、关键特征是否准确
- composition: 构图与视角是否合理，是否展示了关键结构
- material: 材质与光照质量，有无过曝/死黑/材质失真
- layout_text: 标注与文字是否完整、位置是否合理、有无遮挡或溢出
- overall: 综合质量

【一票否决】出现以下任一情况，对应维度打 0 分且 pass=false：
- 空图、全黑、全白、无任何可辨识主体
- 主体或关键结构被画幅裁切
- 渲染错误：残影、重复对象、孤立浮动平面、穿插穿透
- 异常异物：意外出现的水印、UI 元素、背景网格

【pass 条件】
1. overall >= 8
2. science/composition/material/layout_text 的最小值 >= 6
3. 任一维度 < 4 直接失败
4. issues 非空时 pass 必须为 false

输出格式（仅 JSON）：
{"scores":{"science":0,"composition":0,"material":0,"layout_text":0,"overall":0},
 "pass":true,"issues":[],"suggestions":[]}"""

RETRY_STATUS = (429,)
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 30.0
MAX_ATTEMPTS = 3


def _encode_image(image_path: str | Path, max_px: int) -> str:
    """缩放后转 base64。缩放结果写临时目录，不污染渲染产物。"""
    from PIL import Image

    with Image.open(image_path) as img:
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        img.convert("RGBA").save(tmp_path, "PNG")
    try:
        return base64.b64encode(tmp_path.read_bytes()).decode("utf-8")
    finally:
        tmp_path.unlink(missing_ok=True)


def review_image(cfg: Config, image_path: str | Path) -> dict | None:
    """调用配置的审核引擎；失败返回 None（由上层决定是否中止）。"""
    provider = cfg.review.provider
    if provider == "none":
        return None
    api_key, base_url = require_review_credentials(cfg)

    try:
        import requests
    except ImportError:
        print("[REVIEW] FAIL 未安装 requests：pip install requests")
        return None

    model = cfg.review.glm_model if provider == "glm" else cfg.review.mimo_model
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{_encode_image(image_path, cfg.review.max_image_px)}"}},
                {"type": "text", "text": REVIEW_PROMPT},
            ],
        }],
        "temperature": 0.1,
        "max_tokens": 512,
    }
    if provider == "mimo":
        # MiMo 是推理模型，关闭思考否则 512 token 内出不了分
        payload["reasoning_effort"] = "none"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code in RETRY_STATUS or 500 <= resp.status_code < 600:
                delay = min(RETRY_BASE_DELAY * 2 ** (attempt - 1), RETRY_MAX_DELAY)
                print(f"[REVIEW] WARN HTTP {resp.status_code}，{delay:.0f}s 后重试 "
                      f"({attempt}/{MAX_ATTEMPTS})")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            print(f"[REVIEW] {provider} 返回，耗时 {time.time() - t0:.1f}s")
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                print("[REVIEW] FAIL 返回内容不含 JSON")
                return None
            return json.loads(match.group())
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            delay = min(RETRY_BASE_DELAY * 2 ** (attempt - 1), RETRY_MAX_DELAY)
            print(f"[REVIEW] WARN {type(exc).__name__}，{delay:.0f}s 后重试")
            time.sleep(delay)
        except Exception as exc:
            print(f"[REVIEW] FAIL 调用失败: {exc}")
            return None

    print(f"[REVIEW] FAIL 重试 {MAX_ATTEMPTS} 次仍失败")
    return None
