#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""precheck.py 与 commit_msg.py 的行为测试（纯标准库）。

    python scripts/test_precheck.py
    python -m unittest discover -s scripts
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import commit_msg  # noqa: E402
import precheck  # noqa: E402

SKILL_MD = """---
name: demo-skill
description: 演示技能。当用户需要测试发布前预检时使用，覆盖目录名规则、CI 路径可解析性与隐私检查等检查项。
license: MIT
---

# Demo

正文。
"""

README_GOOD = "# demo-skill\n\n" + "说明文字。" * 60 + "\n"

WORKFLOW_OK = """name: validate
on: [push]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Detect skill layout
        run: |
          if [ -f SKILL.md ]; then echo "SKILL_DIR=." >> "$GITHUB_ENV"
          else echo "SKILL_DIR=demo-skill" >> "$GITHUB_ENV"; fi
      - run: python "$SKILL_DIR/scripts/check.py"
"""

WORKFLOW_BAD_PATH = """name: validate
on: [push]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - run: python "other-skill/scripts/check.py"
"""


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def make_skill(parent: str, dirname: str = "demo-skill", skill_md: str = SKILL_MD,
               with_readme: bool = True, with_license: bool = True) -> str:
    directory = os.path.join(parent, dirname)
    write(os.path.join(directory, "SKILL.md"), skill_md)
    if with_readme:
        write(os.path.join(directory, "README.md"), README_GOOD)
    if with_license:
        write(os.path.join(directory, "LICENSE"), "MIT License\n\nCopyright (c) 2026 someone\n")
    return directory


def make_repo(parent: str, workflow: str = WORKFLOW_OK, with_broken_script: bool = False) -> str:
    """构造技能库仓库：根 + demo-skill/ + .github/workflows/。"""
    repo = os.path.join(parent, "repo")
    os.makedirs(repo, exist_ok=True)
    write(os.path.join(repo, "README.md"), "# repo\n\n" + "说明。" * 100 + "\n")
    write(os.path.join(repo, ".gitignore"), "__pycache__/\n")
    write(os.path.join(repo, ".gitattributes"), "* text=auto eol=lf\n")
    write(os.path.join(repo, ".github", "workflows", "validate.yml"), workflow)
    make_skill(repo)
    if with_broken_script:
        write(os.path.join(repo, "demo-skill", "scripts", "check.py"), "print('ok')\n")
    return repo


