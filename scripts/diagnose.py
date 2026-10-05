#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""游戏适配度诊断顾问 —— 判定与报告生成脚本。

只依赖 Python 3.9+ 标准库。

用法示例：

    # 交互式诊断（逐步提问 + 生成报告）
    python diagnose.py --game "艾尔登法环"

    # 直接算分（非交互）
    python diagnose.py --game "星穹铁道" --mode 1 \
        --answers "core_loop:match,controls:partial,pace:conflict,social:match"

    # 从文件读取答案，输出 JSON，保存 Markdown 报告
    python diagnose.py --game "星露谷物语" --answers-file answers.txt --json --save report.md

    # 列出题库
    python diagnose.py --list-questions --mode 2

判定口径见 references/scoring-rubric.md。脚本只做机械计算；
最终结论应由代理结合完整对话信息给出。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# 维度定义：key -> (权重, 中文名, 模块)
# 与 references/question-bank.md、references/scoring-rubric.md 保持一致。
# scripts/validate_skill.py 会校验三方同步。
# --------------------------------------------------------------------------

DIMENSIONS: Dict[str, Tuple[int, str, int]] = {
    # 模块一
    "core_loop": (2, "核心玩法类型", 1),
    "controls": (1, "操作难度", 1),
    "pace": (1, "游戏节奏", 1),
    "social": (1, "社交需求", 1),
    "challenge": (2, "挑战类型", 1),
    "content": (1, "内容消耗", 1),
    "immersion": (1, "沉浸感来源", 1),
    "time_budget": (1, "时间投入", 1),
    # 模块二
    "time_cost": (1, "时间成本", 2),
    "hardware": (1, "硬件要求", 2),
    "payment": (1, "付费模式", 2),
    "community": (1, "社区氛围", 2),
    "update": (1, "更新频率", 2),
    "emotion": (1, "情感体验", 2),
    "retention": (1, "长线留存", 2),
    "values": (2, "价值观契合", 2),
}

# 关键维度：其冲突会把结论压到"低适配"
CRITICAL_KEYS = ("core_loop", "challenge", "values")

COEFFICIENT = {"match": 1.0, "partial": 0.5, "conflict": 0.0}

VERDICT_SYMBOL = {"match": "✅ 匹配", "partial": "⚠️ 部分匹配", "conflict": "❌ 冲突"}

ANSWER_ALIASES = {
    "match": "match", "m": "match", "1": "match", "yes": "match", "y": "match",
    "匹配": "match", "符合": "match", "高": "match",
    "partial": "partial", "p": "partial", "0.5": "partial", "maybe": "partial",
    "部分匹配": "partial", "部分": "partial", "中": "partial", "还行": "partial",
    "conflict": "conflict", "c": "conflict", "0": "conflict", "no": "conflict", "n": "conflict",
    "冲突": "conflict", "不匹配": "conflict", "低": "conflict", "不能接受": "conflict",
    "skip": "skip", "s": "skip", "-": "skip", "跳过": "skip", "未知": "skip", "": "skip",
}

# 允许通过 --answers 覆盖权重：key:verdict:weight
QUESTION_ORDER = {1: [k for k, v in DIMENSIONS.items() if v[2] == 1],
                  2: [k for k, v in DIMENSIONS.items() if v[2] == 2]}


class InputError(ValueError):
    """用户输入无法解析。"""


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def normalize_verdict(raw: str) -> str:
    # 去掉 BOM 与零宽字符（管道/文件重定向常见）
    key = raw.strip().lstrip("\ufeff\u200b").strip().lower()
    if key in ANSWER_ALIASES:
        return ANSWER_ALIASES[key]
    raise InputError(
        "无法识别的判定 %r；可用值：match/partial/conflict/skip（或 匹配/部分匹配/冲突/跳过、y/n/s）" % raw
    )


def parse_answers(spec: str) -> Dict[str, str]:
    """解析 'core_loop:match,controls:partial' 形式的答案串。"""
    answers: Dict[str, str] = {}
    for chunk in spec.replace("；", ",").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk and "：" in chunk:
            chunk = chunk.replace("：", ":")
        if ":" not in chunk:
            raise InputError("答案项 %r 缺少冒号，应形如 core_loop:match" % chunk)
        key, _, value = chunk.partition(":")
        key = key.strip()
        if key not in DIMENSIONS:
            raise InputError("未知维度 key %r；运行 --list-questions 查看可用 key" % key)
        answers[key] = normalize_verdict(value)
    return answers


