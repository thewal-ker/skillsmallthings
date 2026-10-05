#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_skill.py 的测试（纯标准库）。

重点覆盖一次真实事故：技能放在技能库仓库的子目录里时，
“目录名必须等于 name”会误判失败，导致 GitHub Actions 红叉。

    python scripts/test_validate_skill.py
    python -m unittest discover -s scripts
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import validate_skill  # noqa: E402

SKILL_MD = """---
name: demo-skill
description: 这是一个用于测试的技能，说明它做什么、什么时候使用，以及相关关键词，长度需要足够长以便通过校验。
license: MIT
---

# Demo

正文。
"""


def make_skill(parent: str, dirname: str, skill_md: str = SKILL_MD) -> str:
    """在 parent 下创建 dirname/ 目录并写入 SKILL.md，返回该技能目录。"""
    directory = os.path.join(parent, dirname)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write(skill_md)
    return directory


class TestFrontmatter(unittest.TestCase):
    def test_valid_frontmatter_parses(self):
        report = validate_skill.Report()
        data, body = validate_skill.parse_frontmatter(SKILL_MD, report)
        self.assertEqual(data["name"], "demo-skill")
        self.assertEqual(data["license"], "MIT")
        self.assertIn("# Demo", body)
        self.assertEqual(report.errors, [])

    def test_missing_frontmatter_is_error(self):
        report = validate_skill.Report()
        validate_skill.parse_frontmatter("# 没有 frontmatter\n", report)
        self.assertTrue(any("frontmatter" in message for message in report.errors))

    def test_unclosed_frontmatter_is_error(self):
        report = validate_skill.Report()
        validate_skill.parse_frontmatter("---\nname: demo-skill\n", report)
        self.assertTrue(any("未闭合" in message for message in report.errors))

    def test_uppercase_field_is_error(self):
        report = validate_skill.Report()
        validate_skill.parse_frontmatter("---\nName: demo-skill\n---\n正文\n", report)
        self.assertTrue(any("小写" in message for message in report.errors))

    def test_metadata_nested_mapping(self):
        text = ("---\nname: demo-skill\ndescription: 描述够长够长够长够长够长够长够长够长够长够长够长够长\n"
                "metadata:\n  author: someone\n  version: \"1.0.0\"\n---\n正文\n")
        report = validate_skill.Report()
        data, _ = validate_skill.parse_frontmatter(text, report)
        self.assertEqual(data["metadata"], {"author": "someone", "version": "1.0.0"})


class TestDirectoryNameRule(unittest.TestCase):
    """回归测试：技能库仓库（仓库根名 ≠ 技能名）的场景。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skill-val-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_matching_directory_passes(self):
        directory = make_skill(self.tmp, "demo-skill")
        report = validate_skill.validate(directory)
        self.assertEqual(report.errors, [])

    def test_mismatched_directory_is_error_by_default(self):
        # 对应线上事故：仓库根 skillsmallthings/ 里放 game-fit-advisor/
        directory = make_skill(self.tmp, "skillsmallthings")
        report = validate_skill.validate(directory)
        self.assertTrue(any("必须与所在目录名" in message for message in report.errors),
                        "目录名不一致时应报错，实际：%r" % report.errors)

    def test_library_repo_explicit_directory_is_strict(self):
        """显式传目录时必须严格校验目录名（曾因逻辑写反而漏检）。"""
        directory = make_skill(self.tmp, "skillsmallthings")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = validate_skill.main([directory])
        self.assertEqual(code, 1, "显式给出目录时，目录名不匹配应返回失败")

    def test_auto_discovery_finds_skill_subdirectory(self):
        """技能库仓库根运行（无参数）：应自动发现唯一的技能子目录。"""
        make_skill(self.tmp, "game-fit-advisor")
        found = validate_skill.find_skill_dir(self.tmp)
        self.assertEqual(found, os.path.join(self.tmp, "game-fit-advisor"))

    def test_auto_discovery_prefers_current_directory(self):
        with open(os.path.join(self.tmp, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write(SKILL_MD)
        self.assertEqual(validate_skill.find_skill_dir(self.tmp), self.tmp)

    def test_auto_discovery_returns_none_when_ambiguous(self):
        make_skill(self.tmp, "skill-a")
        make_skill(self.tmp, "skill-b")
        self.assertIsNone(validate_skill.find_skill_dir(self.tmp))

    def test_name_flag_skips_directory_check_and_passes(self):
        directory = make_skill(self.tmp, "skillsmallthings")
        report = validate_skill.validate(directory, check_name=False)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("已跳过目录名校验" in message for message in report.infos))

    def test_library_repo_root_skips_name_check(self):
        # 技能库仓库根：SKILL.md 在根、目录名不同 → 不带目录参数运行时按仓库模式放行
        with open(os.path.join(self.tmp, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write(SKILL_MD)
        report = validate_skill.validate(self.tmp, check_name=False)
        self.assertEqual(report.errors, [])

    def test_missing_recommended_files_are_warnings_not_errors(self):
        directory = make_skill(self.tmp, "demo-skill")
        report = validate_skill.validate(directory)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("缺少推荐文件" in message for message in report.warnings))


class TestNamePattern(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skill-val-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_invalid_name_is_error(self):
        text = SKILL_MD.replace("name: demo-skill", "name: Demo_Skill")
        directory = make_skill(self.tmp, "Demo_Skill", text)
        report = validate_skill.validate(directory)
        self.assertTrue(any("只允许小写字母" in message for message in report.errors))

    def test_long_description_is_error(self):
        text = SKILL_MD.replace("description: 这是一个用于测试的技能，说明它做什么、什么时候使用，以及相关关键词，长度需要足够长以便通过校验。",
                                "description: " + "长" * 1100)
        directory = make_skill(self.tmp, "demo-skill", text)
        report = validate_skill.validate(directory)
        self.assertTrue(any("description 超长" in message for message in report.errors))

    def test_missing_description_is_error(self):
        lines = [line for line in SKILL_MD.splitlines() if not line.startswith("description:")]
        directory = make_skill(self.tmp, "demo-skill", "\n".join(lines))
        report = validate_skill.validate(directory)
        self.assertTrue(any("description" in message for message in report.errors))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skill-val-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, argv):
        """运行 CLI 并吞掉它打印的报告，返回退出码。"""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            return validate_skill.main(argv)

    def test_cli_passes_with_name_flag(self):
        directory = make_skill(self.tmp, "skillsmallthings")
        self.assertEqual(self.run_cli([directory, "--name", "demo-skill", "--json"]), 0)

    def test_cli_fails_without_name_flag_on_mismatch(self):
        directory = make_skill(self.tmp, "skillsmallthings")
        self.assertEqual(self.run_cli([directory]), 1)

    def test_cli_without_directory_skips_name_check(self):
        # 模拟在技能库仓库根执行 `python scripts/validate_skill.py`（无参数）
        with open(os.path.join(self.tmp, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write(SKILL_MD)
        previous = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertEqual(self.run_cli([]), 0)
        finally:
            os.chdir(previous)

    def test_cli_rejects_invalid_name_argument(self):
        directory = make_skill(self.tmp, "skillsmallthings")
        self.assertEqual(self.run_cli([directory, "--name", "Bad_Name"]), 2)


class TestRealPackage(unittest.TestCase):
    """对本仓库真实技能包做一次端到端校验。"""

    def test_repo_skill_package_is_valid(self):
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        report = validate_skill.validate(package)
        self.assertEqual(report.errors, [], "技能包校验应无错误：%r" % report.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