def run_cli(func, argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = func(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class TestFrontmatter(unittest.TestCase):
    def test_valid(self):
        data, _body, error = precheck.parse_frontmatter(SKILL_MD)
        self.assertIsNone(error)
        self.assertEqual(data["name"], "demo-skill")

    def test_missing_frontmatter(self):
        _data, _body, error = precheck.parse_frontmatter("# 没有 frontmatter\n")
        self.assertIn("frontmatter", error)

    def test_unclosed(self):
        _data, _body, error = precheck.parse_frontmatter("---\nname: x\n")
        self.assertIn("未闭合", error)


class TestSkillPackageChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-check-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_good_package_has_no_errors(self):
        directory = make_skill(self.tmp)
        report = precheck.Report()
        precheck.check_skill_package(directory, report)
        self.assertEqual(report.errors, [])

    def test_directory_name_mismatch_is_error(self):
        directory = make_skill(self.tmp, dirname="skillsmallthings")
        report = precheck.Report()
        precheck.check_skill_package(directory, report)
        self.assertTrue(any("不一致" in message for message in report.errors), report.errors)

    def test_missing_name_is_error(self):
        skill_md = SKILL_MD.replace("name: demo-skill\n", "")
        directory = make_skill(self.tmp, skill_md=skill_md)
        report = precheck.Report()
        precheck.check_skill_package(directory, report)
        self.assertTrue(any("name" in message for message in report.errors))

    def test_too_long_description_is_error(self):
        skill_md = SKILL_MD.replace(
            "description: 演示技能。当用户需要测试发布前预检时使用，覆盖目录名规则、CI 路径可解析性与隐私检查等检查项。",
            "description: " + "长" * 1100)
        directory = make_skill(self.tmp, skill_md=skill_md)
        report = precheck.Report()
        precheck.check_skill_package(directory, report)
        self.assertTrue(any("description 超长" in message for message in report.errors))

    def test_missing_skill_md_is_error(self):
        report = precheck.Report()
        precheck.check_skill_package(self.tmp, report)
        self.assertTrue(any("找不到 SKILL.md" in message for message in report.errors))

    def test_experimental_field_warns(self):
        skill_md = SKILL_MD.replace("license: MIT\n", "license: MIT\nallowed-tools: Bash\n")
        directory = make_skill(self.tmp, skill_md=skill_md)
        report = precheck.Report()
        precheck.check_skill_package(directory, report)
        self.assertTrue(any("allowed-tools" in message for message in report.warnings))


class TestRepoLayoutChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-repo-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_extract_ci_paths_strips_variables(self):
        repo = make_repo(self.tmp)
        paths = precheck.extract_ci_paths(os.path.join(repo, ".github", "workflows", "validate.yml"))
        self.assertIn("scripts/check.py", paths)

    def test_extract_ci_paths_tags_globs(self):
        workflow = os.path.join(self.tmp, "wf.yml")
        write(workflow, "steps:\n  - run: python -m unittest discover -s scripts -p \"test_*.py\"\n")
        paths = precheck.extract_ci_paths(workflow)
        self.assertIn("GLOB:test_*.py", paths, "通配符应被标记为 GLOB，而不是当作仓库路径")
        self.assertTrue(all(p.startswith("GLOB:") or "/" in p for p in paths))

    def test_glob_pattern_does_not_error(self):
        repo = make_repo(self.tmp, with_broken_script=True)
        write(os.path.join(repo, ".github", "workflows", "tests.yml"),
              "steps:\n  - run: python -m unittest discover -s demo-skill/scripts -p \"test_*.py\"\n")
        report = precheck.Report()
        precheck.check_repo_layout(repo, ["demo-skill"], report)
        self.assertEqual([e for e in report.errors if "workflow" in e], [])

    def test_resolvable_ci_path_passes(self):
        repo = make_repo(self.tmp, with_broken_script=True)
        report = precheck.Report()
        precheck.check_repo_layout(repo, ["demo-skill"], report)
        self.assertEqual([e for e in report.errors if "workflow" in e], [])

    def test_unresolvable_ci_path_is_error(self):
        # 这正是真实事故：技能在 demo-skill/ 子目录，workflow 却指向 other-skill/
        repo = make_repo(self.tmp, workflow=WORKFLOW_BAD_PATH)
        report = precheck.Report()
        precheck.check_repo_layout(repo, ["demo-skill"], report)
        self.assertTrue(any("引用的路径不存在" in message for message in report.errors), report.errors)

    def test_missing_gitignore_is_error(self):
        repo = make_repo(self.tmp)
        os.remove(os.path.join(repo, ".gitignore"))
        report = precheck.Report()
        precheck.check_repo_layout(repo, ["demo-skill"], report)
        self.assertTrue(any(".gitignore" in message for message in report.errors))

    def test_missing_workflows_warns(self):
        repo = make_repo(self.tmp)
        shutil.rmtree(os.path.join(repo, ".github"))
        report = precheck.Report()
        precheck.check_repo_layout(repo, ["demo-skill"], report)
        self.assertTrue(any("workflows" in message for message in report.warnings))

    def test_find_skill_dirs_detects_subdirectory_and_root(self):
        repo = make_repo(self.tmp)
        self.assertEqual(precheck.find_skill_dirs(repo), ["demo-skill"])
        write(os.path.join(repo, "SKILL.md"), SKILL_MD)
        self.assertIn(".", precheck.find_skill_dirs(repo))


class TestPrivacyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-priv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_placeholder_emails_recognized(self):
        for email in ("thewal-ker@users.noreply.github.com", "noreply@example.com",
                      "github-actions[bot]@users.noreply.github.com"):
            self.assertTrue(precheck.is_placeholder_email(email), email)

    def test_real_emails_flagged(self):
        for email in ("15249916183@163.com", "someone@qq.com", "me@gmail.com"):
            self.assertFalse(precheck.is_placeholder_email(email), email)

    def test_real_name_in_files_warns(self):
        directory = make_skill(self.tmp)
        write(os.path.join(directory, "LICENSE"), "Copyright (c) 2026 张三\n")
        report = precheck.Report()
        precheck.check_privacy(directory, "张三", None, report)
        self.assertTrue(any("真实姓名" in message for message in report.warnings))
        self.assertTrue(any("LICENSE" in message for message in report.warnings))

    def test_suspicious_email_in_files_warns(self):
        directory = make_skill(self.tmp)
        write(os.path.join(directory, "config.ini"), "contact = someone@163.com\n")
        report = precheck.Report()
        precheck.check_privacy(directory, None, None, report)
        self.assertTrue(any("真实邮箱" in message for message in report.warnings), report.warnings)

    def test_documentation_example_emails_are_not_warnings(self):
        directory = make_skill(self.tmp)
        write(os.path.join(directory, "README.md"), "示例：someone@163.com、me@qq.com\n")
        write(os.path.join(directory, "scripts", "test_x.py"), "EMAIL = 'a@163.com'\n")
        report = precheck.Report()
        precheck.check_privacy(directory, None, None, report)
        self.assertEqual([w for w in report.warnings if "邮箱" in w], [])

    def test_real_email_flag_reports_location(self):
        directory = make_skill(self.tmp)
        write(os.path.join(directory, "README.md"), "联系：someone@163.com\n")
        report = precheck.Report()
        precheck.check_privacy(directory, None, "someone@163.com", report)
        self.assertTrue(any("你指定的真实邮箱" in message for message in report.warnings), report.warnings)

    def test_clean_package_has_no_warnings(self):
        directory = make_skill(self.tmp)
        report = precheck.Report()
        precheck.check_privacy(directory, None, None, report)
        self.assertEqual(report.warnings, [])


class TestGitChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-git-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = make_repo(self.tmp)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def init_repo(self, email="thewal-ker@users.noreply.github.com"):
        self.git("init", "-b", "main")
        self.git("config", "user.name", "thewal-ker")
        self.git("config", "user.email", email)

    def test_missing_identity_is_error(self):
        self.git("init", "-b", "main")
        report = precheck.Report()
        precheck.check_git_identity(self.repo, report)
        self.assertTrue(any("未配置提交身份" in message for message in report.errors), report.errors)

    def test_placeholder_identity_passes(self):
        self.init_repo()
        self.git("add", "-A")
        self.git("commit", "-m", "chore: init")
        report = precheck.Report()
        precheck.check_git_identity(self.repo, report)
        self.assertEqual([e for e in report.errors if "邮箱" in e], [])

    def test_real_email_in_history_is_error(self):
        self.init_repo(email="15249916183@163.com")
        self.git("add", "-A")
        self.git("commit", "-m", "chore: init")
        report = precheck.Report()
        precheck.check_git_identity(self.repo, report)
        self.assertTrue(any("真实邮箱" in message for message in report.errors), report.errors)

    def test_tracked_temp_artifact_is_error(self):
        write(os.path.join(self.repo, "high.json"), "{}\n")
        self.init_repo()
        self.git("add", "-A")
        report = precheck.Report()
        precheck.check_temp_artifacts(self.repo, report)
        self.assertTrue(any("已被 git 跟踪" in message for message in report.errors), report.errors)


class TestPrecheckCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_good_repo_passes(self):
        repo = make_repo(self.tmp, with_broken_script=True)
        code, out, _err = run_cli(precheck.main, ["--repo", repo])
        self.assertEqual(code, 0, out)

    def test_broken_ci_path_fails(self):
        repo = make_repo(self.tmp, workflow=WORKFLOW_BAD_PATH)
        code, out, _err = run_cli(precheck.main, ["--repo", repo])
        self.assertEqual(code, 1)
        self.assertIn("引用的路径不存在", out)

    def test_json_output_shape(self):
        repo = make_repo(self.tmp, with_broken_script=True)
        code, out, _err = run_cli(precheck.main, ["--repo", repo, "--json"])
        self.assertEqual(code, 0)
        payload = __import__("json").loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["skill_dirs"], ["demo-skill"])

    def test_missing_repo_returns_two(self):
        code, _out, _err = run_cli(precheck.main, ["--repo", os.path.join(self.tmp, "nope")])
        self.assertEqual(code, 2)


class TestCommitMsg(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pub-msg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "thewal-ker"], cwd=self.repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "thewal-ker@users.noreply.github.com"],
                       cwd=self.repo, capture_output=True)
        # 切到仓库里跑，main() 用的都是相对路径
        self.previous = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.previous)

    def test_build_writes_utf8_without_bom(self):
        code, _out, _err = run_cli(commit_msg.main,
                                   ["build", "--title", "feat: 首个技能", "--body", "改动说明：含\"引号\"与\n换行"])
        self.assertEqual(code, 0)
        with open(os.path.join(".git", "COMMIT_MSG.txt"), "rb") as handle:
            raw = handle.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "不应写 BOM")
        self.assertNotIn(b"\r\n", raw, "不应写 CRLF")
        text = raw.decode("utf-8")
        self.assertIn("feat: 首个技能", text)
        self.assertIn("含\"引号\"与", text)

    def test_commit_creates_commit_with_message_file(self):
        with open("file.txt", "w", encoding="utf-8") as handle:
            handle.write("x\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, capture_output=True)
        code, _out, _err = run_cli(commit_msg.main,
                                   ["build", "--title", "chore: init", "--commit"])
        self.assertEqual(code, 0)
        log = subprocess.run(["git", "log", "--format=%s", "-1"], cwd=self.repo,
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(log, "chore: init")

    def test_commit_with_empty_index_fails(self):
        code, _out, err = run_cli(commit_msg.main, ["commit"])
        self.assertEqual(code, 2)
        self.assertIn("暂存区为空", err)

    def test_title_warnings(self):
        long_title = "feat: " + "很长的标题" * 20
        problems = commit_msg.validate_title(long_title)
        self.assertTrue(any("72" in problem for problem in problems))
        self.assertTrue(any("类型前缀" in problem for problem in commit_msg.validate_title("随手写一句")))

    def test_suggest_title_uses_scope(self):
        self.assertEqual(commit_msg.suggest_title(["game-fit-advisor/scripts/a.py"]),
                         "fix(game-fit-advisor): 更新脚本")
        self.assertEqual(commit_msg.suggest_title([".github/workflows/validate.yml"]),
                         "ci: 更新工作流")

    def test_status_reports_untracked_and_title(self):
        with open("new.md", "w", encoding="utf-8") as handle:
            handle.write("hi\n")
        code, out, _err = run_cli(commit_msg.main, ["status"])
        self.assertEqual(code, 0)
        self.assertIn("new.md", out)
        self.assertIn("建议标题", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
