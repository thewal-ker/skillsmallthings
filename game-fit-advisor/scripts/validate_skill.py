#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验本技能包是否符合 Agent Skills 开放规范，并检查包内三方一致性。

只依赖 Python 3.9+ 标准库。

用法：

    python validate_skill.py                            # 自动定位技能目录；放宽目录名要求
    python validate_skill.py ./game-fit-advisor         # 校验技能目录（目录名须等于 name）
    python validate_skill.py ./game-fit-advisor --json  # 机器可读输出
    python validate_skill.py . --name game-fit-advisor  # 显式给技能名，放宽目录名要求

不带目录参数时：先看当前目录有没有 SKILL.md，没有则找唯一的、含 SKILL.md 的一级子目录。
因此技能库仓库（仓库根名 ≠ 技能名）可以直接在根目录运行本脚本。

校验内容：
  1. SKILL.md 存在，frontmatter 为合法 YAML 子集，字段名/取值符合规范
  2. name 与所在目录名一致（不带目录参数或用 --name 时跳过）
  3. description 非空、长度合规
  4. SKILL.md 正文行数建议上限
  5. 本技能包约定的推荐文件是否齐全（缺失为警告）
  6. 维度 key 在 question-bank.md / scoring-rubric.md / scripts/diagnose.py 三方一致
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_COMPATIBILITY_LEN = 500
BODY_LINE_WARN = 500

RECOGNIZED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]*\}\}|<[a-z-]+>")

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    "references/question-bank.md",
    "references/scoring-rubric.md",
    "references/interaction-rules.md",
    "assets/report-template.md",
    "scripts/diagnose.py",
    "scripts/test_diagnose.py",
    "scripts/test_validate_skill.py",
    "scripts/validate_skill.py",
]

# 与 scripts/diagnose.py 的 DIMENSIONS 保持一致
EXPECTED_KEYS = [
    "core_loop", "controls", "pace", "social", "challenge", "content", "immersion", "time_budget",
    "time_cost", "hardware", "payment", "community", "update", "emotion", "retention", "values",
]


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


# --------------------------------------------------------------------------
# frontmatter（规范只允许简单标量 + 一层键值映射，这里实现最小子集解析）
# --------------------------------------------------------------------------

