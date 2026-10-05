# 发布操作手册

按顺序执行的完整命令清单。环境以 Windows + PowerShell 为例，附 Git Bash / 类 Unix 的等价命令。

---

## 1. 摸清现状（30 秒）

```powershell
# 本地：这个目录是不是 git 仓库？远程配了没？
git rev-parse --is-inside-work-tree 2>$null
git remote -v
git log --oneline -3 2>$null

# 远程：仓库存不存在？是空仓库吗？（需要已认证；没有则用网页看）
git ls-remote https://github.com/<用户>/<仓库>.git
```

| `git ls-remote` 结果 | 含义 | 下一步 |
|---|---|---|
| 报 `Repository not found` | 仓库不存在或没权限 | 让用户在 GitHub 建**空仓库**（不勾 README/.gitignore/License） |
| 无输出（成功但空） | **空仓库**，最理想 | 直接按第 3 步推送 |
| 打印 `refs/heads/main` | 非空 | 会触发陷阱 1，按"合并"方案走 |

**建仓时务必让用户不要勾任何初始化文件**——这是避免陷阱 1 的最省事办法。

---

## 2. 本地准备与首次提交

```powershell
cd <项目目录>
git init -b main                                  # 分支名直接叫 main
git config user.name  "thewal-ker"
git config user.email "thewal-ker@users.noreply.github.com"   # 用 noreply，护住真实邮箱
git add -A
git status --short                                # 确认要提交的文件清单符合预期
```

**提交信息写文件，再 `-F` 读取**（避免陷阱 3；用编辑工具写，避免陷阱 4）：

```powershell
git commit -F .git\COMMIT_MSG.txt
git log --oneline --stat -1
```

自查三条：

```powershell
git log --format="%h %an <%ae> %s" -1     # 身份对不对
git ls-files | Select-String "pycache|\.json$|report" # 别把产物提交进去
git status --short --branch               # 工作区应干净
```

---

## 3. 推送

```powershell
cd <项目目录>
if (git remote | Select-String -Quiet "^origin$") {
  git remote set-url origin https://github.com/<用户>/<仓库>.git
} else {
  git remote add origin https://github.com/<用户>/<仓库>.git
}
git push -u origin main
```

**认证**：首次会弹浏览器授权（Git Credential Manager）。若弹出终端要密码，密码处填 **Personal Access Token**（GitHub → Settings → Developer settings → Personal access tokens → 勾 `repo`）。非交互环境下先设 `GIT_TERMINAL_PROMPT=0`，避免卡在输入提示。

成功输出形如：

```text
To https://github.com/<用户>/<仓库>.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

被拒 → 转到 `troubleshooting.md` 的陷阱 1 / `stale info`。

---

## 4. 推送后立刻做服务器侧终校验

```powershell
git ls-remote origin refs/heads/main                    # 服务器真实哈希
git fetch origin "+refs/heads/*:refs/remotes/origin/*"  # 对齐本地跟踪引用
git rev-parse --short HEAD origin/main                  # 两者应一致
git ls-tree -r --name-only origin/main                  # 远程文件树（核对结构与文件名）
git show origin/main:<关键文件> | Select-Object -First 5 # 抽查内容确实是新版
```

**别只看本地 `git status` 显示干净就收工**——本地干净不代表远程正确。

---

## 5. 离线复现 CI（推送前做，能把红叉提前到本地）

目标：用 GitHub runner 的视角跑一遍 workflow 里的每条命令。

```powershell
$base = "$env:USERPROFILE\AppData\Local\Temp\ci-sim"     # 用长路径，见下方注意
Remove-Item -LiteralPath $base -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $base | Out-Null
git clone -q https://github.com/<用户>/<仓库>.git "$base\<仓库>"
cd "$base\<仓库>"
```

- 若你要验证**尚未推送**的改动：克隆后，把本地待推送的文件覆盖进克隆（`Copy-Item`），或直接在本地仓库跑同样命令。
- **模拟 runner 最干净的做法**：把克隆里的 `.git` 删掉——runner 上也没有 `.git` 影响你的相对路径。

然后逐条执行 workflow 里的 `run:` 命令，注意 **runner 是 Ubuntu + bash**：

```powershell
# workflow 里的 Detect skill layout
if (Test-Path "SKILL.md") { $env:SKILL_DIR = "." } else { $env:SKILL_DIR = "<skill-name>" }

python "$env:SKILL_DIR/scripts/validate_skill.py" "$env:SKILL_DIR"
python -m unittest discover -s "$env:SKILL_DIR/scripts" -p "test_*.py" -v
python "$env:SKILL_DIR/scripts/diagnose.py" --game "smoke" --mode 1 `
  --answers "core_loop:match,challenge:match" --non-interactive --json
```

**两个坑**

1. **别用 `$LASTEXITCODE` 判断步骤成败**——它会被后续管道（`Select-Object` 等）覆盖，得出假的"失败"。要退出码就用 Python 一次问清：

   ```powershell
   python -c "import subprocess,sys; r=subprocess.run([sys.executable,'-m','unittest','discover','-s','<skill>/scripts','-p','test_*.py'],capture_output=True,text=True); print(r.returncode); print(r.stderr[-200:])"
   ```

2. **临时目录别直接拼 `$env:TEMP`**：中文用户名下 `%TEMP%` 会是 `C:\Users\CC2F~1\...` 这种 8.3 短名，某些工具解析会出问题（本文档写作时 `Push-Location "$env:TEMP\..."` 就报了 `An object at the specified path C:\Users\CC2F~1 does not exist`）。用 `"$env:USERPROFILE\AppData\Local\Temp\..."` 这种长路径。

---

## 6. 收尾清单

- [ ] 服务器侧哈希与本地一致（第 4 步）
- [ ] 远程文件树与预期结构一致
- [ ] 抽查 1–2 个关键文件内容是新版
- [ ] GitHub Actions 最新一次运行是绿色（网页 Actions 标签）
- [ ] 提交身份不含真实邮箱（`git log origin/main --format="%an <%ae>"`）
- [ ] 仓库首页 README 说明与实际结构一致（技能库要有技能索引表）
- [ ] 临时产物没有被提交（`high.json`、`__pycache__`、`reports/` 等）
- [ ] 若改写过程序/规则，回归测试全绿

---

## 附 A：Git Bash 等价命令

```bash
# 合并远程无关历史
git fetch origin && git merge origin/main --no-edit --allow-unrelated-histories -X ours
# 恢复被覆盖的文件
git show <commit>:README.md > README.md && git add README.md
# 对齐远程引用后强推
git fetch origin "+refs/heads/*:refs/remotes/origin/*" && git push --force-with-lease origin main
```

## 附 B：一个可复制的提交信息模板

```text
<type>(<scope>): <一句话说明>

问题：
- <为什么会这样>

改动：
- <做了什么>

验证：
- <跑了什么命令，结果如何>
```

类型用 `feat` / `fix` / `docs` / `chore`。技能库仓库建议在信息里写清**影响哪个技能目录**。
