#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送前的预检：把"发布 skill 到 GitHub"踩过的坑变成自动检查。

只依赖 Python 3.9+ 标准库。

用法：

    python precheck.py                                   # 检查当前目录的技能包
    python precheck.py --skill-dir github-skill-publisher
    python precheck.py --repo . --real-name 张三 --real-email you@example.com
    python precheck.py --json

`--repo` 用于技能库仓库（仓库根含 .github/），会额外检查：
  - CI 里引用的脚本路径是否存在
  - 仓库根是否有 README / .gitignore / .gitattributes
  - 是否有仓库级 LICENSE 与技能包内 LICENSE

检查项：
  [错误] 必须修掉才能推送
  [警告] 逐条判断是否接受
  [信息] 供参考
"""

from __future__ import annotations

import argparse
import glob as glob_module
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

MAX_DESCRIPTION_LEN = 1024
PLACEHOLDER_EMAIL_DOMAINS = ("noreply.github.com", "users.noreply.github.com",
                             "example.com", "example.org", "localhost")
PLACEHOLDER_LOCAL_HINTS = ("noreply", "no-reply", "bot", "actions", "github-actions")
TEMP_ARTIFACT_PATTERNS = (
    (re.compile(r"(^|/)__pycache__/"), "__pycache__ 字节码目录"),
    (re.compile(r"\.pyc$"), "Python 字节码"),
    (re.compile(r"(^|/)\.DS_Store$"), "macOS 垃圾文件"),
    (re.compile(r"(^|/)Thumbs\.db$"), "Windows 缩略图缓存"),
    (re.compile(r"(^|/)reports?/[^/]+$"), "诊断产物目录"),
    (re.compile(r"\.(?:log|tmp)$"), "日志/临时文件"),
    (re.compile(r"(^|/)(?:high|critical|smoke|result|results|output|tmp|temp)[^/]*\.json$"),
     "试跑产物 JSON"),
)
# 这些 JSON 是项目正常组成部分，不算试跑产物
ARTIFACT_ALLOWLIST = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "tsconfig.json",
    "manifest.json", "plugin.json", "composer.json", "pyproject.json",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.infos: List[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


def run_git(args: Sequence[str], cwd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return 127, ""
    return proc.returncode, (proc.stdout or "").strip()


def is_git_repo(directory: str) -> bool:
    code, out = run_git(["rev-parse", "--is-inside-work-tree"], directory)
    return code == 0 and out.strip() == "true"


def tracked_files(directory: str) -> List[str]:
    code, out = run_git(["ls-files"], directory)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# 检查：SKILL.md
# --------------------------------------------------------------------------

def parse_frontmatter(text: str):
    """返回 (data, body, error)。只解析标量与本技能需要的一层嵌套。"""
    if not text.startswith("---"):
        return {}, text, "SKILL.md 必须以 YAML frontmatter 开头"
    lines = text.splitlines()
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text, "frontmatter 未闭合（缺少第二处 ---）"
    data: Dict[str, object] = {}
    current_key: Optional[str] = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  ") and current_key:
            nested = raw.strip()
            if ":" in nested:
                key, _, value = nested.partition(":")
                mapping = data.get(current_key)
                if isinstance(mapping, dict):
                    mapping[key.strip()] = value.strip().strip("'\"")
            continue
        if ":" not in raw:
            return {}, text, "frontmatter 行不是 key: value：%r" % raw
        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if value in ("", "|", ">"):
            data[key] = {}
            current_key = key
        else:
            data[key] = value.strip("'\"")
            current_key = None
    return data, "\n".join(lines[end + 1:]), None


def check_yaml_scalar_safety(frontmatter_lines: List[str], report: "Report") -> None:
    """真实事故：未加引号的标量里出现 ": "（ASCII 冒号 + 空格）会让 YAML 解析失败，
    加载器只写日志、静默跳过该技能——界面上完全看不出问题。
    本项目曾因 description 结尾写了 "English: Diagnose ..." 踩中，
    结果技能装好了却永远加载不出来。这里在推送前就拦住。
    """
    for index, raw in enumerate(frontmatter_lines, start=2):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            nested = line.strip()
            if ":" not in nested:
                continue
            _key, _, value = nested.partition(":")
        else:
            if ":" not in line:
                continue
            _key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith(("'", '"', "|", ">")):
            continue
        if ": " in value or value.endswith(":"):
            report.error(
                "frontmatter 第 %d 行：未加引号的值里出现 ASCII 冒号（%r...）；"
                "YAML 会解析失败、技能被静默忽略。改用单引号包裹整个值：key: '...'"
                % (index, value[:40]))


def _frontmatter_lines(text: str) -> List[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    return []


def check_skill_package(skill_dir: str, report: Report) -> Optional[Dict[str, object]]:
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        report.error("在 %s 下找不到 SKILL.md；技能包必须含 SKILL.md" % skill_dir)
        return None

    with open(skill_md, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    check_yaml_scalar_safety(_frontmatter_lines(text), report)
    data, body, error = parse_frontmatter(text)
    if error:
        report.error("SKILL.md frontmatter 解析失败：%s" % error)
        return data

    name = data.get("name")
    if not isinstance(name, str) or not name:
        report.error("frontmatter 缺少必填字段 name")
    else:
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
            report.error("name 只允许小写字母、数字与单连字符：%r" % name)
        if len(name) > 64:
            report.error("name 超长：%d > 64" % len(name))
        if os.path.basename(os.path.abspath(skill_dir)) != name:
            report.error("目录名（%s）与 name（%s）不一致：安装时目录名必须等于 name"
                         % (os.path.basename(os.path.abspath(skill_dir)), name))
        else:
            report.info("目录名与 name 一致：%s" % name)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        report.error("frontmatter 缺少必填字段 description")
    else:
        if len(description) > MAX_DESCRIPTION_LEN:
            report.error("description 超长：%d > %d" % (len(description), MAX_DESCRIPTION_LEN))
        if "{" in description or "<" in description:
            report.warn("description 含可疑占位符字符，自动匹配效果会变差")
        report.info("description 长度：%d 字符" % len(description))

    if "allowed-tools" in data:
        report.warn("allowed-tools 属实验字段，非必要建议删除")

    body_lines = [line for line in body.splitlines() if line.strip()]
    if len(body_lines) > 500:
        report.warn("SKILL.md 正文 %d 行，建议 ≤ 500 行（细节移入 references/）" % len(body_lines))
    else:
        report.info("SKILL.md 正文 %d 行" % len(body_lines))

    # 技能包组成的推荐文件
    for relative in ("README.md", "LICENSE"):
        if os.path.isfile(os.path.join(skill_dir, relative)):
            report.info("存在 %s" % relative)
        else:
            report.warn("技能包内缺 %s（发布到 GitHub 时建议补上）" % relative)
    return data


# --------------------------------------------------------------------------
# 检查：仓库级
# --------------------------------------------------------------------------

def extract_ci_paths(workflow_path: str) -> List[str]:
    """从 workflow 里抽取脚本路径，形如 "$SKILL_DIR/scripts/x.py"、"scripts/x.py"。

    返回值里 `GLOB:` 前缀表示通配模式（如 `scripts/test_*.py`），校验时按 glob 匹配。
    含未解析变量且去掉变量后不成为路径的片段会被跳过。
    """
    with open(workflow_path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    found = set()
    for match in re.finditer(r'["\']([^"\'\n]*\.(?:py|sh|js|mjs|ps1))["\']', text):
        raw = match.group(1)
        raw = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "", raw)   # 去掉变量
        raw = raw.replace("//", "/").lstrip("./")
        if not raw or raw.startswith("/"):
            continue
        if "*" in raw or "?" in raw:
            # 通配符：把模式所在目录也补成一条 glob，避免 "-p test_*.py" 这种
            # （模式不带目录）被误判为"未匹配到文件"
            prefix = os.path.dirname(raw)
            found.add("GLOB:" + raw)
            if prefix:
                found.add("GLOB:" + prefix + "/*")
            continue
        if "/" not in raw:
            continue                            # 变量拼出的残缺路径，跳过
        found.add(raw)
    return sorted(found)


def check_repo_layout(repo_dir: str, skill_dirs: List[str], report: Report) -> None:
    for relative in ("README.md", ".gitignore"):
        if os.path.isfile(os.path.join(repo_dir, relative)):
            report.info("仓库根存在 %s" % relative)
        else:
            report.error("仓库根缺 %s" % relative)
    if not os.path.isfile(os.path.join(repo_dir, ".gitattributes")):
        report.warn("仓库根缺 .gitattributes（建议加 `* text=auto eol=lf` 统一换行符）")

    workflows_dir = os.path.join(repo_dir, ".github", "workflows")
    if not os.path.isdir(workflows_dir):
        report.warn("未找到 .github/workflows/：CI 缺失，改动没有自动验证")
        return

    for name in sorted(os.listdir(workflows_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(workflows_dir, name)
        report.info("检查 workflow：%s" % name)
        for reference in extract_ci_paths(path):
            is_glob = reference.startswith("GLOB:")
            raw = reference[5:] if is_glob else reference
            bases = [repo_dir] + [os.path.join(repo_dir, skill) for skill in skill_dirs]
            if is_glob:
                # 模式与"模式所在目录/*"都试：覆盖 "-p test_*.py"（模式不带目录）的写法
                patterns = [raw]
                prefix = os.path.dirname(raw)
                if prefix:
                    patterns.append(prefix + "/*")
                matched = any(glob_module.glob(os.path.join(base, pattern))
                              for base in bases for pattern in patterns)
                if not matched:
                    # unittest 的 -p "test_*.py" 这类是运行时发现模式，不是仓库路径，
                    # 匹配不到属正常，降为提示以免制造噪音。
                    report.info("workflow %s 的通配模式（运行时发现用，非仓库路径）：%s" % (name, raw))
                continue
            candidates = [os.path.join(base, raw) for base in bases]
            if not any(os.path.exists(candidate) for candidate in candidates):
                report.error("workflow %s 引用的路径不存在：%s（仓库结构可能与之不匹配）"
                             % (name, raw))
            else:
                report.info("  workflow 路径可解析：%s" % raw)

    if len(skill_dirs) > 1:
        report.info("仓库含 %d 个技能目录：workflow 必须逐个显式指向，或用 SKILL_DIR 变量自适应"
                    % len(skill_dirs))


# --------------------------------------------------------------------------
# 检查：隐私
# --------------------------------------------------------------------------

def is_placeholder_email(email: str) -> bool:
    lowered = email.lower()
    if any(lowered.endswith(domain) for domain in PLACEHOLDER_EMAIL_DOMAINS):
        return True
    local = lowered.split("@", 1)[0]
    return any(hint in local for hint in PLACEHOLDER_LOCAL_HINTS)


def check_privacy(directory: str, real_name: Optional[str], real_email: Optional[str],
                  report: Report) -> None:
    if real_name:
        hits: List[str] = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            for filename in files:
                path = os.path.join(root, filename)
                try:
                    with open(path, "r", encoding="utf-8-sig") as handle:
                        content = handle.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if real_name in content:
                    rel = os.path.relpath(path, directory)
                    lines = [str(i) for i, line in enumerate(content.splitlines(), 1) if real_name in line]
                    hits.append("%s (行 %s)" % (rel, ", ".join(lines[:5])))
        if hits:
            report.warn("文件里出现真实姓名「%s」：%s（公开仓库会暴露；确认是否要替换）"
                        % (real_name, "；".join(hits)))
        else:
            report.info("文件里未发现真实姓名")

    if real_email:
        lowered = real_email.lower()
        try:
            with open(os.path.join(directory, "LICENSE"), "r", encoding="utf-8-sig") as handle:
                if lowered in handle.read().lower():
                    report.warn("LICENSE 里出现真实邮箱")
        except OSError:
            pass

    # 扫描文件里的真实邮箱（qq/163/126/gmail/outlook 等），忽略占位域名。
    # 降噪：文档（.md）与测试脚本里的邮箱多为"举例说明"，单列出来不触发警告；
    # 其余文件（配置、脚本、数据）里出现真实邮箱才值得警惕。
    by_email: Dict[str, set] = {}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        for filename in files:
            path = os.path.join(root, filename)
            if os.path.splitext(filename)[1].lower() in (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"):
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    content = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            rel = os.path.relpath(path, directory).replace(os.sep, "/")
            for email in sorted(set(EMAIL_RE.findall(content))):
                if is_placeholder_email(email):
                    continue
                by_email.setdefault(email.lower(), set()).add(rel)

    if real_email and real_email.lower() in by_email:
        report.warn("文件里出现你指定的真实邮箱（%s）：%s"
                    % (real_email, "、".join(sorted(by_email[real_email.lower()]))))

    def is_example_file(rel: str) -> bool:
        base = os.path.basename(rel)
        return rel.endswith(".md") or (base.startswith("test_") and base.endswith(".py"))

    leaked = {email: sorted(paths) for email, paths in by_email.items()
              if any(not is_example_file(path) for path in paths)}
    if leaked:
        report.warn("非文档/测试文件里出现真实邮箱：%s；确认是否需要替换"
                    % "；".join("%s（%s）" % (email, "、".join(paths)) for email, paths in sorted(leaked.items())))
    elif by_email:
        report.info("文件里的邮箱均属占位域名或文档示例（%d 处）" % sum(len(v) for v in by_email.values()))


def check_git_identity(directory: str, report: Report) -> None:
    if not is_git_repo(directory):
        report.info("当前目录不是 git 仓库（首次发布会执行 git init）")
        return

    code, name = run_git(["config", "--get", "user.name"], directory)
    code2, email = run_git(["config", "--get", "user.email"], directory)
    if code != 0 or not name or code2 != 0 or not email:
        report.error("未配置提交身份：git commit / --amend / rebase 都会失败，"
                     "先 git config user.name / user.email")
    else:
        report.info("提交身份（仓库级）：%s <%s>" % (name, email))
        if not is_placeholder_email(email):
            report.warn("提交身份用的是真实邮箱（%s）：建议换成 <用户名>@users.noreply.github.com" % email)

    code, log = run_git(["log", "--all", "--format=%h|%an|%ae|%cn|%ce"], directory)
    if code != 0 or not log:
        report.info("尚无提交历史")
        return
    offenders: List[str] = []
    for line in log.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        short, author, author_email, committer, committer_email = parts
        for email in (author_email, committer_email):
            if email and not is_placeholder_email(email):
                offenders.append("%s 使用真实邮箱 %s" % (short, email))
    if offenders:
        report.error("提交历史里存在真实邮箱（公开仓库会暴露）：%s；"
                     "处理流程见 references/privacy-and-history-rewrite.md"
                     % "；".join(sorted(set(offenders))[:5]))
    else:
        report.info("提交历史里的邮箱均为占位/noreply 域名")

    code, remote = run_git(["remote", "-v"], directory)
    if code == 0 and remote:
        report.info("已配置远程：%s" % remote.splitlines()[0])
    else:
        report.warn("尚未配置远程仓库（git remote add origin <url>）")


def check_temp_artifacts(directory: str, report: Report) -> None:
    tracked = set(tracked_files(directory))
    hits: List[str] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d != ".git"]
        for filename in files:
            path = os.path.join(root, filename)
            rel = os.path.relpath(path, directory).replace(os.sep, "/")
            if os.path.basename(rel).lower() in ARTIFACT_ALLOWLIST:
                continue
            for pattern, label in TEMP_ARTIFACT_PATTERNS:
                if pattern.search(rel):
                    hits.append("%s（%s）" % (rel, label))
                    break
    if not hits:
        report.info("未发现临时产物")
        return
    tracked_hits = [hit for hit in hits if hit.split("（")[0] in tracked]
    if tracked_hits:
        report.error("临时产物已被 git 跟踪：%s（从仓库移除并加入 .gitignore）" % "；".join(tracked_hits))
    else:
        report.warn("工作区存在未跟踪的临时产物：%s（确认 .gitignore 覆盖它们）"
                    % "；".join(hits[:6]))


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def find_skill_dirs(repo_dir: str) -> List[str]:
    found: List[str] = []
    if os.path.isfile(os.path.join(repo_dir, "SKILL.md")):
        found.append(".")
    for name in sorted(os.listdir(repo_dir)):
        path = os.path.join(repo_dir, name)
        if not name.startswith(".") and os.path.isdir(path) and os.path.isfile(os.path.join(path, "SKILL.md")):
            found.append(name)
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="precheck.py",
                                     description="发布 skill 到 GitHub 前的预检")
    parser.add_argument("--repo", default=".", help="仓库根目录（默认当前目录）")
    parser.add_argument("--skill-dir", help="技能目录（默认自动发现；'.' 表示技能在仓库根）")
    parser.add_argument("--real-name", help="需要扫描的真实姓名（可多次传入）", action="append")
    parser.add_argument("--real-email", help="需要扫描的真实邮箱", action="append")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    repo_dir = os.path.abspath(args.repo)
    if not os.path.isdir(repo_dir):
        print("目录不存在：%s" % repo_dir, file=sys.stderr)
        return 2

    report = Report()

    if args.skill_dir:
        skill_dirs = [args.skill_dir]
    else:
        skill_dirs = find_skill_dirs(repo_dir)
        if not skill_dirs:
            report.error("未找到任何含 SKILL.md 的技能目录（可用 --skill-dir 指定）")

    for skill in skill_dirs:
        skill_path = skill if skill == "." else os.path.join(repo_dir, skill)
        report.info("=== 技能包：%s ===" % (skill if skill != "." else "仓库根"))
        check_skill_package(skill_path, report)

    if len(skill_dirs) > 1 or any(skill != "." for skill in skill_dirs):
        report.info("=== 仓库级检查 ===")
        check_repo_layout(repo_dir, [s for s in skill_dirs if s != "."], report)

    report.info("=== 隐私检查 ===")
    for real_name in (args.real_name or []):
        check_privacy(repo_dir, real_name, None, report)
    if not args.real_name:
        check_privacy(repo_dir, None, None, report)
    for real_email in (args.real_email or []):
        check_privacy(repo_dir, None, real_email, report)

    report.info("=== git 与产物 ===")
    check_git_identity(repo_dir, report)
    check_temp_artifacts(repo_dir, report)

    if args.json:
        print(json.dumps({
            "repo": repo_dir,
            "skill_dirs": skill_dirs,
            "ok": not report.errors,
            "errors": report.errors,
            "warnings": report.warnings,
            "infos": report.infos,
        }, ensure_ascii=False, indent=2))
    else:
        print("预检目录：%s" % repo_dir)
        print("技能目录：%s" % "、".join(skill_dirs) if skill_dirs else "（未找到）")
        print("-" * 56)
        for message in report.infos:
            print("  [信息] %s" % message)
        for message in report.warnings:
            print("  [警告] %s" % message)
        for message in report.errors:
            print("  [错误] %s" % message)
        print("-" * 56)
        if report.errors:
            print("结论：不可推送（%d 个错误，%d 个警告）——修完再推"
                  % (len(report.errors), len(report.warnings)))
        else:
            print("结论：可以推送（0 个错误，%d 个警告）" % len(report.warnings))

    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
