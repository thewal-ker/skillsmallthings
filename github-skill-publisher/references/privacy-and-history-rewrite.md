# 隐私清理与历史改写

处理"真实姓名/邮箱已经进了提交历史"这类问题。**顺序不能乱**，每一步都给出验证命令。

> 前置：确认用户**确实要改写历史**。改写会改变所有提交哈希，协作者需要重新克隆；如果仓库有他人协作，先问清楚。
> 对公开仓库，泄露真实邮箱属常见疏忽——GitHub 网页建仓的 `Initial commit` 会用账号邮箱。

---

## 第 0 步：先摸清泄露范围

```bash
# 提交历史里的身份
git log --all --format="%h  A=%an <%ae>  C=%cn <%ce>  %s"

# 工作区文件里的真名/真邮箱（把 <真名> 换成实际值）
grep -rn "<真名>" --exclude-dir=.git .
grep -rnE "QQ|163\.com|@[a-z0-9.-]+\.(com|cn)" --exclude-dir=.git --include="*.md" --include="*.py" .

# 是否已经推到远程
git ls-remote origin refs/heads/main
```

分类处理：

| 位置 | 处理方式 |
|---|---|
| 工作区文件（`LICENSE`、`metadata.author`） | 直接改文本，提交即可 |
| 提交作者/提交者字段 | 需要改写历史（本文档第 2 步） |
| 远程分支上的历史 | 改写后强推（第 4 步） |
| 仓库描述、README 里的自我介绍 | 网页改，或改文件后提交 |

---

## 第 1 步：替换工作区里的真名

```powershell
# 用编辑工具或 Python 改，不要用 PowerShell 重定向（会写 BOM，见 troubleshooting 陷阱 4）
python -c "
import pathlib
for p, old, new in [(r'LICENSE','朱希贤','thewal-ker'), (r'SKILL.md','朱希贤','thewal-ker')]:
    f = pathlib.Path(p); f.write_text(f.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')
print('done')
"
grep -rn "<真名>" --exclude-dir=.git .   # 应为空
```

**注意**：`references/` 里如果引用了用户提供的原始文档（例如"来源：某某.docx"），文件名可能含真名。判断标准是——**这句引用是否必要**。保留来源说明通常没问题（文档名不等于隐私泄露的主因），但要在报告里明确告诉用户"这里还有一处，是否要一并处理"。

---

## 第 2 步：改写全部提交的作者与提交者

```powershell
# 环境变量关掉 filter-branch 的警告
$env:FILTER_BRANCH_SQUELCH_WARNING = "1"

git filter-branch -f --env-filter '
export GIT_AUTHOR_NAME=thewal-ker
export GIT_AUTHOR_EMAIL=thewal-ker@users.noreply.github.com
export GIT_COMMITTER_NAME=thewal-ker
export GIT_COMMITTER_EMAIL=thewal-ker@users.noreply.github.com
' -- --all
```

要点：

- `-- --all` 覆盖**所有**引用（本地分支 + remote-tracking），漏了 `refs/remotes/*` 会让 `git log origin/main` 显示旧身份，误以为没成功。
- 单引号内的脚本由 filter-branch 的 shell 执行，`export` 写法在 Ubuntu 与 Git Bash 下都可用。
- 若提交信息里也含真名，加 `--msg-filter 'sed "s/<真名>/thewal-ker/g"'`。

**验证**

```bash
git log --format="%h  A=%an <%ae>  C=%cn <%ce>  %s" -5
```

---

## 第 3 步：彻底清理本地残留

只做第 2 步，旧信息仍会通过**备份引用与 reflog** 存活：

```bash
# filter-branch 会留下 refs/original/*，它被 --all 视为可达
git for-each-ref --format="%(refname)" refs/original
git for-each-ref --format="%(refname)" refs/original | while read ref; do git update-ref -d "$ref"; done

git reflog expire --expire=now --all
git gc --prune=now --quiet

# 复查（应无输出）
git log --all --format="%an %ae %cn %ce" | grep -E "<真实邮箱域名>|noreply@example.com"
```

**判据**：`git for-each-ref --format="%(refname)"` 输出里**不应**再有 `refs/original/...`。

---

## 第 4 步：强推并再次验证

```bash
# 关键：先强制对齐远程跟踪引用，否则 --force-with-lease 会报 stale info
git fetch origin "+refs/heads/*:refs/remotes/origin/*"
git push --force-with-lease origin main
```

服务器侧确认（**必须做**，本地干净不等于远程干净）：

```bash
git ls-remote origin refs/heads/main                      # 哈希应为改写后的新哈希
git log origin/main --format="%h %an <%ae>" -5            # 身份应已更新
git show origin/main:<被改的文件> | grep -n "Copyright"    # 文件内容应已更新
```

---

## 第 5 步：如实告知用户的三件事

不要含糊，也不要夸大：

1. **旧提交在 GitHub 上变成不可达**，通过分支、文件页、提交列表都看不到；
2. 若有人**保存了旧提交的完整哈希**，短时间内仍可能直接访问到——想更彻底可在仓库 Settings 里联系 GitHub Support 请求清理（多数个人项目不必）；
3. **今后**为避免再泄露，配置 noreply 邮箱：

```powershell
git config --global user.name  "<GitHub 用户名>"
git config --global user.email "<GitHub 用户名>@users.noreply.github.com"
```

并在 GitHub **Settings → Emails** 勾选 *Keep my email addresses private*（双保险，网页端操作也会用 noreply 地址）。

---

## 附：撤回到改写前

改写前的哈希在 `ORIG_HEAD` 与 `refs/original/*`（若未清理）中，可临时恢复：

```bash
git reflog                 # 找到改写前的提交
git reset --hard <旧哈希>
git push --force-with-lease origin main
```

因此**清理残留（第 3 步）应放在"用户确认改写结果没问题"之后**；若还没确认，先别删 `refs/original/*`。