def parse_answers_file(path: str) -> Dict[str, str]:
    """读取答案文件：每行 `key:verdict`，支持 # 注释与空行。"""
    answers: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line and "：" in line:
                line = line.replace("：", ":")
            if ":" not in line:
                raise InputError("第 %d 行格式错误：%r（应形如 core_loop:match）" % (lineno, line))
            key, _, value = line.partition(":")
            key = key.strip()
            if key not in DIMENSIONS:
                raise InputError("第 %d 行未知维度 key：%r" % (lineno, key))
            answers[key] = normalize_verdict(value)
    return answers


# --------------------------------------------------------------------------
# 计算
# --------------------------------------------------------------------------

def compute(answers: Dict[str, str], weights: Optional[Dict[str, int]] = None) -> dict:
    """按 scoring-rubric 计算得分、适配率、结论与风险排序。"""
    scored = {k: v for k, v in answers.items() if v in COEFFICIENT}
    if not scored:
        raise InputError("没有任何有效判定，至少需要一个 match/partial/conflict")

    rows: List[dict] = []
    earned = 0.0
    total = 0.0
    for key in QUESTION_ORDER[1] + QUESTION_ORDER[2]:
        if key not in scored:
            continue
        weight = (weights or {}).get(key, DIMENSIONS[key][0])
        verdict = scored[key]
        row_earned = weight * COEFFICIENT[verdict]
        earned += row_earned
        total += weight
        rows.append({
            "key": key,
            "label": DIMENSIONS[key][1],
            "weight": weight,
            "verdict": verdict,
            "verdict_display": VERDICT_SYMBOL[verdict],
            "critical": key in CRITICAL_KEYS,
            "earned": round(row_earned, 2),
        })

    ratio = earned / total if total else 0.0
    percent = round(ratio * 100, 1)

    conflicts = [r for r in rows if r["verdict"] == "conflict"]
    critical_conflicts = [r for r in conflicts if r["critical"]]
    partials = [r for r in rows if r["verdict"] == "partial"]

    if ratio >= 0.80 and not critical_conflicts:
        level = "high"
    elif ratio < 0.55 or len(critical_conflicts) >= 2:
        level = "low"
    else:
        level = "medium"

    # 强制覆盖：非关键冲突过多时不得报高适配
    if level == "high" and len(conflicts) >= 3:
        level = "medium"

    recommendation = {
        "high": "推荐直接试玩或购买。建议给出一个具体入手动作（试玩版 / 免费周末 / 云游戏试机 / 折扣节点）。",
        "medium": "建议先体验试玩版或查看多篇不同立场的评测，再决定长期投入。给出一个低成本验证动作 + 观察窗口。",
        "low": "提醒潜在痛点，避免浪费资源。给出替代方向（描述偏好特征，而非硬推某一款）。",
    }[level]

    skipped = [k for k, v in answers.items() if v == "skip"]
    return {
        "ratio": round(ratio, 4),
        "percent": percent,
        "earned": round(earned, 2),
        "total": total,
        "level": level,
        "level_cn": {"high": "高适配", "medium": "中适配", "low": "低适配"}[level],
        "rows": rows,
        "conflicts": [r["key"] for r in conflicts],
        "critical_conflicts": [r["key"] for r in critical_conflicts],
        "partials": [r["key"] for r in partials],
        "skipped": skipped,
        "counts": {
            "match": sum(1 for r in rows if r["verdict"] == "match"),
            "partial": len(partials),
            "conflict": len(conflicts),
        },
        "recommendation": recommendation,
        "disclaimer": "以上基于用户自述的偏好；游戏事实请以官方商店页与实机体验为准。",
    }


