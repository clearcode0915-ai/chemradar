"""入口：抓取 → 合并 → 翻译标题 → 生成静态页。

用法：
    python src/run.py                 # 正常更新
    python src/run.py --days 30       # 临时扩大回溯窗口
    python src/run.py --no-translate  # 跳过翻译（调试用）
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import build, fetch, filters, translate  # noqa: E402
from src import covers as covers_mod  # noqa: E402
from src.util import DATA, load_config, log, read_json, write_json  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="定制版文献速递页生成器")
    ap.add_argument("--days", type=int, default=None, help="回溯天数，默认取 config.toml")
    ap.add_argument("--no-translate", action="store_true", help="跳过标题翻译")
    ap.add_argument("--budget", type=int, default=None,
                    help="本轮翻译字符预算（默认取 config.toml；首次补全可临时调大）")
    ap.add_argument("--pace", type=float, default=0.5, help="两次翻译请求的间隔秒数")
    args = ap.parse_args()

    t0 = time.time()
    cfg = load_config()
    site = cfg.get("site", {})
    window = args.days or int(site.get("window_days", 14))
    keep = int(site.get("keep_days", max(window * 3, 60)))
    mailto = (cfg.get("fetch", {}).get("mailto") or "").strip()
    if mailto.startswith("you@"):
        mailto = ""  # 占位符没改就别传给 Crossref

    since = dt.date.today() - dt.timedelta(days=window)
    log(f"▸ 抓取窗口 {since} 起 / {window} 天，共 {len(cfg.get('journals', []))} 种期刊")

    fresh: list[dict] = []
    for journal in cfg.get("journals", []):
        fresh.extend(fetch.fetch_journal(journal, since, mailto,
                                         rows=int(cfg.get("fetch", {}).get("rows", 500))))
    if cfg.get("fetch", {}).get("arxiv"):
        cats = cfg["fetch"].get("arxiv_categories") or ["physics.chem-ph"]
        fresh.extend(fetch.fetch_arxiv(cats, since))
    log(f"▸ 本轮抓到 {len(fresh)} 条")

    history = read_json(DATA / "papers.json", {"papers": []}).get("papers", [])
    papers = fetch.merge(fresh, history, keep)
    # 期刊从 config 里删掉后，历史数据里可能还留着它的旧条目——顺手剔掉
    allowed = {j["label"] for j in cfg.get("journals", [])}
    if cfg.get("fetch", {}).get("arxiv"):
        allowed.add("arXiv")
    keep_papers = [p for p in papers if p["j"] in allowed]
    if len(keep_papers) != len(papers):
        log(f"▸ 剔除已从配置移除的期刊条目 {len(papers) - len(keep_papers)} 篇")
    papers = keep_papers
    log(f"▸ 合并后共 {len(papers)} 篇（含历史 {len(history)} 篇）")

    papers, dropped = filters.apply(papers, cfg)
    if dropped:
        kinds = "、".join(sorted({(d.get("title") or "")[:28] for d in dropped})[:4])
        log(f"▸ 剔除期刊前置内容 {len(dropped)} 篇（如 {kinds}）")

    if (cfg.get("covers", {}).get("mode") or "auto").lower() != "off":
        log("▸ 抓取目录图（TOC graphic）")
        covers = covers_mod.collect(cfg)
        covers.update({k: v for k, v in covers_mod.probe_acs(papers, cfg).items() if v})
        hit = 0
        for p in papers:
            img = covers.get(p.get("doi") or "")
            if img:
                p["img"] = img
                hit += 1
        log(f"  · 命中 {hit} 篇（其余用生成封面）")

    if not args.no_translate:
        log("▸ 翻译标题")
        zh = translate.translate_papers(papers, cfg, budget=args.budget,
                                        pace=max(0.0, args.pace))
        for p in papers:
            if p["id"] in zh:
                p["zh"] = zh[p["id"]]
            p.pop("zh_pending", None)

    write_json(DATA / "papers.json", {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window_days": window,
        "papers": papers,
    })
    log("▸ 生成页面")
    build.build(cfg)
    log(f"✓ 完成，用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
