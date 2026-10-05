# 故障速查：症状 → 根因 → 处置

每条都来自真实事故。先按"症状"定位，再按"判据"确认是同一回事，最后照"处置"执行。

---

## 陷阱 1 · push 被拒：`rejected ... (fetch first)`

**症状**

```text
! [rejected]        main -> main (fetch first)
error: failed to push some refs to 'https://github.com/...'
hint: Updates were rejected because the remote contains work that you do not
hint: have locally.
```

**根因**：远程仓库**不是空的**。在 GitHub 建仓时勾了 "Add a README file" / "Add .gitignore" / "Choose a license"，GitHub 会替你生成一个 `Initial commit`，它与你本地历史**完全无关**（no common ancestor）。

**判据**

```bash
git fetch origin
git log --oneline --graph --all -5      # 会看到两条互不相连的历史
git ls-tree -r --name-only origin/main  # 远程有哪些文件
```

**处置（推荐：合并，保留双方历史且无需强推）**

```bash
# 仅当远程文件（一般是 README 桩）可以覆盖时用 -X ours
git merge origin/main --no-edit --allow-unrelated-histories -X ours
git push -u origin main
# 输出应形如：c9bbe67..52cbcc0  main -> main
```

- 如果远程那个文件**有价值**（用户自己写的 README）：合并后手动把它的内容并回你的文件，再 `git commit --amend --no-edit`。
- 如果确定远程内容全是垃圾且只有你一个人用这个仓库，也可以 `git push --force-with-lease`，但**必须**先说明会丢弃远程那一条提交。

**不要**直接 `git rebase origin/main`：变基到无关历史上会把你的文件逐个重放，撞名文件（`README.md`）会冲突，而 rebase 的 `-X ours` 语义见陷阱 2，很容易把用户的内容盖掉或把自己的盖掉。

---

## 陷阱 2 · 变基后自己的文件被远程内容覆盖

**症状**：变基"成功"了，但 `README.md` 变成了远程那两行桩文本；`git rebase --continue` 又卡住不动。

**根因**：`git rebase -X ours` 里的 **"ours" 指上游（upstream）那一侧**，不是你正在重放的提交。所以在变基时 `-X ours` = 保留**远程**版本，与直觉相反。（在 `merge` 时 "ours" 才是你的分支。）

**判据**

```bash
git show :0:README.md | head -3        # 看看索引里现在是谁的版本
git show <你的原提交>:README.md | head -3  # 你的版本还在，需要恢复
git rev-parse --short main             # main 还没动，安全
```

**处置（恢复到你的版本并完成）**

```bash
# 用 Python 写文件，避免 PowerShell 的重定向编码问题（见陷阱 4）
python -c "import subprocess,pathlib; pathlib.Path('README.md').write_bytes(subprocess.run(['git','show','<原提交>:README.md'],capture_output=True).stdout)"
git add README.md
git -c core.editor=true rebase --continue
```

**更省事的替代**：直接放弃变基，改走陷阱 1 的合并方案。

```bash
git rebase --abort
git merge origin/main --no-edit --allow-unrelated-histories -X ours   # merge 时 ours = 你
```

---

## 陷阱 3 · PowerShell 吃掉引号 / 把多行参数拆开

**症状**

```text
+ git commit -m "feat: ...
+                    ~
Missing closing ')' in expression.
```
或
```text
fatal: ... did not match any file(s) known to git
```

**根因**：PowerShell 对**内嵌双引号**、多行字符串、`(` `)` `;` 的处理规则与 bash 不同。一段长提交信息里带引号，就可能被截断，剩余部分被当成路径参数。

**判据**：命令里出现了多行文本、嵌套引号、或 `(` `)`，而报错位置指向引号或括号。

**处置**

1. **长文本写文件**，再让 git 读文件（最稳，跨 shell 通用）：

   ```powershell
   # 先用 write 工具（或编辑器）把提交信息写到 C:\Temp\msg.txt
   git commit -F C:\Temp\msg.txt
   ```
