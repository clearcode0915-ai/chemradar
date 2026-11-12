# 部署到 GitHub Actions（照抄即可）

我这边已经把仓库初始化好了（4 个 commit，`main` 分支就绪），**代码你不用动**。
下面只有三步：推上去 → 配两个 secret → 手动跑一次。

> 我没有、也不该有你的 GitHub 令牌，所以推送这一步必须由你自己执行。

---

## 第 1 步：创建仓库并推送

### 路线 A：网页建库（不装任何工具）

1. 打开 https://github.com/new
   - Repository name：`chemradar`（随意）
   - 选 **Public**（Pages 免费；Private 需要 Pro 才能开 Pages）
   - **不要**勾 "Add a README" / "Add .gitignore" / "Choose a license"
2. 本机执行（把 `<你的用户名>` 换掉）：

```bash
cd C:/Users/27940/WorkBuddy/tmp/lit-radar
git remote add origin https://github.com/<你的用户名>/chemradar.git
git branch -M main
git push -u origin main
```

首次 push 会弹登录：用浏览器授权，或去
`Settings → Developer settings → Personal access tokens → Tokens (classic)`
建一个勾了 `repo` 权限的 token，密码栏粘 token。

### 路线 B：装了 gh CLI 的话（三条命令）

```bash
winget install --id GitHub.cli -e
gh auth login                                    # 选 GitHub.com → HTTPS → 浏览器登录
cd C:/Users/27940/WorkBuddy/tmp/lit-radar
gh repo create chemradar --public --source=. --push
```

---

## 第 2 步：配两个 secret

仓库页 → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value | 作用 |
|---|---|---|
| `CROSSREF_MAILTO` | 你的邮箱 | 走 Crossref polite pool，抓取更稳 |
| `MYMEMORY_EMAIL` | 同一个邮箱 | 翻译额度 **5000 → 50000 字符/天**，首跑才能一次把几百条标题补完 |

两个都不填也能跑，只是翻译会慢很多（每天只翻几十条）。
代码里 `src/util.py` 会读这两个环境变量并覆盖 `config.toml`，所以你**不用改文件**。

---

## 第 3 步：手动跑一次

仓库页 → **Actions** → 左侧 `update-feed` → 右侧 **Run workflow** → 绿色按钮。

首次约 **3–10 分钟**（12 个刊 + 几百条标题翻译，翻译是故意放慢的，避免被限流）。

### 怎么判断成功了

1. Actions 里 `build` 任务变绿，点进去看 **Summary**，我会写一段运行摘要：

```
### 本次更新
- 条目总数：540
- 有中文标题：412（其余靠后续运行续译）
- 有真实封面：0（其余用生成封面）
- 分刊：JCP 123、JPCC 88、JPCL 78、JPCB 61、JCIM 55、JCTC 51、JPCA 46、npjCM 14 …
```

2. 站点地址：`https://<你的用户名>.github.io/chemradar/`
   Pages 首次部署后要等 1–2 分钟才生效。

**Pages 不用手动开**：workflow 里 `configure-pages` 带了 `enablement: true`，会自动把
Source 设成 "GitHub Actions"。如果它报 `Get Pages site failed`，就去
Settings → Pages → Source 手动选 **GitHub Actions**，再重跑一次。

---

## 之后它自己会怎么跑

| 项 | 说明 |
|---|---|
| 频率 | 每天两次，UTC 22:10 / 10:10 → **北京时间 06:10 / 18:10** |
| 延迟 | GitHub 的 cron 常有 0–30 分钟延迟，属正常 |
| 每次都做什么 | 抓新文章 → 合并去重 → 补译标题（只译没译过的）→ 生成页面 → 提交 `data/` 和 `site/` → 部署 |
| 想改时间 | 改 `.github/workflows/daily.yml` 里的 `cron`（注意是 **UTC**） |
| 60 天规则 | 公开仓库若 60 天无提交，GitHub 会自动停用 schedule；随便推一次 commit 就恢复 |

---

## 常见报错对照表

| 现象 | 原因 / 处理 |
|---|---|
| `remote: Permission to ... denied` | token 没有 `repo` 权限，或仓库地址用户名写错 |
| Actions 里 `git push` 失败（protected branch） | 关掉分支保护，或 Settings → Actions → General 允许 workflow 写仓库 |
| `deploy-pages` 报 `No artifact found` | 前面的 `build` 失败了，先看 build 的日志，别管 deploy |
| 页面 404 | 刚部署完等 1–2 分钟；还不行看 Settings → Pages 的 Source 是否是 GitHub Actions |
| 标题全英文 | 日志里找 `仍缺 N 条`：配额用尽或接口限流，等下一次运行会自动续译 |
| 封面全是晶格图 | `RSS 不可达`，说明出版方 feed 被网络挡住；这是预期降级 |
| Summary 里条目数 0 | Crossref 被限流，重跑一次即可 |

---

## 可选：换成 `*.pages.dev` 域名（和参考站一样）

如果你更喜欢 Cloudflare 的域名，可以：Cloudflare Dashboard → Pages → 连接这个 GitHub 仓库 →
构建命令 `python src/run.py`、输出目录 `site`、环境变量 `PYTHON_VERSION=3.12`。
之后每天由 GitHub Actions 提交 `data/` 触发 Cloudflare 重新构建，两边并存互不影响。
