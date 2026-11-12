# SPDX-License-Identifier: GPL-3.0-or-later
"""审核判定：唯一入口，首次与重渲共用同一套规则。

刻意把"模型打分"和"程序判定"分开：
- 模型只负责给分和列问题；
- 是否通过由本模块按阈值和硬伤清单决定，不信任模型的 pass 字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 默认硬伤关键词。注意：不要用"文字"这种过宽的词——
# 模型正常建议"文字可以更大"也会被误杀。
DEFAULT_VETO_KEYWORDS: tuple[str, ...] = (
    "裁切", "截断", "空图", "全黑", "全白", "残影", "重复对象",
    "浮动平面", "水印", "UI 元素", "意外出现的文字", "穿透", "穿插",
)

DIMS = ("science", "composition", "material", "layout_text")


@dataclass
class Criteria:
    overall_min: float = 8.0
    dim_min: float = 6.0
    dim_floor: float = 4.0
    veto_keywords: tuple[str, ...] = DEFAULT_VETO_KEYWORDS


@dataclass
class Verdict:
    passed: bool
    scores: dict[str, float] = field(default_factory=dict)
    hard_fail: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def judge_review(review: dict | None, criteria: Criteria) -> Verdict:
    """把一次审核结果转成可执行结论。review 为 None 时判定为未通过。"""
    if not review:
        return Verdict(passed=False, reasons=["未获得审核结果"])

    raw_scores = review.get("scores") or {}
    scores = {name: _num(raw_scores.get(name)) for name in DIMS}
    overall = _num(raw_scores.get("overall"))
    issues = [str(i) for i in (review.get("issues") or [])]

    verdict = Verdict(passed=False, scores={**scores, "overall": overall})

    dims = list(scores.values())
    if overall <= 0.01 and all(v <= 0.01 for v in dims):
        verdict.hard_fail.append("空图或模型未给出有效评分")
        verdict.reasons.append("硬伤：无有效评分")
        return verdict

    issue_text = " ".join(issues)
    for kw in criteria.veto_keywords:
        if kw and kw in issue_text:
            verdict.hard_fail.append(f"命中硬伤关键词：{kw}")
            break

    if overall < criteria.overall_min:
        verdict.reasons.append(f"综合分 {overall:g} < {criteria.overall_min:g}")
    if dims and min(dims) < criteria.dim_min:
        verdict.reasons.append(f"最低维度 {min(dims):g} < {criteria.dim_min:g}")
    below_floor = [name for name, v in scores.items() if v < criteria.dim_floor]
    if below_floor:
        verdict.reasons.append("低于下限维度: " + ", ".join(below_floor))

    # 不信任模型的 pass 字段，但必须尊重 issues 非空这个事实：
    # REVIEW_PROMPT 里明确写了 issues 非空时 pass 必须为 false。
    # 这里即使分数全高，issues 非空也直接转成 reasons，不通过。
    if issues:
        verdict.reasons.append("模型报告了问题: " + "；".join(issues[:6])
                               + ("（仅列前 6 条）" if len(issues) > 6 else ""))
    if review.get("pass") is False:
        verdict.reasons.append("模型判定为未通过（pass=false）")

    verdict.passed = not verdict.hard_fail and not verdict.reasons
    return verdict