def rank_risks(result: dict, limit: int = 3) -> List[str]:
    """风险排序：关键冲突 > 高权重冲突 > 其余冲突 > 部分匹配 > 信息不足。"""
    priority = {"conflict": 0, "partial": 1}
    items = [r for r in result["rows"] if r["verdict"] in priority]
    items.sort(key=lambda r: (
        priority[r["verdict"]],
        0 if r["critical"] else 1,
        -r["weight"],
    ))
    risks: List[str] = []
    for row in items[:limit]:
        tag = "冲突" if row["verdict"] == "conflict" else "部分匹配"
        star = "（关键维度）" if row["critical"] else ""
        risks.append("%s：判定为%s%s，权重 %d" % (row["label"], tag, star, row["weight"]))
    if not risks:
        risks.append("本次诊断未发现冲突项或部分匹配项。")
    if result["skipped"]:
        risks.append("（另）未诊断维度：%s，会降低结论置信度"
                     % "、".join(DIMENSIONS[k][1] for k in result["skipped"]))
    return risks


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def display_width(text: str) -> int:
    """终端显示宽度：CJK 全角字符按 2 列计，用于对齐表格。"""
    width = 0
    for char in text:
        code = ord(char)
        wide = (
            0x1100 <= code <= 0x115F
            or 0x2E80 <= code <= 0xA4CF
            or 0xAC00 <= code <= 0xD7A3
            or 0xF900 <= code <= 0xFAFF
            or 0xFE30 <= code <= 0xFE6F
            or 0xFF00 <= code <= 0xFF60
            or 0xFFE0 <= code <= 0xFFE6
            or 0x1F300 <= code <= 0x1FAFF
        )
        width += 2 if wide else 1
    return width


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def render_text(game: str, mode: Optional[int], result: dict) -> str:
    lines: List[str] = []
    title = "适配度诊断结论：%s" % game
    if mode:
        title += "（模块%s）" % ("一" if mode == 1 else "二")
    lines.append(title)
    lines.append("=" * 48)
    lines.append("结论：%s" % result["level_cn"])
    lines.append("适配率：%s%%（得分 %s / 满分 %s）" % (result["percent"], result["earned"], result["total"]))
    lines.append("判定分布：匹配 %d · 部分匹配 %d · 冲突 %d"
                 % (result["counts"]["match"], result["counts"]["partial"], result["counts"]["conflict"]))
    lines.append("")
    headers = [("维度", 16), ("权重", 6), ("判定", 14), ("得分", 6)]
    lines.append(" ".join(pad(h, w) for h, w in headers))
    lines.append("-" * 48)
    for row in result["rows"]:
        cells = [
            pad(row["label"], 16),
            pad(str(row["weight"]), 6),
            pad(row["verdict_display"], 14),
            pad(str(row["earned"]), 6),
        ]
        lines.append(" ".join(cells))
    lines.append("")
    lines.append("最需要留意的 3 点")
    for index, risk in enumerate(rank_risks(result), 1):
        lines.append("  %d. %s" % (index, risk))
    lines.append("")
    lines.append("下一步建议：%s" % result["recommendation"])
    if result["critical_conflicts"]:
        lines.append("关键冲突：%s" % "、".join(DIMENSIONS[k][1] for k in result["critical_conflicts"]))
    lines.append("")
    lines.append(result["disclaimer"])
    return "\n".join(lines)


def render_markdown(game: str, mode: Optional[int], result: dict) -> str:
    heading = "## 适配度诊断结论：%s" % game
    if mode:
        heading += "（模块%s）" % ("一" if mode == 1 else "二")
    lines = [heading, "", "**结论：%s**" % result["level_cn"], ""]
    lines.append("| 维度 | 权重 | 判定 | 得分 |")
    lines.append("|---|---|---|---|")
    for row in result["rows"]:
        lines.append("| %s | %d | %s | %s |"
                     % (row["label"], row["weight"], row["verdict_display"], row["earned"]))
    lines.append("")
    lines.append("**适配率**：%s%%（得分 %s / 满分 %s）" % (result["percent"], result["earned"], result["total"]))
    lines.append("")
    lines.append("**最需要留意的 3 点**")
    lines.append("")
    for index, risk in enumerate(rank_risks(result), 1):
        lines.append("%d. %s" % (index, risk))
    lines.append("")
    lines.append("**下一步建议**：%s" % result["recommendation"])
    lines.append("")
    lines.append("**还需确认**：%s" % ("无" if not result["skipped"] else
                                      "、".join(DIMENSIONS[k][1] for k in result["skipped"])))
    lines.append("")
    lines.append(result["disclaimer"])
    return "\n".join(lines)


