# github-skill-publisher

把一个本地 **Agent Skill**（含 `SKILL.md` 的目录）发布到 GitHub —— 顺便把"发布过程中真正会踩的坑"变成自动检查。

> **English TL;DR** — An installable [Agent Skill](https://agentskills.io/specification) that walks an agent through publishing a local skill (or prompt project) to GitHub: pre-publish privacy/consistency checks, commit-identity setup, push, CI verification, and recovery from the failures that actually happen (rejected pushes on non-empty repos, rebase `-X ours` semantics, PowerShell quoting/encoding traps, missing git identity, real email leaked into commit history, CI path/layout mismatch).

## 它解决什么问题

把技能推上 GitHub 时，真正浪费时间的不是 `git push` 本身，而是这一串意外：

| 症状 | 根因 | 本技能给出的处置 |
|---|---|---|
| `! [rejected] main -> main (fetch first)` | 建仓时勾了 README，远程非空且历史无关 | 用合并而非变基，两条历史都保留 |
| 变基后自己的 README 被远程两行桩文件覆盖 | **`rebase -X ours` 的 "ours" 指上游那一侧** | 从原提交恢复，或改用合并 |
| 命令报语法错误 / `did not match any file(s) known to git` | PowerShell 吃掉引号、拆散多行参数 | 长文本写文件，`git commit -F` |
| 脚本解析失败、首字符是 `\ufeff` | PowerShell 重定向写了 BOM / UTF-16 | 写入端与读取端各有对策 |
| `Author identity unknown` | `user.name/email` 未配置（`--amend`、`rebase` 也要） | 仓库级身份配置 + noreply 邮箱 |
| CI 12 秒失败：路径不存在 | workflow 假设的目录结构与仓库实际结构不一致 | 布局自适应 workflow + 离线复现 CI |
| 公开仓库历史里出现真实邮箱 | GitHub 建仓自动提交使用账号邮箱 | `filter-branch` 重写 + 清理 + 强推 |
| `--force-with-lease` 报 `stale info` | 本地 remote-tracking 引用被改写或过期 | 先强制对齐远程引用再强推 |

细节见 [`references/troubleshooting.md`](references/troubleshooting.md)。

## 目录结构

```text
github-skill-publisher/
├── SKILL.md                                  # 入口：六步工作流 + 铁律 + 陷阱速查
├── README.md  LICENSE
├── references/
│   ├── publish-playbook.md                   # 逐步命令清单（含离线复现 CI）
│   ├── troubleshooting.md                    # 症状 → 根因 → 判据 → 处置
│   └── privacy-and-history-rewrite.md        # 真名/真邮箱清理与历史改写
└── scripts/
    ├── precheck.py                           # 推送前预检（本技能的核心工具）
    ├── commit_msg.py                         # 跨 shell 安全的提交信息工具
    └── test_precheck.py                      # 34 项测试
```

## 安装

把**整个 `github-skill-publisher/` 目录**复制到代理的技能目录下，目录名保持不变（必须等于 frontmatter 的 `name`）：

| 运行时 | 放置位置 |
|---|---|
| Claude Code | `~/.claude/skills/github-skill-publisher/` |
| DSH | 你的 skills 目录下 |
| Microsoft Agent Framework | 传给 `skills_paths` / `AgentSkillsProvider` 的目录 |

## 使用

### 在代理里

```text
把这个技能包上传到 GitHub。
帮我推送到 https://github.com/me/my-skills。
push 被拒了，报 rejected (fetch first)，帮我看看。
CI 红了，检查一下是不是结构问题。
把仓库历史里的真实邮箱清掉。
```

代理会先跑预检、再提交推送、推送后从服务器侧校验，最后确认 CI。

### 命令行：推送前预检

```bash
# 单技能仓库（SKILL.md 在根）或技能库仓库都能用
python scripts/precheck.py --repo . --real-name "你的真名" --real-email "you@163.com"

# 机器可读
python scripts/precheck.py --repo . --json

# 指定技能目录（默认自动发现含 SKILL.md 的子目录）
python scripts/precheck.py --repo . --skill-dir my-skill
```

检查内容：

- `SKILL.md` frontmatter 合规（`name` 字符集/长度、**目录名 == name**、`description` 长度）
- 技能包内 `README.md` / `LICENSE` 是否齐全
- **CI 里引用的脚本路径在仓库里是否真的存在**（本次事故的核心检查项）
- 仓库根 `README.md` / `.gitignore` / `.gitattributes`
- 文件里的真名、真实邮箱；提交历史里的提交身份
- 被 git 跟踪的临时产物（`__pycache__`、试跑产物 JSON、日志）

`[错误]` 必须修完再推；`[警告]` 逐条判断。

### 命令行：提交信息

```bash
python scripts/commit_msg.py status                                  # 看改动 + 建议标题
python scripts/commit_msg.py build --title "fix(ci): 修正校验路径" --body-file notes.md
python scripts/commit_msg.py build --title "feat: 首个技能" --commit   # 写完直接提交
```

它以 **UTF-8 无 BOM + LF** 写 `.git/COMMIT_MSG.txt`，再用 `git commit -F` 提交——同时避开"PowerShell 吃引号"和"重定向写 BOM"两个坑。

### 自检

```bash
python -m unittest discover -s scripts -p "test_*.py"   # 34 项测试
```

仓库已带 GitHub Actions（`.github/workflows/validate.yml`），在 Python 3.9 / 3.12 上跑上述测试。

## 设计取向

- **先预检再提交**：本次两个 CI 红叉都是"跳过校验直接推"造成的，所以预检是硬性第一步。
- **失败可恢复**：每条陷阱都给"判据 + 处置 + 验证"，而不是只说"别这么做"。
- **不越权**：不编造用户的真实邮箱、不擅自 force push 到共享分支、不静默覆盖远程既有内容。
- **跨 shell**：所有脚本纯标准库、路径用相对/可传参形式，Windows PowerShell 与 Ubuntu bash 都能跑。

## 许可

MIT，见 [LICENSE](LICENSE)。
