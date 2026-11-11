# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_render.judge import DEFAULT_VETO_KEYWORDS, Criteria, judge_review


def _review(scores: dict, passed: bool = True, issues=None) -> dict:
    return {"scores": scores, "pass": passed, "issues": issues or [], "suggestions": []}


GOOD = {"science": 9, "composition": 8, "material": 8, "layout_text": 8, "overall": 9}


class TestJudge(unittest.TestCase):
    def test_pass(self):
        verdict = judge_review(_review(GOOD), Criteria())
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.hard_fail, [])

    def test_low_overall(self):
        scores = dict(GOOD, overall=7)
        verdict = judge_review(_review(scores), Criteria())
        self.assertFalse(verdict.passed)
        self.assertTrue(any("综合分" in r for r in verdict.reasons))

    def test_dim_below_floor(self):
        scores = dict(GOOD, material=3)
        verdict = judge_review(_review(scores), Criteria())
        self.assertFalse(verdict.passed)
        self.assertTrue(any("下限" in r for r in verdict.reasons))

    def test_veto_keyword(self):
        verdict = judge_review(_review(GOOD, issues=["右下角出现水印"]), Criteria())
        self.assertFalse(verdict.passed)
        self.assertTrue(verdict.hard_fail)

    def test_text_mention_is_not_a_hard_fail(self):
        """'文字' 过宽，不能作为一票否决词。"""
        self.assertNotIn("文字", DEFAULT_VETO_KEYWORDS)
        verdict = judge_review(_review(GOOD, passed=False, issues=["文字可以再大一点"]),
                               Criteria())
        self.assertEqual(verdict.hard_fail, [])

    def test_model_self_contradiction(self):
        verdict = judge_review(_review(GOOD, passed=True, issues=["主体偏左"]), Criteria())
        self.assertFalse(verdict.passed)
        self.assertTrue(any("自相矛盾" in r for r in verdict.reasons))

    def test_empty_result(self):
        verdict = judge_review(None, Criteria())
        self.assertFalse(verdict.passed)

    def test_zero_scores(self):
        zeros = {k: 0 for k in ("science", "composition", "material", "layout_text", "overall")}
        verdict = judge_review(_review(zeros), Criteria())
        self.assertFalse(verdict.passed)
        self.assertTrue(verdict.hard_fail)


if __name__ == "__main__":
    unittest.main()
