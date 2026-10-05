#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose.py 的行为测试（纯标准库，可直接运行，也可用 unittest 发现）。

    python scripts/test_diagnose.py
    python -m unittest discover -s scripts
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagnose  # noqa: E402


class TestParsing(unittest.TestCase):
    def test_parse_answers_basic(self):
        answers = diagnose.parse_answers("core_loop:match,controls:partial,pace:conflict")
        self.assertEqual(answers, {"core_loop": "match", "controls": "partial", "pace": "conflict"})

    def test_parse_answers_accepts_chinese_and_fullwidth(self):
        answers = diagnose.parse_answers("core_loop：匹配,challenge:冲突")
        self.assertEqual(answers["core_loop"], "match")
        self.assertEqual(answers["challenge"], "conflict")

    def test_parse_answers_accepts_fullwidth_separator(self):
        answers = diagnose.parse_answers("core_loop:match；challenge:partial")
        self.assertEqual(answers, {"core_loop": "match", "challenge": "partial"})

    def test_parse_answers_aliases(self):
        self.assertEqual(diagnose.parse_answers("core_loop:y")["core_loop"], "match")
        self.assertEqual(diagnose.parse_answers("core_loop:n")["core_loop"], "conflict")
        self.assertEqual(diagnose.parse_answers("core_loop:p")["core_loop"], "partial")

    def test_parse_answers_rejects_unknown_key(self):
        with self.assertRaises(diagnose.InputError):
            diagnose.parse_answers("nope:match")

    def test_parse_answers_rejects_bad_verdict(self):
        with self.assertRaises(diagnose.InputError):
            diagnose.parse_answers("core_loop:maybe-not")

    def test_parse_answers_rejects_missing_colon(self):
        with self.assertRaises(diagnose.InputError):
            diagnose.parse_answers("core_loop")


