#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨 shell 安全的提交信息工具：解决 PowerShell 吃掉引号、重定向写 BOM 两个坑。

只依赖 Python 3.9+ 标准库。

用法：

    # 1) 看当前改动并拿到一份建议的提交信息
    python commit_msg.py status

    # 2) 从文件（或命令行）组装提交信息，写进 .git/COMMIT_MSG.txt
    python commit_msg.py build --title "fix(ci): 修正校验路径" --body-file notes.md
    python commit_msg.py build --title "feat: 首个技能" --body "改动说明" --commit

    # 3) 直接提交（内部调用 git commit -F，绕开 shell 解析）
    python commit_msg.py commit

要点：
  - 一律以 UTF-8 无 BOM + LF 写入，避免 PowerShell 重定向的 UTF-16/BOM 问题
  - 提交信息只经文件传递，不在命令行里塞多行文本
  - 标题超过 72 字符、为空、或含控制字符时给出警告
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import List, Optional, Sequence

DEFAULT_MSG_FILE = os.path.join(".git", "COMMIT_MSG.txt")
TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "ci", "perf")
TITLE_RE = re.compile(r"^(?:%s)(\([^)]+\))?!?:\s+\S" % "|".join(TYPES))


def run_git(args: Sequence[str], quiet: bool = False) -> int:
    if quiet:
        try:
            return subprocess.call(["git", *args], stdout=subprocess.DEVNULL)
        except (OSError, FileNotFoundError):
            return 127
    return subprocess.call(["git", *args])


