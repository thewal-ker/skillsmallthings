# game-fit-advisor

游戏适配度诊断顾问 —— 一个可安装的 [Agent Skill](https://agentskills.io/specification)：判断**某款具体游戏**是否适合**某位具体玩家**。

- **入口**：`SKILL.md`（frontmatter + 六步工作流）
- **判定细则**：`references/scoring-rubric.md`（权重、公式、三档阈值、强制覆盖规则）
- **题库与判定口径**：`references/question-bank.md`（模块一 8 维、模块二 8 维）
- **交互规则**：`references/interaction-rules.md`（动态调整、追问上限、边界免责）
- **报告与范例**：`assets/report-template.md`、`assets/sample-session.md`
- **可选脚本**：`scripts/diagnose.py`（算分与生成报告）、`scripts/validate_skill.py`（校验本包）

## 安装

把**整个 `game-fit-advisor/` 目录**复制到代理的技能目录下，目录名保持不变（必须等于 frontmatter 里的 `name`）：

| 运行时 | 放置位置 |
|---|---|
| Claude Code | `~/.claude/skills/game-fit-advisor/` 或 `<项目>/.claude/skills/game-fit-advisor/` |
| DSH | 你的 skills 目录下 |
| Microsoft Agent Framework | 传给 `skills_paths` / `AgentSkillsProvider` 的目录 |

## 用法

装好后直接说人话：

```text
《艾尔登法环》适合我吗？我 PS5，每天只有 1 小时。
帮我做《原神》的模块二，我手机上玩。
这游戏我犹豫要不要买，帮我快速诊断一下。
```

## 命令行走查

```bash
python scripts/diagnose.py --game "杀戮尖塔" --mode 1 \
  --answers "core_loop:match,controls:match,pace:match,challenge:partial" --non-interactive
python scripts/validate_skill.py .          # 校验本包结构（目录名须等于 name）
python -m unittest discover -s scripts -p "test_*.py"
```

完整说明、设计取向与自定义方式见**仓库根目录的 README.md**。

## 许可

MIT，见 `LICENSE`。