2. **复杂逻辑交给 Python**：用 `subprocess.run([...])` 列表传参，完全绕开 shell 解析。
3. 必须写在命令行时：用**单引号**包整体、去掉内嵌双引号、避免 `()` `;`。

---

## 陷阱 4 · 脚本读到 BOM / UTF-16，解析失败

**症状**：Python 脚本报 `invalid start byte`、字段名带 `\ufeff`、或中文字符串变成乱码；`Select-String` 搜不到本该存在的文本。

**根因**：`>` / `Out-File` / `Set-Content` 在 Windows PowerShell 5.1 下默认写 **UTF-16LE**，PowerShell 7 下写带 **BOM** 的 UTF-8。`git mv`、脚本读取端通常按纯 UTF-8 处理。

**判据**

```powershell
Format-Hex -Path .\somefile.txt | Select-Object -First 1
# EF BB BF -> UTF-8 BOM ; FF FE -> UTF-16LE
```

**处置**

- 写文件：用编辑工具（如 DSH 的 write 工具）或 Python `pathlib.Path(...).write_text(text, encoding="utf-8")`。
- 必须用 PowerShell 时：`Set-Content -Encoding utf8NoBOM`（PS7）。
- 读取端做兼容：`open(path, encoding="utf-8-sig")`，并在解析前 `strip("\ufeff\u200b")`。
- 本次事故里，管道输入的第一行 `y` 变成 `\ufeffy`，就是靠这个 `strip` 修好的。

---

## 陷阱 5 · `Author identity unknown` / `Committer identity unknown`

**症状**

```text
Author identity unknown
*** Please tell me who you are.
fatal: unable to auto-detect email address (got 'user@HOST.(none)')
```

**根因**：`user.name` / `user.email` 未配置。注意**不只是** `git commit`：`git commit --amend`、`git rebase --continue`、`git merge`（要新建合并提交时）都会要求身份，所以变基中途报这个错会让人以为是变基坏了。

**判据**

```bash
git config --get user.name ; git config --get user.email   # 空 = 未配置
```

**处置**

```bash
# 仓库级（推荐：不污染全局，也不泄露给其他项目）
git config user.name "thewal-ker"
git config user.email "thewal-ker@users.noreply.github.com"

# 若只是想临时跑一条命令
GIT_AUTHOR_NAME="x" GIT_AUTHOR_EMAIL="x@example.com" git commit ...
```

**身份不确定时**：不要编造用户的真实邮箱。两种安全选择——① 用 GitHub noreply 形式 `<用户名>@users.noreply.github.com`；② 用明确占位（`<项目名> <noreply@example.com>`）并告诉用户事后一条命令改回：

```bash
git commit --amend --reset-author --no-edit
```

---

## 陷阱 6 · CI 十几秒就失败：路径不存在

**症状**

```text
python: can't open file '/home/runner/work/<repo>/<repo>/<skill>/scripts/validate.py':
[Errno 2] No such file or directory
##[error]Process completed with exit code 2
```

伴随现象：矩阵里一条 `Failed in 12 seconds`，另一条 `Cancelled`（一条失败后 GitHub 取消其余）。

**根因**：workflow 假设的目录结构与仓库实际结构不一致。典型是仓库是**技能库**（技能在 `<skill>/` 子目录），而本地文件其实**平铺在仓库根**，或反过来。

**判据**（在本地 clone 上比对，别猜）

```bash
git ls-tree -r --name-only origin/main | head -20   # 远程真实结构
grep -n "scripts/" .github/workflows/validate.yml    # workflow 假设的路径
```

**处置**

1. **对齐结构**：技能库就把技能整体移进 `<skill>/`（`git mv <item> <skill>/<item>`），并同步 README 里的目录树。
2. **让 workflow 自适应**（推荐，将来拆分仓库不用改）：

   ```yaml
   - name: Detect skill layout
     run: |
       if [ -f SKILL.md ]; then echo "SKILL_DIR=." >> "$GITHUB_ENV"
       else echo "SKILL_DIR=<skill-name>" >> "$GITHUB_ENV"; fi
   ```