def git_output(args: Sequence[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return ""
    return (proc.stdout or "").strip()


def is_git_repo() -> bool:
    return git_output(["rev-parse", "--is-inside-work-tree"]) == "true"


def suggest_title(changed: Sequence[str]) -> str:
    """按改动文件的分布猜一个标题与 scope，减少用户手敲。"""
    if not changed:
        return "chore: 更新"
    skills = sorted({path.split("/", 1)[0] for path in changed
                     if "/" in path and path.split("/", 1)[0] not in (".github",)})
    scope = skills[0] if len(skills) == 1 else None
    if all(path.startswith(".github/") for path in changed):
        return "ci: 更新工作流"
    if all(path.endswith(".md") for path in changed):
        return "docs%s: 更新文档" % ("(%s)" % scope if scope else "")
    if any(path.endswith((".py", ".js", ".sh")) for path in changed):
        return "fix%s: 更新脚本" % ("(%s)" % scope if scope else "")
    return "chore%s: 更新文件" % ("(%s)" % scope if scope else "")


def cmd_status(args: argparse.Namespace) -> int:
    if not is_git_repo():
        print("当前目录不是 git 仓库；先执行 git init -b main", file=sys.stderr)
        return 2

    staged = [line for line in git_output(["diff", "--cached", "--name-only"]).splitlines() if line]
    unstaged = [line for line in git_output(["diff", "--name-only"]).splitlines() if line]
    untracked = [line for line in git_output(["ls-files", "--others", "--exclude-standard"]).splitlines() if line]

    print("已暂存：%d 个文件" % len(staged))
    for path in staged[:20]:
        print("   + %s" % path)
    if len(staged) > 20:
        print("   ... 其余 %d 个" % (len(staged) - 20))
    if unstaged:
        print("已修改未暂存：%s" % "、".join(unstaged[:10]))
    if untracked:
        print("未跟踪（确认是否需要加入，或写进 .gitignore）：")
        for path in untracked[:20]:
            print("   ? %s" % path)

    print("\n建议标题：%s" % suggest_title(staged or unstaged or untracked))
    print("\n下一步：")
    print('  python scripts/commit_msg.py build --title "<标题>" --body-file <说明文件> --commit')
    return 0


def validate_title(title: str) -> List[str]:
    problems: List[str] = []
    if not title.strip():
        problems.append("标题为空")
    if len(title) > 72:
        problems.append("标题 %d 字符，建议 ≤ 72" % len(title))
    if '"' in title or "'" in title:
        problems.append("标题含引号：本工具走文件传递没问题，但直接在 shell 里用会踩坑")
    if any(ord(ch) < 32 for ch in title):
        problems.append("标题含控制字符")
    if not TITLE_RE.match(title):
        problems.append("标题未使用 feat/fix/docs/chore 等类型前缀（建议，不强制）")
    return problems


def build_message(title: str, body_parts: Sequence[str]) -> str:
    body = "\n\n".join(part.strip() for part in body_parts if part and part.strip())
    text = title.strip() if not body else "%s\n\n%s" % (title.strip(), body)
    return text.rstrip() + "\n"


def write_message(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    # newline="\n" + UTF-8（不写 BOM）：跨平台一致，脚本读取端无需特殊处理
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def cmd_build(args: argparse.Namespace) -> int:
    body_parts: List[str] = []
    if args.body:
        body_parts.append(args.body)
    if args.body_file:
        try:
            with open(args.body_file, "r", encoding="utf-8-sig") as handle:
                body_parts.append(handle.read())
        except OSError as exc:
            print("无法读取 --body-file：%s" % exc, file=sys.stderr)
            return 2

    message = build_message(args.title, body_parts)
    path = args.out or DEFAULT_MSG_FILE
    # 先落盘，再打印：即使输出管道被提前关闭，提交信息也已写好
    write_message(path, message)

    def say(text: str) -> None:
        try:
            print(text)
        except (BrokenPipeError, ValueError, OSError):
            pass

    for problem in validate_title(args.title):
        say("  [警告] %s" % problem)
    say("已写入提交信息：%s（%d 字符，UTF-8 无 BOM）" % (path, len(message)))
    say("-" * 56)
    say(message.rstrip())
    say("-" * 56)

    if args.commit:
        return git_commit(path)
    say("下一步：git commit -F %s" % path)
    return 0


def git_commit(path: str) -> int:
    if not is_git_repo():
        print("当前目录不是 git 仓库", file=sys.stderr)
        return 2
    staged = git_output(["diff", "--cached", "--name-only"])
    if not staged:
        print("暂存区为空：先 git add -A", file=sys.stderr)
        return 2
    if not os.path.isfile(path):
        print("找不到提交信息文件：%s（先运行 build）" % path, file=sys.stderr)
        return 2
    return run_git(["commit", "-F", path], quiet=True)


def cmd_commit(args: argparse.Namespace) -> int:
    return git_commit(args.out or DEFAULT_MSG_FILE)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    # 输出被管道提前关闭时（例如 PowerShell 的 `| Select-Object -First N`），
    # 默认行为会让进程在"写完提交信息文件"之前就被打断。忽略 SIGPIPE，
    # 改为在写入失败处捕获 BrokenPipeError，保证提交信息一定落盘。
    try:
        import signal as signal_module
        if hasattr(signal_module, "SIGPIPE"):
            signal_module.signal(signal_module.SIGPIPE, signal_module.SIG_IGN)
    except (ImportError, ValueError, OSError):
        pass

    parser = argparse.ArgumentParser(prog="commit_msg.py",
                                     description="跨 shell 安全的提交信息工具")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="查看改动并给出建议标题")
    status.set_defaults(func=cmd_status)

    build = sub.add_parser("build", help="组装提交信息并写入文件")
    build.add_argument("--title", required=True, help="标题（一行）")
    build.add_argument("--body", help="正文（单段，短文本用）")
    build.add_argument("--body-file", help="正文文件（长文本用，UTF-8）")
    build.add_argument("--out", help="输出路径（默认 .git/COMMIT_MSG.txt）")
    build.add_argument("--commit", action="store_true", help="写完立即提交")
    build.set_defaults(func=cmd_build)

    commit = sub.add_parser("commit", help="用已有信息文件提交")
    commit.add_argument("--out", help="信息文件路径（默认 .git/COMMIT_MSG.txt）")
    commit.set_defaults(func=cmd_commit)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # 输出管道被下游提前关闭：按惯例返回 0，工作已完成
        try:
            sys.stderr.close()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
