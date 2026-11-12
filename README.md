# ChemRadar · 定制版文献速递页

按 ISSN 抓取指定期刊最近 N 天的**全部**新文章，自动补全元数据与摘要，配上中文标题，
生成一个纯静态、可离线打开的单文件页面（搜索 / 期刊筛选 / 时间窗 / 收藏全部在浏览器端完成）。
数据每天由 GitHub Actions 自动更新并发布到 GitHub Pages。

- 零第三方依赖：只用 Python 标准库，Actions 里不需要 `pip install`
- 不爬出版方页面：数据取自 [Crossref](https://www.crossref.org/) 官方接口（摘要由出版方 deposit，实测 12 种期刊全都有）
- 只翻标题：一天 40 篇标题约 4500 字符，MyMemory 免费额度足够，成本≈0

## 本地运行

```bash
python src/run.py                 # 抓取 + 翻译 + 生成
python src/run.py --days 30       # 临时扩大回溯窗口
python src/run.py --no-translate  # 只抓不翻，调试用
python src/run.py --budget 60000  # 首次补全译文时临时放宽本轮字符预算
python src/run.py --pace 1.0      # 放慢翻译节奏（被限流时用）
```

> 首次运行会把 14 天窗口内的几百条标题排队翻译。免费接口按 IP 限流，
> 若没填 `translate.email`，一轮只能译出最新的几十条 —— 这是正常现象，
> 后面每次运行会接着补；想一次补齐就填上 email 再跑 `--budget 60000`。

产物：`site/index.html`（数据内嵌，双击即可看）、`site/papers.json`（纯数据）、
`data/papers.json`（含历史）、`data/translations.json`（译文缓存）。

## 部署到自己的 GitHub（5 步）

1. 新建仓库，把本目录推上去。
2. 仓库 **Settings → Secrets and variables → Actions** 加两个 secret：
   - `CROSSREF_MAILTO`：你的邮箱（Crossref polite pool，抓取更稳）
   - `MYMEMORY_EMAIL`：你的邮箱（翻译额度 5000 → 50000 字符/天）
3. 仓库 **Settings → Pages → Source** 选 **GitHub Actions**。
4. 到 **Actions → update-feed → Run workflow** 手动跑一次。
5. 跑完地址是 `https://<用户名>.github.io/<仓库名>/`。

定时任务默认每天两次（北京时间约 06:10 / 18:10），想改就改 `.github/workflows/daily.yml` 里的 `cron`。

## 配置（`config.toml`）

| 项 | 说明 |
|---|---|
| `[site] window_days` | 每次抓取回溯天数，默认 14；首跑会把这段窗口全抓下来 |
| `[site] keep_days` | `data/papers.json` 保留多久历史 |
| `[fetch] mailto` | Crossref 联系邮箱，建议填 |
| `[fetch] arxiv` | 改成 `true` 可额外收 `physics.chem-ph` 预印本（按标题与正式发表条目合并去重） |
| `[translate] email` | MyMemory 邮箱，填了额度 ×10 |
| `[translate] max_chars_per_run` | 单轮字符预算，超出部分下次自动续译 |
| `[[journals]]` | 期刊清单：`issn` / `label`（角标文字）/ `name` / `color`（角标色） |

增删期刊只要改这一段，ISSN 可在 crossref.org 搜索期刊页查到。

## 常见问题

**为什么有的条目没有中文标题？**
MyMemory 免费额度有限，首次全量补全需要跑 1–2 次（或在 config 里填 email 后跑一次
`--budget 60000`）。之后每天只有几十条新增，一次就能翻完。缓存按原文哈希存，不会重复消耗额度。

**摘要怎么来的？**
Crossref 里出版方 deposit 的 JATS 摘要，去标签后原样展示，没有二次加工；摘要不做翻译。

**`ASAP` 角标是什么意思？**
Crossref 里没有卷号/页码、只有在线发表时间的条目，即 ACS 的 Articles ASAP（定稿前在线）。

**页面样式能改吗？**
`templates/index.html` 是单文件模板，CSS 变量集中在 `:root` 与 `:root[data-theme="light"]`，
改 `--ac`（强调色）就能换主题色。期刊角标色在 `config.toml` 的 `color` 里。

**会不会被 Crossref 限流？**
每个期刊一次请求（`rows=500`），共 12 次，带 `mailto` 走 polite pool，正常不会触发。
代码里对 429/5xx 有指数退避重试，单刊失败不影响整体。
