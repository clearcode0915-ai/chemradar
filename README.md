# ChemRadar · 定制版文献速递页

按 ISSN 抓取指定期刊最近 N 天的**全部**新文章，加上 arXiv 预印本，自动补全元数据与摘要，
配上中文标题，生成一个纯静态、可离线打开的单文件页面。
搜索 / 期刊筛选 / 时间窗 / 收藏全部在浏览器端完成，没有后端。
数据每天由 GitHub Actions 自动更新并发布到 GitHub Pages。

- **零第三方依赖**：只用 Python 标准库，Actions 里不需要 `pip install`
- **不爬出版方页面**：数据取自 [Crossref](https://www.crossref.org/) 官方接口，摘要由出版方 deposit（JATS 格式）
- **预印本**：arXiv `physics.chem-ph`，与正式发表条目按标题自动合并去重
- **摘要补全**：APS（PRL）不向 Crossref 提供摘要，从文章页取回并缓存
- **只翻标题**：一天 40 篇标题约 4500 字符，MyMemory 免费额度足够，成本≈0

站点：<https://clearcode0915-ai.github.io/chemradar/>

## 本地运行

```bash
python src/run.py                 # 抓取 + 翻译 + 生成
python src/run.py --days 30       # 临时扩大回溯窗口
python src/run.py --no-translate  # 只抓不翻（已有的中文标题会保留）
python src/run.py --budget 60000  # 首次补全译文时临时放宽本轮字符预算
python src/run.py --pace 1.0      # 放慢翻译节奏（被限流时用）
```

产物：

| 文件 | 说明 |
|---|---|
| `site/index.html` | 最终页面，数据内嵌，双击即可看 |
| `site/papers.json` | 同一份数据的纯 JSON 接口 |
| `data/papers.json` | 抓取结果 + 历史（滚动窗口） |
| `data/translations.json` | 译文缓存，按标题哈希索引 |

> 首次运行会把窗口内几百条标题排队翻译。免费接口按 IP 限流，若没填
> `translate.email`，一轮只能译出最新的几十条——这是正常现象，后面每次运行接着补。
> 想一次补齐就填上 email 再跑 `--budget 60000`。

## 部署

完整步骤见 [DEPLOY.md](DEPLOY.md)，核心三件事：

1. 推到自己的 GitHub 仓库（public，Pages 免费）
2. 加两个 secret：`CROSSREF_MAILTO`、`MYMEMORY_EMAIL`（都填邮箱）
3. Actions 里手动 Run 一次 `update-feed`

之后每天 UTC 22:10 / 10:10（北京时间 06:10 / 18:10）自动跑：抓新文章 → 合并去重 →
补译标题 → 生成页面 → 提交 `data/` 和 `site/` → 部署到 Pages。

## 配置（`config.toml`）

| 项 | 说明 |
|---|---|
| `[site] title` / `subtitle` | 页面标题与副标题 |
| `[site] window_days` | 每次抓取回溯天数，默认 14 |
| `[site] keep_days` | `data/papers.json` 保留多久历史，默认 90 天 |
| `[site] page_limit` | 页面最多放多少篇（默认 1000，`0` = 不限），数据不受影响 |
| `[fetch] mailto` | Crossref 联系邮箱，走 polite pool 更稳 |
| `[fetch] rows` | 单刊单次请求条数（上限 1000） |
| `[fetch] arxiv` | 是否收 `physics.chem-ph` 预印本，默认 `true` |
| `[filter] drop_titles` | 要剔除的前置内容标题正则（见下节） |
| `[filter] drop_anonymous` | 无作者且无摘要的条目一律剔除，默认 `true` |
| `[abstracts] enabled` | 是否给 APS 条目补摘要，默认 `true` |
| `[abstracts] max_per_run` | 单轮最多补多少篇，默认 60 |
| `[translate] backend` | `mymemory` 或 `none` |
| `[translate] email` | MyMemory 邮箱，额度 5000 → 50000 字符/天 |
| `[translate] max_chars_per_run` | 单轮字符预算，`0` = 自动 |
| `[[journals]]` | 期刊清单：`issn` / `label`（角标）/ `name` / `color` |

增删期刊只改 `[[journals]]` 那几段。**从配置里删掉的期刊，历史条目会在下一次运行时自动剔除**，
不用手动清数据。

## 过滤掉的非研究条目

Crossref 里混着一批「期刊前置内容」，它们同样是 `type:journal-article`，会污染列表：

| 标题 | 是什么 |
|---|---|
| `Issue Editorial Masthead` | 编委会名单 |
| `Issue Publication Information` / `Issue Information` | 出版信息、版权页 |
| `Front cover` / `Back cover` / `Inside front cover` | 封面 |
| `Contents list` / `Table of contents` | 目录页 |

`src/filters.py` 用两条规则剔除：

1. **标题正则**：清单在 `[filter] drop_titles`，想保留某类删掉对应行即可；
2. **结构规则**：`drop_anonymous = true` 时，**无作者且无摘要**一律视为非研究内容——
   前置内容几乎都长这样，而真论文一定有作者。这条能挡住清单里没列到的新花样。

剔除数量与前几条标题会打在日志里，方便核对有没有误伤。
注意 `Correction` / `Erratum`（勘误、更正）**不会**被剔除，它们有作者有摘要，属于有效信息；
不想要就在 `drop_titles` 里加 `'^correction'`、`'^erratum'`。

## 页面能力

- 顶部即时搜索：中英标题、作者、摘要，命中词高亮
- 期刊单选：点哪本只看哪本，再点一次回到全部；提示行显示「只看 XX」
- 时间窗：24 小时 / 3 天 / 7 天 / 全部
- 收藏：localStorage，不登录，「只看收藏」一键过滤
- 摘要默认折叠，展开状态在筛选切换后保持
- 滚到底自动续载，提示行显示「共 N 篇 · 已显示 M 篇」
- 右下角返回顶部按钮（滚动超过 700px 出现）；切换期刊/时间窗后自动回到页首
- 深浅色跟随系统，可手动切换；`/` 聚焦搜索，`Esc` 取消
- **卡片不带图**，只保留期刊角标、标题、作者、摘要与链接，追求加载速度

## 常见问题

**数据能存多久？**
抓取窗口 14 天（`window_days`），历史保留 90 天（`keep_days`）。也就是说页面最多能累积约 90 天的文章；
更早的会在下次运行时被丢掉。页面本身只放最近 1000 篇（`page_limit`），但 `data/papers.json` 里仍是完整数据。

**需要我手动跑吗？**
不需要。GitHub Actions 每天自动跑两次（北京时间约 06:10 / 18:10）：抓新文章 → 补译标题 →
生成页面 → 提交数据 → 部署 Pages。只有改了 `config.toml` 想立刻生效时，才需要去 Actions 页面手动 Run 一次。

**为什么有的标题没有中文标题？**
MyMemory 免费额度有限或 IP 被限流时会停手，下次运行自动续译。缓存按标题哈希存，不会重复消耗额度。
日志里会打「仍缺 N 条」；填了 `translate.email` 基本一轮就能补齐。

**摘要哪来的？**
绝大多数刊是 Crossref 里出版方 deposit 的 JATS 摘要，去标签后原样展示。
APS（PRL）不提供摘要，`src/abstracts.py` 会去文章页取一次并缓存，所以新条目可能先没有摘要，
下一轮运行补上。摘要**不翻译**，只翻标题。

**`ASAP` 角标是什么意思？**
Crossref 里没有卷号/页码、只有在线发表时间的条目，即 ACS 的 Articles ASAP（定稿前在线发表）。

**`≈` 是什么意思？**
该条目在 Crossref 里只有「年」这一级精度（RSC 常见），日期退回成了 DOI 注册时间，不是真实出版日。

**会被限流吗？**
Crossref 每个期刊一次请求（`rows=500`），带 `mailto` 走 polite pool，正常不触发；
429/5xx 有指数退避重试，单刊失败不影响整体。MyMemory 按 IP 限流，失败后退避重试，
连续 6 次失败即本轮收工，已译部分照常落盘。