def parse_frontmatter(text: str, report: Report) -> Tuple[Dict[str, object], str]:
    if not text.startswith("---"):
        report.error("SKILL.md 缺少 YAML frontmatter（文件必须以 --- 开头）")
        return {}, text
    lines = text.splitlines()
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        report.error("frontmatter 未闭合（缺少第二处 --- 分隔线）")
        return {}, text

    data: Dict[str, object] = {}
    current_map: Optional[str] = None
    current_key: Optional[str] = None
    seen: set = set()

    for offset, raw in enumerate(lines[1:end], start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") and current_map and current_key:
            nested = line.strip()
            if ":" not in nested:
                report.error("frontmatter 第 %d 行：metadata 子项缺少冒号" % offset)
                continue
            sub_key, _, sub_value = nested.partition(":")
            mapping = data[current_key]
            assert isinstance(mapping, dict)
            value = sub_value.strip().strip("'\"")
            if sub_key.strip() in mapping:
                report.warn("frontmatter 第 %d 行：metadata 重复键 %s（保留首个有效值）" % (offset, sub_key.strip()))
                continue
            if value.startswith("[") or value.endswith("}"):
                report.warn("frontmatter 第 %d 行：metadata 值疑似嵌套集合，部分实现会跳过" % offset)
            mapping[sub_key.strip()] = value
            continue

        if ":" not in line:
            report.error("frontmatter 第 %d 行不是合法的 key: value：%r" % (offset, line))
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key != key.lower():
            report.error("frontmatter 字段名必须全小写：%r" % key)
        if key in seen:
            report.error("frontmatter 字段重复：%r" % key)
        seen.add(key)
        if key not in RECOGNIZED_FIELDS:
            report.warn("frontmatter 含未被规范识别的字段 %r（实现会忽略，建议删除）" % key)
        current_map = None
        current_key = None
        if not value:
            data[key] = {}
            current_map = key
            current_key = key
        else:
            if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
                value = value[1:-1]
            elif value.startswith("[") or value.startswith("{"):
                report.warn("frontmatter 字段 %r 使用了集合写法；规范要求标量字段用字符串" % key)
            data[key] = value

    body = "\n".join(lines[end + 1:])
    return data, body


def _frontmatter_lines(text: str) -> List[str]:
    """取出 frontmatter 里的原始行（不含首尾 --- 分隔线）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    return []


def check_yaml_scalar_safety(frontmatter_lines: List[str], report: Report) -> None:
    """真实事故防线：未加引号的标量里出现 ": "（ASCII 冒号 + 空格）会让
    YAML 解析失败，而加载器只会静默跳过该技能（只写日志，界面无任何提示）。
    本项目的 description 曾因为结尾的 "English: Diagnose ..." 触发此问题，
    导致技能装了却永远加载不出来。这里在解析阶段就拦住。
    """
    for index, raw in enumerate(frontmatter_lines, start=2):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):          # 嵌套值单独处理
            nested = line.strip()
            if ":" not in nested:
                continue
            _key, _, value = nested.partition(":")
        else:
            if ":" not in line:
                continue
            _key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith(("'", '"', "|", ">")):  # 已加引号或用块标量：安全
            continue
        if ": " in value or value.endswith(":"):
            report.error(
                "frontmatter 第 %d 行：未加引号的值里出现 ASCII 冒号（%r...），"
                "YAML 会解析失败、技能被静默忽略。请用单引号包裹整个值："
                "key: '...'" % (index, value[:40]))


def check_frontmatter(data: Dict[str, object], body: str, directory: str, report: Report,
                      check_name: bool = True) -> None:
    name = data.get("name")
    if not isinstance(name, str) or not name:
        report.error("frontmatter 缺少必填字段 name")
    else:
        if len(name) > MAX_NAME_LEN:
            report.error("name 超长：%d > %d" % (len(name), MAX_NAME_LEN))
        if not NAME_PATTERN.match(name):
            report.error("name 只允许小写字母、数字与单连字符：%r" % name)
        dirname = os.path.basename(os.path.abspath(directory))
        if not check_name:
            report.info("已跳过目录名校验（技能库仓库模式：根目录名与技能名可以不同）")
        elif dirname != name:
            # 显式指定了技能目录，就按规范严格要求：安装时可被直接复制/软链到技能目录下。
            report.error("name（%s）必须与所在目录名（%s）一致；"
                         "技能库仓库请改用 validate_skill.py . --name %s" % (name, dirname, name))
        else:
            report.info("name 与目录名一致：%s" % name)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        report.error("frontmatter 缺少必填字段 description")
    else:
        if len(description) > MAX_DESCRIPTION_LEN:
            report.error("description 超长：%d > %d" % (len(description), MAX_DESCRIPTION_LEN))
        if PLACEHOLDER_PATTERN.search(description):
            report.error("description 含占位符，会降低自动匹配效果")
        if len(description) < 60:
            report.warn("description 偏短（%d 字符），建议写清「做什么 + 何时用 + 关键词」" % len(description))
        report.info("description 长度：%d 字符" % len(description))

    compatibility = data.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > MAX_COMPATIBILITY_LEN:
        report.error("compatibility 超长：%d > %d" % (len(compatibility), MAX_COMPATIBILITY_LEN))

    if "allowed-tools" in data:
        report.warn("allowed-tools 属实验字段，不同实现支持度不一，非必要建议删除")

    body_lines = [line for line in body.splitlines() if line.strip()]
    if len(body_lines) > BODY_LINE_WARN:
        report.warn("SKILL.md 正文 %d 行，超过建议上限 %d 行，建议把细节移入 references/"
                    % (len(body_lines), BODY_LINE_WARN))
    else:
        report.info("SKILL.md 正文 %d 行（建议 ≤ %d）" % (len(body_lines), BODY_LINE_WARN))


# --------------------------------------------------------------------------
# 包内一致性
# --------------------------------------------------------------------------

def check_files(directory: str, report: Report) -> None:
    """检查技能包内容。缺失项记为警告：规范只强制要求 SKILL.md，
    其余是本技能包的约定；在技能库仓库里对根目录校验时它们本就不存在。"""
    for relative in REQUIRED_FILES:
        path = os.path.join(directory, relative)
        if not os.path.isfile(path):
            report.warn("缺少推荐文件：%s" % relative)
    for relative in ("references", "assets", "scripts"):
        if not os.path.isdir(os.path.join(directory, relative)):
            report.warn("缺少推荐目录：%s/" % relative)


def check_key_consistency(directory: str, report: Report) -> None:
    question_bank = os.path.join(directory, "references", "question-bank.md")
    rubric = os.path.join(directory, "references", "scoring-rubric.md")
    script = os.path.join(directory, "scripts", "diagnose.py")

    missing_files = [p for p in (question_bank, rubric, script) if not os.path.isfile(p)]
    if missing_files:
        return  # check_files 已报错

    def read(path: str) -> str:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    bank_text = read(question_bank)
    rubric_text = read(rubric)
    script_text = read(script)

    for key in EXPECTED_KEYS:
        if ("`%s`" % key) not in bank_text:
            report.error("question-bank.md 缺少维度 key：%s" % key)
        if ("`%s`" % key) not in rubric_text:
            report.error("scoring-rubric.md 缺少维度 key：%s" % key)
        if ('"%s"' % key) not in script_text:
            report.error("diagnose.py 缺少维度 key：%s" % key)

    extra = set(re.findall(r"`([a-z_]+)`", bank_text)) - set(EXPECTED_KEYS)
    suspicious = {k for k in extra if k in script_text}
    if suspicious:
        report.warn("question-bank.md 出现未登记的 key：%s" % "、".join(sorted(suspicious)))

    # 权重表与脚本权重一致性
    for key in EXPECTED_KEYS:
        match = re.search(r"\|\s*`%s`\s*\|\s*(\d+)\s*\|" % re.escape(key), rubric_text)
        if not match:
            report.error("scoring-rubric.md 权重表缺少 %s 行" % key)
            continue
        rubric_weight = int(match.group(1))
        script_match = re.search(r'"%s":\s*\((\d+),' % re.escape(key), script_text)
        if not script_match:
            report.error("diagnose.py 无法解析 %s 的权重" % key)
            continue
        if int(script_match.group(1)) != rubric_weight:
            report.error("权重不一致：%s 在 rubric 为 %d，在 diagnose.py 为 %s"
                         % (key, rubric_weight, script_match.group(1)))
    report.info("维度 key 与权重三方校验完成（%d 个维度）" % len(EXPECTED_KEYS))


def check_readme(directory: str, report: Report) -> None:
    path = os.path.join(directory, "README.md")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if len(text) < 400:
        report.warn("README.md 偏短，GitHub 首页建议写清安装、用法与目录结构")
    if "SKILL.md" not in text:
        report.warn("README.md 未提到 SKILL.md，使用者可能不知道入口文件")


def validate(directory: str, check_name: bool = True) -> Report:
    report = Report()
    skill_path = os.path.join(directory, "SKILL.md")
    if not os.path.isfile(skill_path):
        report.error("在 %s 下找不到 SKILL.md" % os.path.abspath(directory))
        return report
    with open(skill_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    data, body = parse_frontmatter(text, report)
    check_yaml_scalar_safety(_frontmatter_lines(text), report)
    check_frontmatter(data, body, directory, report, check_name=check_name)
    check_files(directory, report)
    check_key_consistency(directory, report)
    check_readme(directory, report)
    return report


def find_skill_dir(directory: str) -> Optional[str]:
    """在目录下定位技能包：优先当前目录，其次唯一的含 SKILL.md 的一级子目录。

    便于在技能库仓库根直接运行 `python <skill>/scripts/validate_skill.py`。
    """
    if os.path.isfile(os.path.join(directory, "SKILL.md")):
        return directory
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return None
    candidates = [
        os.path.join(directory, name)
        for name in entries
        if not name.startswith(".")
        and os.path.isdir(os.path.join(directory, name))
        and os.path.isfile(os.path.join(directory, name, "SKILL.md"))
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="validate_skill.py",
                                     description="校验 Agent Skills 技能包结构与一致性")
    parser.add_argument("directory", nargs="?",
                        help="技能目录（省略时校验当前目录，并按技能库仓库模式跳过目录名校验）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--name", metavar="NAME",
                        help="以 NAME 作为技能名校验，并跳过“目录名必须等于 name”检查。"
                             "用于校验技能库仓库中的技能（如 validate_skill.py . --name game-fit-advisor）")
    args = parser.parse_args(argv)

    # 显式给了目录 → 严格按规范校验（目录名必须等于 name）；
    # 没给目录或显式 --name → 按技能库仓库模式放宽目录名要求。
    check_name = True
    directory = os.path.abspath(args.directory or ".")
    if args.directory is None:
        check_name = False
        discovered = find_skill_dir(directory)
        if discovered:
            directory = discovered
    if args.name:
        check_name = False
        if not NAME_PATTERN.match(args.name):
            print("参数错误：--name 只允许小写字母、数字与单连字符：%r" % args.name, file=sys.stderr)
            return 2
    report = validate(directory, check_name=check_name)
    if args.name:
        report.info("校验目标技能名（--name）：%s" % args.name)

    if args.json:
        print(json.dumps({
            "directory": directory,
            "ok": not report.errors,
            "errors": report.errors,
            "warnings": report.warnings,
            "infos": report.infos,
        }, ensure_ascii=False, indent=2))
    else:
        print("校验目录：%s" % directory)
        for message in report.infos:
            print("  [信息] %s" % message)
        for message in report.warnings:
            print("  [警告] %s" % message)
        for message in report.errors:
            print("  [错误] %s" % message)
        print("-" * 48)
        if report.errors:
            print("结果：失败（%d 个错误，%d 个警告）" % (len(report.errors), len(report.warnings)))
        else:
            print("结果：通过（0 个错误，%d 个警告）" % len(report.warnings))

    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