class TestCompute(unittest.TestCase):
    def test_high_fit(self):
        result = diagnose.compute({
            "core_loop": "match", "controls": "match", "pace": "match",
            "social": "match", "challenge": "partial", "content": "match",
        })
        self.assertEqual(result["level"], "high")
        self.assertEqual(result["percent"], 87.5)

    def test_values_conflict_forces_medium(self):
        result = diagnose.compute({
            "time_cost": "match", "hardware": "match", "payment": "match",
            "community": "match", "update": "match", "emotion": "match",
            "retention": "match", "values": "conflict",
        })
        self.assertEqual(result["percent"], 77.8)
        self.assertIn("values", result["critical_conflicts"])
        self.assertEqual(result["level"], "medium")

    def test_core_loop_conflict_blocks_high_fit(self):
        # 适配率 = 6/8 = 75% 且关键冲突 → 中适配
        result = diagnose.compute({
            "core_loop": "conflict", "controls": "match", "pace": "match",
            "social": "match", "challenge": "match", "content": "match",
            "immersion": "match", "time_budget": "match",
        })
        self.assertEqual(result["level"], "medium")

    def test_two_critical_conflicts_is_low(self):
        result = diagnose.compute({
            "core_loop": "conflict", "challenge": "conflict", "values": "conflict",
            "controls": "match", "pace": "match", "social": "match",
        })
        self.assertEqual(result["level"], "low")
        self.assertEqual(len(result["critical_conflicts"]), 3)

    def test_ratio_below_55_is_low(self):
        result = diagnose.compute({
            "core_loop": "partial", "challenge": "conflict", "values": "partial",
            "controls": "conflict", "pace": "conflict", "social": "partial",
        })
        # earned = 2*0.5 + 0 + 2*0.5 + 0 + 0 + 0.5 = 2.5 / 7 = 35.7%
        self.assertLess(result["percent"], 55)
        self.assertEqual(result["level"], "low")

    def test_three_noncritical_conflicts_downgrade_high(self):
        # 适配率 = 9/12 = 75%？否：8 个维度中 3 个冲突，得分 6/8 = 75% → 中适配；
        # 这里验证的是"无关键冲突但冲突数 >= 3"时不会判为高适配。
        result = diagnose.compute({
            "core_loop": "match", "challenge": "match", "immersion": "match",
            "time_budget": "match", "controls": "conflict", "pace": "conflict",
            "social": "conflict", "content": "match",
        })
        # earned = 2 + 2 + 1 + 1 + 1 = 7 / 10 = 70%
        self.assertEqual(result["percent"], 70.0)
        self.assertEqual(result["critical_conflicts"], [])
        self.assertEqual(result["level"], "medium")

    def test_high_ratio_with_three_noncritical_conflicts_downgrades(self):
        # 16 维中 3 个非关键冲突：eraned = 16 / 19 = 84.2% ≥ 80%，
        # 但因非关键冲突 >= 3，强制降为中适配（防止"高分掩盖多处摩擦"）。
        result = diagnose.compute({
            "core_loop": "match", "challenge": "match", "values": "match",
            "controls": "conflict", "pace": "conflict", "social": "conflict",
            "content": "match", "immersion": "match", "time_budget": "match",
            "time_cost": "match", "hardware": "match", "payment": "match",
            "community": "match", "update": "match", "emotion": "match",
            "retention": "match",
        })
        self.assertEqual(result["percent"], 84.2)
        self.assertEqual(result["critical_conflicts"], [])
        self.assertEqual(result["level"], "medium")

    def test_skip_is_excluded_from_denominator(self):
        result = diagnose.compute({"core_loop": "match", "controls": "skip", "pace": "match"})
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["skipped"], ["controls"])
        self.assertEqual(result["level"], "high")

    def test_all_skipped_raises(self):
        with self.assertRaises(diagnose.InputError):
            diagnose.compute({"core_loop": "skip"})

    def test_weight_override(self):
        base = diagnose.compute({"core_loop": "conflict", "controls": "match"})
        self.assertEqual(base["total"], 3)
        overridden = diagnose.compute({"core_loop": "conflict", "controls": "match"},
                                     weights={"controls": 5})
        self.assertEqual(overridden["total"], 7)


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.result = diagnose.compute({
            "core_loop": "match", "challenge": "conflict", "controls": "partial",
        })

    def test_rank_risks_puts_conflict_first(self):
        risks = diagnose.rank_risks(self.result)
        self.assertTrue(risks[0].startswith("挑战类型"))
        self.assertIn("关键维度", risks[0])

    def test_render_text_contains_verdict_and_disclaimer(self):
        text = diagnose.render_text("测试游戏", 1, self.result)
        self.assertIn("结论：", text)
        self.assertIn("以上基于用户自述的偏好", text)
        self.assertIn("测试游戏", text)

    def test_render_markdown_table_shape(self):
        markdown = diagnose.render_markdown("测试游戏", None, self.result)
        self.assertIn("| 维度 | 权重 | 判定 | 得分 |", markdown)
        self.assertIn("**结论：", markdown)

    def test_display_width_pads_cjk(self):
        self.assertEqual(diagnose.display_width("维度"), 4)
        self.assertEqual(diagnose.display_width("abc"), 3)
        self.assertEqual(diagnose.pad("维度", 6), "维度  ")
        self.assertEqual(diagnose.pad("abcdefgh", 6), "abcdefgh")

    def test_list_questions_lists_all_dimensions(self):
        listing = diagnose.list_questions(1)
        for key in diagnose.QUESTION_ORDER[1]:
            self.assertIn(key, listing)
        self.assertNotIn("hardware", listing)


class TestCli(unittest.TestCase):
    def test_non_interactive_without_answers_errors(self):
        with self.assertRaises(SystemExit) as context:
            diagnose.main(["--game", "x", "--non-interactive"])
        self.assertEqual(context.exception.code, 2)

    def test_answers_mode_returns_zero(self):
        code = diagnose.main(["--game", "x", "--answers", "core_loop:match", "--non-interactive"])
        self.assertEqual(code, 0)

    def test_bad_answers_return_one(self):
        code = diagnose.main(["--game", "x", "--answers", "core_loop:nope", "--non-interactive"])
        self.assertEqual(code, 1)

    def test_list_questions_returns_zero(self):
        self.assertEqual(diagnose.main(["--list-questions"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