3. **推送前离线复现 CI**（见 `publish-playbook.md`），把 12 秒的失败提前到本地。

**附带教训**：校验脚本里"目录名必须等于 `name`"这类规则，在有**两种合法布局**（单技能仓库 / 技能库仓库）时会误杀。正确设计是——显式传入技能目录时**严格**校验，不带参数运行时**自动发现**技能目录并放宽该规则。

---

## 陷阱 7 · 公开仓库的提交历史里有真实邮箱

**症状**：`git log` 里出现 `用户 <15249916183@163.com>`，而仓库是 public。

**根因**：GitHub 网页建仓时生成的 `Initial commit` 使用**你账号的邮箱**；之后如果你没单独配置，本地提交也会带上全局邮箱。

**判据**

```bash
git log --all --format="%h %an <%ae> %cn <%ce>"
git ls-remote origin refs/heads/main   # 确认这条历史是否已经推上去了
```

**处置**：完整流程（含 `filter-branch`、清理备份引用、强推、复查）见 `privacy-and-history-rewrite.md`。**顺序不能乱**，尤其别漏 `refs/original/*` 的删除，否则 `git log --all` 里旧信息仍在，会以为没改成功。

---

## 附：`--force-with-lease` 报 `stale info`

**症状**

```text
! [rejected]        main -> main (stale info)
```

**根因**：`--force-with-lease` 用本地 `refs/remotes/origin/main` 作为"我上次看到的远程状态"来比较。若这个引用被改写（例如刚跑过 `git filter-branch -- --all`）或过期，比较失败即拒绝推送。

**处置**

```bash
git fetch origin "+refs/heads/*:refs/remotes/origin/*"   # 强制对齐远程引用
git push --force-with-lease origin main
```

**判据**：`git rev-parse origin/main` 与 `git ls-remote origin refs/heads/main` 的哈希不一致 → 就是它。

---

## 陷阱 8 · 技能装好了却永远加载不出来（YAML 冒号）

**症状**：文件位置、目录名、`name`、编码全都对，`skill <名字>` 却始终返回
`unknown or no longer available`；重启应用、换会话都无效；界面上**没有任何报错**。

**根因**：`SKILL.md` 的 frontmatter 是 YAML。**未加引号的标量里出现 ASCII 冒号**
（尤其是 `: ` 冒号 + 空格，或值以 `:` 结尾）会让 YAML 解析失败。技能加载器遇到解析失败时
只写一行日志然后 `return`：

```js
ctx.logger.warn(`skill file ${path} ignored: invalid YAML frontmatter: ...`);
```

——**静默跳过**：不报错、不提示、不进技能清单。

实战案例：`description` 结尾写了英文标签

```yaml
description: ……也不代替用户做购买决定。English: Diagnose whether a specific video game fits a specific player……
#                                                ↑ 这个 ": " 让整个技能失效
```

**判据**：在同一技能目录下做 A/B 对照——写一个只有 `name` + 简短 `description`（不含冒号）的
探针技能。若探针出现在技能清单里而你的技能没有，就是 frontmatter 解析失败。
（DSH 的技能清单带文件监听：新建或修改 `SKILL.md` 后清单会**立即刷新**，无需重启应用。）

**处置**：二选一。

```yaml
# 方案 A（推荐）：用单引号包裹整个值，内部冒号就失去语法意义
description: '……原文…… English: Diagnose whether ……'

# 方案 B：把 ASCII 冒号换成全角冒号
description: ……原文…… English：Diagnose whether ……
```

**预防**：`scripts/precheck.py --repo .` 会直接报出
`frontmatter 第 N 行：未加引号的值里出现 ASCII 冒号`。同类风险字段还有
`compatibility`、以及 `metadata` 下的自定义值（如 `note: see: the docs`）。

**顺带一条运行时装法**：技能目录里可以有 `references/`、`assets/`、`scripts/`，但
**`SKILL.md` 必须在被扫描根目录的第一层子目录里**；`**/SKILL.md`（再深一层）故意不被发现。