def list_questions(mode: Optional[int]) -> str:
    modes = [mode] if mode else [1, 2]
    chunks: List[str] = []
    for current in modes:
        chunks.append("模块%s：" % ("一" if current == 1 else "二"))
        for index, key in enumerate(QUESTION_ORDER[current], 1):
            weight, label, _ = DIMENSIONS[key]
            star = "（关键维度）" if key in CRITICAL_KEYS else ""
            chunks.append("  %2d. %-14s %-12s 权重 %d%s" % (index, key, label, weight, star))
        chunks.append("")
    chunks.append("判定取值：match（匹配）/ partial（部分匹配）/ conflict（冲突）/ skip（跳过）")
    return "\n".join(chunks)


# --------------------------------------------------------------------------
# 交互
# --------------------------------------------------------------------------

def ask(prompt: str, allow_skip: bool = True) -> str:
    while True:
        try:
            raw = input(prompt).strip()
        except EOFError:
            return "skip"
        if not raw and allow_skip:
            return "skip"
        try:
            return normalize_verdict(raw)
        except InputError as exc:
            print("  ! %s" % exc)


def interactive(game: str, mode: int) -> Dict[str, str]:
    print("游戏：%s   模式：模块%s" % (game, "一" if mode == 1 else "二"))
    print("对每个维度填入判定：y=匹配  p=部分匹配  n=冲突  回车=跳过")
    print("详细问法与判定口径见 references/question-bank.md\n")
    answers: Dict[str, str] = {}
    for index, key in enumerate(QUESTION_ORDER[mode], 1):
        weight, label, _ = DIMENSIONS[key]
        star = "（关键维度）" if key in CRITICAL_KEYS else ""
        answers[key] = ask("  %d. %s%s [y/p/n/回车] " % (index, label, star))
    return answers


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diagnose.py",
        description="游戏适配度诊断顾问：判定计算与报告生成（纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python diagnose.py --game \"艾尔登法环\" --answers \"core_loop:match,challenge:partial\"",
    )
    parser.add_argument("--game", help="游戏名称（报告标题用）")
    parser.add_argument("--mode", type=int, choices=(1, 2), help="诊断模块：1=快速玩法诊断，2=深度全面分析")
    parser.add_argument("--answers", help="答案串，如 core_loop:match,controls:partial")
    parser.add_argument("--answers-file", help="答案文件路径，每行 key:verdict")
    parser.add_argument("--list-questions", action="store_true", help="列出题库并退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出判定结果")
    parser.add_argument("--markdown", action="store_true", help="以 Markdown 输出报告")
    parser.add_argument("--save", metavar="PATH", help="把报告写入文件（按扩展名选择 md 或 txt）")
    parser.add_argument("--non-interactive", action="store_true", help="缺少答案时直接报错，不进入交互")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_questions:
        print(list_questions(args.mode))
        return 0

    game = args.game or "未命名游戏"
    mode = args.mode

    try:
        if args.answers_file:
            answers = parse_answers_file(args.answers_file)
        elif args.answers:
            answers = parse_answers(args.answers)
        elif args.non_interactive:
            parser.error("缺少答案：请使用 --answers 或 --answers-file（或去掉 --non-interactive 进入交互）")
            return 2
        else:
            # 无答案时进入交互；stdin 被重定向（管道 / 文件）时同样按行读取。
            answers = interactive(game, mode or 1)
    except InputError as exc:
        print("输入错误：%s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("无法读取答案文件：%s" % exc, file=sys.stderr)
        return 1

    try:
        result = compute(answers)
    except InputError as exc:
        print("无法计算：%s" % exc, file=sys.stderr)
        return 1

    if args.json:
        payload = {"game": game, "mode": mode, "risks": rank_risks(result)}
        payload.update(result)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(render_markdown(game, mode, result))
    else:
        print(render_text(game, mode, result))

    if args.save:
        path = args.save
        content = render_markdown(game, mode, result) if path.lower().endswith(".md") \
            else render_text(game, mode, result)
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content + "\n")
        print("\n报告已保存：%s" % path, file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
