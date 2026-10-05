---
name: github-skill-publisher
description: 把一个本地 Agent Skill（含 SKILL.md 的目录）或提示词项目发布到 GitHub。当用户说“上传到 GitHub / 推到仓库 / 建仓库发布 skill / commit 并 push / 帮我提交到 GitHub”，或需要在推送前检查隐私信息（真名、真实邮箱）、修正提交作者、排查 push 被拒与 GitHub Actions 失败时使用。覆盖空仓库导致的 push 拒绝、rebase/merge 冲突、PowerShell 引号与编码陷阱、git 身份缺失、历史里的邮箱泄露、CI 路径与仓库结构不匹配等具体故障。English: Publish a local Agent Skill or prompt project to GitHub, including pre-publish privacy checks, commit-identity fixes, push-rejection and CI-failure troubleshooting.
license: MIT
compatibility: 需要本机已装 git 并能访问 GitHub；预检脚本仅依赖 Python 3.9+ 标准库。推送时会用到 GitHub 凭据（浏览器登录或 Personal Access Token）。
metadata:
  author: thewal-ker
  version: "1.0.0"
  language: zh-CN
  tags: github, git, 发布, agent-skill, ci, 隐私检查
---

# GitHub Skill 发布助手

把一个本地技能包（`<skill-name>/SKILL.md`，可含 `references/` `assets/` `scripts/`）安全、可验证地发布到 GitHub。**先预检、再提交、后推送、终校验**，任何一步失败都有对应的处置办法。

真实事故优先：本技能里的每条"陷阱"都来自实际把技能推上 GitHub 时踩过的坑，不是假设。

## 何时用

- 用户要求把某个技能/项目**上传、发布、提交**到 GitHub。
- `git push` 被拒（rejected / stale info / non-fast-forward）。
- GitHub Actions 出现红叉，需要定位是结构、路径还是脚本问题。
- 推送前后要确认**没有泄露真名、真实邮箱**等隐私信息。
- 需要修改已经推送出去的提交作者或署名。

## 铁律（违反必出事故）

1. **先跑预检再提交**：`scripts/publish_prep.py --check`。它会扫出真名、"目录名≠name"、CI 路径不匹配、缺 LICENSE 等问题。本次事故全部由它覆盖。
2. **不在命令行里塞多行文本**：提交信息、含引号/换行的字符串一律**写文件**再 `git commit -F`。PowerShell 解析会截断或报 `did not match any file(s) known to git`。
3. **不把中文/多行内容用 PowerShell 重定向写文件**：会得到 UTF-8 BOM 或 UTF-16，导致脚本解析失败。用 `write` 工具或 Python 写。
4. **推送前检查提交身份**：`git log --format='%an <%ae>'`。GitHub 建仓自带的 `Initial commit` 可能带**你的真实邮箱**。
5. **推送后再从服务器侧校验一次**：`git ls-remote` + `git ls-tree -r origin/main`。本地干净 ≠ 远程正确。
6. **绝不 `git push --force` 到共享分支**；个人仓库需强推时用 `--force-with-lease`，并在 filter-branch 后先重抓远程引用（否则 lease 会因陈旧信息拒绝）。

## 工作流

### 第 0 步：预检（推送前，必须做）

```bash
python <skill>/scripts/publish_prep.py --check --skill-dir <skill-name>
```

检查项：frontmatter 合规（`name` 与目录名一致、`description` 长度）、隐私词（真名，需 `--real-name` 传入）、历史中的真实邮箱、`.gitignore`/`LICENSE` 是否存在、CI 配置里的脚本路径是否与仓库结构一致、是否有临时产物（`*.json`、`__pycache__`）。

把报告里的**每个 [错误] 都修掉**再继续；`[警告]` 逐条判断是否接受。

### 第 1 步：确认仓库与结构

问清（或按已有信息判断）三件事：

| 问题 | 影响 |
|---|---|
| GitHub 上仓库建了吗？是空仓库还是自带 README？ | 空仓库才能直接 push；自带文件会触发 unrelated histories |
| 仓库是**单技能**还是**技能库**（多个技能并列）？ | 决定技能放仓库根还是子目录 |
| 仓库放技能的**子目录名**是什么？ | 必须等于 `SKILL.md` 里的 `name`，否则部分运行时拒绝加载 |

**结构约定**（技能库仓库）：

```text
<repo>/                      # 仓库根：只放仓库级文件
├── README.md                # 仓库首页：技能索引表
├── .gitignore  .gitattributes
├── .github/workflows/validate.yml
└── <skill-name>/            # 技能包，目录名 == frontmatter 的 name
    ├── SKILL.md  README.md  LICENSE
    └── references/  assets/  scripts/
```

### 第 2 步：建立 git 仓库并首次提交

```bash
cd <skill-dir>
git init -b main                       # 不叫 master，省一次重命名
git config user.name "<昵称>"           # 仓库级，避免污染全局
git config user.email "<noreply 邮箱>"
git add -A
git commit -F <信息文件>                # 见铁律 2
```

