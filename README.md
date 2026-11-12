# ChemRadar · 定制版文献速递页

按 ISSN 抓取指定期刊最近 N 天的**全部**新文章，自动补全元数据与摘要，配上中文标题，
生成一个纯静态、可离线打开的单文件页面（搜索 / 期刊筛选 / 时间窗 / 收藏全部在浏览器端完成）。
数据每天由 GitHub Actions 自动更新并发布到 GitHub Pages。

- 零第三方依赖：只用 Python 标准库，Actions 里不需要 `pip install`
- 不爬出版方页面：数据取自 [Crossref](https://www.crossref.org/) 官方接口（摘要由出版方 deposit，实测 12 种期刊全都有）
- 只翻标题：一天 40 篇标题约 4500 字符，MyMemory 免费额度足够，成本≈0
- 期刊流 + arXiv `physics.chem-ph` 预印本（按标题与正式发表条目合并去重）
- 卡片不带图（`[covers] mode = "off"`）；想开封面就改成 `auto`，见下节

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
| `[fetch] arxiv` | 是否收 `physics.chem-ph` 预印本，默认 `true` |
| `[translate] email` | MyMemory 邮箱，填了额度 ×10 |
| `[translate] max_chars_per_run` | 单轮字符预算，超出部分下次自动续译 |
| `[covers] mode` | `auto` 有真图用真图、没有则生成封面；`off` 关闭封面 |
| `[[journals]]` | 期刊清单：`issn` / `label`（角标文字）/ `name` / `color`（角标色）/ `rss`（可选，封面源） |

增删期刊只要改这一段，ISSN 可在 crossref.org 搜索期刊页查到。

## 封面（TOC 图）

卡片左侧的小图有三个来源，按优先级：

1. **直接问 CDN 反推（主路径，不需要访问出版方站点）**
   ACS 的目录图托管在 `acs.silverchair-cdn.com`，路径固定：
   `/{刊路径}/pap/{DOI 下划线化}/1/{前缀}{稿件号}_{图号}.png`，
   而 **CDN 不校验签名**（带不带 `?Expires=…&Signature=…` 都返回 200）。
   图号不可推导，但实测「**该文章最大的图号 = 目录图**」（拿参考站 9 篇带图文章逐篇核对，9/9 一致），
   且**不存在的图号返回 403**，于是从 `probe_max_index` 往下试，第一个 200 就是目录图。
   每篇的刊路径与文件名前缀写在 `config.toml` 的 `acs_key` / `acs_prefix` 里：

   | 刊 | acs_key | acs_prefix |
   |---|---|---|
   | JCTC | jctcce | ct |
   | JCIM | jcisd8 | ci |
   | JPCA | jpcafh | jp |
   | JPCL | jpclcd | jz |
   | JPCB | jpcbfk | jp |
   | JPCC | jpccck | jp |

   结果按 DOI 缓存在 `data/covers.json`，每篇只探一次；`max_probe_per_run` 控制单轮上限，
   没探完的下次继续。关掉就把 `probe_acs` 设为 `false`。

2. **出版方 RSS**（最权威，但 `pubs.acs.org` 对本机和 GitHub Actions 的机房 IP 都不通）
3. **生成封面**：都没有时，用期刊色 + DOI 哈希画一张分子晶格小图（纯内联 SVG，零请求）

只有真图能点开看大图（灯箱）；生成封面不响应点击。

## 常见问题

**为什么有的条目没有中文标题？**
MyMemory 免费额度有限，首次全量补全需要跑 1–2 次（或在 config 里填 email 后跑一次
`--budget 60000`）。之后每天只有几十条新增，一次就能翻完。缓存按原文哈希存，不会重复消耗额度。

**摘要怎么来的？**
Crossref 里出版方 deposit 的 JATS 摘要，去标签后原样展示，没有二次加工；摘要不做翻译。

**为什么很多封面是"晶格图"而不是论文里的图？**
那些是生成封面。真图依赖出版方 RSS，RSS 一旦不可达（或该刊不提供图），就自动回落。
在 GitHub Actions 上跑更容易拿到真图，本地网络打不开 `pubs.acs.org` 时全是生成封面，属正常现象。

**`ASAP` 角标是什么意思？**
Crossref 里没有卷号/页码、只有在线发表时间的条目，即 ACS 的 Articles ASAP（定稿前在线）。

**页面样式能改吗？**
`templates/index.html` 是单文件模板，CSS 变量集中在 `:root` 与 `:root[data-theme="light"]`，
改 `--ac`（强调色）就能换主题色。期刊角标色在 `config.toml` 的 `color` 里。

**会不会被 Crossref 限流？**
每个期刊一次请求（`rows=500`），共 12 次，带 `mailto` 走 polite pool，正常不会触发。
代码里对 429/5xx 有指数退避重试，单刊失败不影响整体。
