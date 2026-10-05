# skillsmallthings

一个随便玩玩 skill 小库，还在学习当中。本仓库收录的 Agent Skill：

| 技能 | 说明 |
|---|---|
| [`game-fit-advisor`](#game-fit-advisor--游戏适配度诊断顾问) | 游戏适配度诊断顾问：判断某款游戏是否适合你 |
| [`github-skill-publisher`](#github-skill-publisher--github-技能发布助手) | GitHub 技能发布助手：推送前预检隐私与结构、排查 push 被拒与 CI 失败 |

---

# game-fit-advisor · 游戏适配度诊断顾问

把一份"聊天式提示词"变成可安装、可验证、可复用的 **Agent Skill**：当你想知道某款游戏到底适不适合自己时，它会用场景化提问替你做一次结构化体检，最后给出 **高 / 中 / 低适配** 的结论和下一步动作（试玩 / 观望 / 放弃）。

> **English TL;DR** — An installable [Agent Skill](https://agentskills.io/specification) that diagnoses whether a specific video game fits a specific player. It asks scenario-based questions in two modules (8 quick gameplay dimensions, or 8 deeper dimensions covering time, hardware, monetization, community, updates, emotion, retention and values), scores the match with a weighted rubric, and returns a high / medium / low fit verdict plus a concrete next step. Works in any agent that supports `SKILL.md` (Claude Code, DSH, Microsoft Agent Framework, and other Agent Skills–compatible runtimes). Prompt-only: no network or extra dependencies required.

---

## 它和原始提示词的区别

| 项目 | 原始提示词（`references/original-prompt.md`） | 本技能包 |
|---|---|---|
| 结构 | 单段纯文本 | `SKILL.md` + `references/` + `assets/` + `scripts/` 渐进披露 |
| 自动触发 | 需手动粘贴 | `name` / `description` 进系统提示，命中意图即加载 |
| 题目 | 16 个问题文本 | 16 个维度 + 每题判定口径（回答 → 匹配/部分匹配/冲突） |
| 结论 | 只有高/中/低三档名词 | 加权评分公式、阈值、**强制覆盖规则**、风险排序规则 |
| 交互 | 原则性描述 | 四类信号（硬约束/否定/犹豫/跳步）各自的确定动作 + 追问上限 |
| 事实核查 | 无 | 三级核实规则，禁止把记忆当事实断言 |
| 可验证 | 无 | `scripts/validate_skill.py` 校验规范与三方一致性；`scripts/diagnose.py` 可跑通算分 |

改动逐条说明见 [`references/original-prompt.md`](references/original-prompt.md)。

---

## 目录结构

```text
skillsmallthings/                   # 仓库根：只放仓库级文件
├── README.md                       # 本文件（仓库首页）
├── .gitignore  .gitattributes
├── .github/workflows/validate.yml  # CI：Python 3.9 / 3.12 上校验 + 测试 + 冒烟测试
└── game-fit-advisor/               # ← 技能包本体，整个目录复制到技能目录即可
    ├── SKILL.md                    # 技能入口：角色、工作流、六步执行顺序
    ├── README.md                   # 技能包内说明（GitHub 上可见）
    ├── LICENSE                     # MIT
    ├── references/
    │   ├── question-bank.md        # 16 个维度：问法 + 判定线索 + 追问
    │   ├── scoring-rubric.md       # 权重、公式、三档阈值、强制覆盖、措辞模板
    │   ├── interaction-rules.md    # 动态调整、追问上限、边界与免责
    │   └── original-prompt.md      # 原始提示词存档 + 改动清单
    ├── assets/
    │   ├── report-template.md      # 高/中/低三份完整报告范例 + 格式硬要求
    │   └── sample-session.md       # 两个模块的完整对话范例（风格基准）
    └── scripts/
        ├── diagnose.py             # 交互式诊断 / 直接算分 / 生成报告
        ├── validate_skill.py       # 校验包结构与文档-脚本一致性
        ├── test_diagnose.py        # 26 项判定逻辑测试
        └── test_validate_skill.py  # 22 项校验器测试（含目录名规则回归）
```

---

## 安装

技能就是"一个含 `SKILL.md` 的目录"，安装 = 放到你的代理会扫描的技能目录里。

```bash
git clone https://github.com/<your-name>/game-fit-advisor.git
```

| 运行时 | 放置位置 |
|---|---|
| Claude Code | `~/.claude/skills/game-fit-advisor/`（个人）或 `<项目>/.claude/skills/game-fit-advisor/`（项目级） |
| DSH | 你的 skills 目录下（目录名须为 `game-fit-advisor`） |
| Microsoft Agent Framework | 传入 `skills_paths` / `AgentSkillsProvider` 的任意目录 |
| 其他 Agent Skills 实现 | 任何扫描 `<dir>/<skill-name>/SKILL.md` 的目录 |

**关键约定**：目录名必须与 frontmatter 里的 `name` 完全一致（`game-fit-advisor`），否则部分实现会拒绝加载。`scripts/validate_skill.py` 会替你检查这一点。

---

## 使用

### 在代理里（主要用法）

装好后直接说人话即可，例如：

```text
《艾尔登法环》适合我吗？我 PS5，每天只有 1 小时。
帮我做《原神》的模块二，我手机上玩，大学生。
这游戏我犹豫要不要买，帮我快速诊断一下。
```

代理会按 `SKILL.md` 的六步走：确认游戏 → 让你选模块 → 每轮 2–3 题提问 → 动态跳过你已否定的维度 → 输出结论 → 问你是否深入。

### 命令行辅助

`scripts/diagnose.py` 只依赖 Python 3.9+ 标准库，用于非交互场景（批量、记录、算分）：

```bash
# 交互式：逐维度输入 y / p / n
python scripts/diagnose.py --game "艾尔登法环" --mode 1

# 直接算分
python scripts/diagnose.py --game "星穹铁道" --mode 2 \
  --answers "core_loop:match,challenge:partial,values:match,payment:conflict"

# 从文件读答案（每行 key:verdict，# 为注释），输出 JSON 并保存报告
python scripts/diagnose.py --game "星露谷物语" --answers-file answers.txt --json --save reports/stardew.md

# 查看题库与权重
python scripts/diagnose.py --list-questions --mode 2
```

判定取值：`match`（匹配）/ `partial`（部分匹配）/ `conflict`（冲突）/ `skip`（跳过），也接受 `y / p / n`、`匹配 / 部分匹配 / 冲突`。

### 自检

```bash
# 本仓库是技能库（根目录名 skillsmallthings ≠ 技能名），所以显式指向技能目录
python game-fit-advisor/scripts/validate_skill.py game-fit-advisor      # 结构与一致性校验（严格）
python -m unittest discover -s game-fit-advisor/scripts -p "test_*.py"  # 53 项行为测试
```

也可以不带参数运行校验脚本：它会自动定位唯一的技能子目录，并放宽"目录名须等于 name"检查；显式传入技能目录时则严格校验该规则。

校验 frontmatter 规范符合性、目录名规则、推荐文件、以及 **维度 key 与权重在题库、评分标准、脚本三处是否一致**。修改任何一处后都应重跑。仓库已带 GitHub Actions（`.github/workflows/validate.yml`），在 Python 3.9 与 3.12 上跑校验、测试与冒烟测试。

---

## 诊断机制速览

**模块一 · 快速玩法诊断（8 维）**：核心玩法类型、操作难度、游戏节奏、社交需求、挑战类型、内容消耗、沉浸感来源、时间投入。

**模块二 · 深度全面分析（8 维）**：时间成本、硬件要求、付费模式、社区氛围、更新频率、情感体验、长线留存、价值观契合。

**判定与评分**

```text
适配率 = Σ(权重 × 系数) / Σ(权重)     系数：匹配 1.0 · 部分匹配 0.5 · 冲突 0
权重：核心玩法类型、挑战类型、价值观契合 = 2，其余 = 1
```

| 结论 | 条件 | 行动建议 |
|---|---|---|
| 高适配 | 适配率 ≥ 80% 且无关键维度冲突 | 直接试玩 / 入手 |
| 中适配 | 55%–79%，或高分但有 1 个可调整冲突 | 先试玩、看多立场评测、等折扣 |
| 低适配 | < 55%，或 ≥ 2 个关键冲突 | 提醒痛点，给替代方向 |

**强制覆盖**：`values`（价值观契合）或 `core_loop`（核心玩法）为冲突时，即使适配率 ≥ 80% 也不得报"高适配"。理由很实在——玩法和底线不对味，靠习惯补不回来。

---

## 设计取向

- **只诊断匹配度，不评价游戏好坏**。同一款游戏对不同用户的结论可以完全相反。
- **场景化提问**。凡出现"节奏""沉浸感""肝"这类词，必须紧跟一句具体情境，例如"若 BOSS 战连续失败 3 次，你会感到激励还是烦躁？"。
- **不猜**。用户没说清的维度记"部分匹配（信息不足）"并列进"还需确认"，绝不写成匹配。
- **有上限**。单场诊断 ≤ 11 题、≤ 4 轮提问，超限就用已有信息出结论并标注置信度。
- **不替用户做消费决定**，不催购买，不承诺"你一定喜欢"。

---

## 自定义

| 想改什么 | 改哪里 |
|---|---|
| 增删维度 | `references/question-bank.md` + `references/scoring-rubric.md` 权重表 + `scripts/diagnose.py` 的 `DIMENSIONS`，然后跑 `validate_skill.py` |
| 调整阈值 / 权重 | `references/scoring-rubric.md`（脚本里的阈值在 `compute()`） |
| 换语言 | `SKILL.md` 与 `references/` 均为中文；翻译时保留 `name`（不可改）与结构 |
| 加自己的画像预设 | 复制 `assets/sample-session.md` 的写法，追加到 `assets/` |

---

## 许可与免责

MIT，见 [LICENSE](LICENSE)。

本技能是**决策辅助**，不是专业建议：结论基于用户自述偏好与顾问对游戏设计的理解，游戏事实请以官方商店页、最新公告与实机体验为准。涉及现实支出、家庭关系或未成年人的场景，请自行判断。

---

# github-skill-publisher · GitHub 技能发布助手

把"把一个技能推上 GitHub"这件事本身也做成了技能。它不是 `git push` 的包装，而是把发布过程中**真正会卡住人的环节**变成可执行的检查与恢复步骤。

**它内置的预检工具**（`precheck.py`）在推送前扫描：

- `SKILL.md` 合规：`name` 字符集与长度、**目录名必须等于 name**、`description` 长度
- **CI 里引用的脚本路径在仓库里是否真的存在** —— 这正是本仓库当初 CI 红叉的根因
- 仓库根 `README.md` / `.gitignore` / `.gitattributes` 是否齐全
- 文件里的真名、真实邮箱；**提交历史里是否混入真实邮箱**
- 是否把 `__pycache__`、试跑产物 JSON、日志等临时文件提交进了仓库

**它记录的七类真实故障**（每类都给出判据与恢复命令）：

| 症状 | 根因 |
|---|---|
| `! [rejected] main -> main (fetch first)` | 建仓时勾了 README，远程非空且历史无关 |
| 变基后自己的 README 被远程桩文件覆盖 | `rebase -X ours` 的 "ours" 指**上游**那一侧 |
| 命令报语法错误 / `did not match any file(s) known to git` | PowerShell 吃掉引号、拆散多行参数 |
| 脚本解析失败、首字符是 `\ufeff` | PowerShell 重定向写了 BOM / UTF-16 |
| `Author identity unknown` | `user.name/email` 未配置（`--amend`、`rebase` 同样要求） |
| CI 12 秒失败：路径不存在 | workflow 假设的目录结构与仓库实际结构不一致 |
| 公开仓库历史里出现真实邮箱 | GitHub 建仓自动提交使用账号邮箱 |

另附 `commit_msg.py`：以 UTF-8 无 BOM + LF 写提交信息再用 `git commit -F` 提交，一次避开"引号"与"编码"两个坑。

- 入口：[`github-skill-publisher/SKILL.md`](github-skill-publisher/SKILL.md)
- 逐步命令清单：[`references/publish-playbook.md`](github-skill-publisher/references/publish-playbook.md)
- 故障速查：[`references/troubleshooting.md`](github-skill-publisher/references/troubleshooting.md)
- 隐私与历史改写：[`references/privacy-and-history-rewrite.md`](github-skill-publisher/references/privacy-and-history-rewrite.md)

```bash
# 推送前预检（本仓库）
python github-skill-publisher/scripts/precheck.py --repo .
python -m unittest discover -s github-skill-publisher/scripts -p "test_*.py"
```

MIT，见 [LICENSE](github-skill-publisher/LICENSE)。