**优先用 GitHub 的 noreply 邮箱**（`<用户名>@users.noreply.github.com`），这样提交能关联账号又不暴露真实邮箱。

### 第 3 步：接远程并推送

```bash
git remote add origin https://github.com/<用户>/<仓库>.git
git push -u origin main
```

被拒时的处置见 `references/troubleshooting.md`，三种典型情况一句话版：

- `rejected ... (fetch first)` → 远程非空，用**合并**：`git merge origin/main --no-edit --allow-unrelated-histories -X ours`（详见陷阱 2）。
- `stale info` → 本地 remote-tracking 引用过期或被改写，先 `git fetch origin "+refs/heads/*:refs/remotes/origin/*"` 再 `--force-with-lease`。
- `Author identity unknown` → 见陷阱 5，配好 `user.name`/`user.email`（`git rebase`/`commit --amend` 也会要求）。

### 第 4 步：CI 绿灯

技能库仓库的 CI 必须**显式指向技能子目录**，否则 runner 上路径不存在、十几秒就红：

```yaml
- name: Detect skill layout
  run: |
    if [ -f SKILL.md ]; then echo "SKILL_DIR=." >> "$GITHUB_ENV"
    else echo "SKILL_DIR=game-fit-advisor" >> "$GITHUB_ENV"; fi

- run: python "$SKILL_DIR/scripts/validate_skill.py" "$SKILL_DIR"
- run: python -m unittest discover -s "$SKILL_DIR/scripts" -p "test_*.py" -v
```

**推送前必须本地离线复现 CI**：克隆远程 → 覆盖待推送文件 → 逐条执行 workflow 里的命令。步骤见 `references/publish-playbook.md` 的"离线复现 CI"。这一步能在 1 分钟内拦下 90% 的红叉。

### 第 5 步：服务器侧终校验

```bash
git ls-remote origin refs/heads/main          # 服务器上的真实哈希
git fetch origin "+refs/heads/*:refs/remotes/origin/*"
git ls-tree -r --name-only origin/main        # 远程文件树
git log origin/main --format="%h %an <%ae>"   # 远程提交身份
```

与预期不符就回到对应步骤，不要"看起来没问题"就收工。

### 第 6 步：隐私收尾（涉及真名/真实邮箱时）

需要改写已推送历史时，完整流程见 `references/privacy-and-history-rewrite.md`。顺序固定：

1. 工作区里替换真名（`LICENSE`、`SKILL.md` 的 `metadata.author`）。
2. `git filter-branch --env-filter` 重写**全部**提交的作者与提交者。
3. 删除 `refs/original/*` 备份引用 → `git reflog expire --expire=now --all` → `git gc --prune=now`。
4. **重新抓取远程引用**，再 `git push --force-with-lease origin main`。
5. 用 `git log --all` 复查 `@163.com` / `@qq.com` 等真实邮箱是否彻底消失。

## 七类陷阱速查

细节、判据与恢复命令见 `references/troubleshooting.md`。

| # | 症状 | 根因 | 一句话处置 |
|---|---|---|---|
| 1 | `! [rejected] main -> main (fetch first)` | 建仓时勾了 README/LICENSE，远程非空且历史无关 | 合并而非变基：`--allow-unrelated-histories` + 保留己方文件 |
| 2 | 变基后自己的 README 被远程两行桩文件覆盖 | `rebase -X ours` 的 "ours" 指**上游**那一侧 | 用 `git show <原提交>:README.md` 恢复；或用合并方式 |
| 3 | 命令报语法错误 / `did not match any file(s) known to git` | PowerShell 吃掉引号、把多行参数拆开 | 长文本写文件；复杂命令交给 Python 或写脚本 |
| 4 | 脚本读配置文件解析失败、首字符是 `\ufeff` | PowerShell 重定向写了 BOM / UTF-16 | 用 `write` 工具或 Python 写文件；读取端用 `utf-8-sig` |
| 5 | `Author identity unknown` / `Committer identity unknown` | `user.name`/`user.email` 未配置（`--amend`、`rebase` 也会要求） | `git config user.email` 配仓库级身份 |
| 6 | CI 12 秒失败：`can't open file '.../scripts/x.py'` | workflow 假设的目录结构与仓库实际结构不一致 | 加"检测布局"步骤；本地离线复现 CI |
| 7 | 公开仓库的提交历史里出现真实邮箱 | GitHub 建仓自动提交使用账号邮箱 | `filter-branch` 重写 + 清理 + 强推，见第 6 步 |

## 禁止事项

- 不代用户猜测邮箱/昵称后**当作事实**提交；不确定就问，或用明确的占位身份并告知用户如何 `--amend --reset-author` 改回。
- 不在用户没要求时把仓库设为 public，不代填许可证类型之外的法律信息。
- 不因"急着推"跳过预检与终端校验——本次两个 CI 红叉都是跳过校验造成的。
- 不删除、不重置用户仓库里的既有内容，除非用户明确要求；覆盖远程 README 这类操作要先说明。
