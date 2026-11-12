"""生成层：papers.json + 译文缓存 → 单文件 site/index.html（数据内嵌，可离线打开）。"""

from __future__ import annotations

import datetime as dt
import json

from src.util import DATA, SITE, TEMPLATES, log, read_json, write_json

MAX_ABS = 1800  # 摘要截断长度，控制页面体积


def _payload(papers: list[dict], cfg: dict) -> dict:
    site = cfg.get("site", {})
    limit = int(site.get("page_limit", 0) or 0)
    total = len(papers)
    if limit and total > limit:
        papers = papers[:limit]
    journals = [{"label": j["label"], "name": j.get("name", j["label"]),
                 "color": j.get("color", "#888780")} for j in cfg.get("journals", [])]
    if cfg.get("fetch", {}).get("arxiv"):
        journals.append({"label": "arXiv", "name": "arXiv preprint", "color": "#CECBF6"})

    slim = []
    for p in papers:
        abs_txt = p.get("abs") or ""
        if len(abs_txt) > MAX_ABS:
            abs_txt = abs_txt[:MAX_ABS].rsplit(" ", 1)[0] + " …"
        slim.append({
            "id": p["id"],
            "doi": p.get("doi") or "",
            "title": p["title"],
            "zh": p.get("zh") or "",
            "authors": p.get("authors") or [],
            "j": p["j"],
            "ts": p["ts"],
            "edate": bool(p.get("edate")),
            "asap": bool(p.get("asap")),
            "oa": bool(p.get("oa")),
            "pre": bool(p.get("pre")),
            "abs": abs_txt,
            "pdf": p.get("pdf") or "",
            "url": p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else ""),
        })

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "site": {"title": site.get("title", "ChemRadar"),
                 "subtitle": site.get("subtitle", ""),
                 "window_days": site.get("window_days", 14)},
        "journals": journals,
        "total": total,
        "papers": slim,
    }


def build(cfg: dict) -> str:
    papers = read_json(DATA / "papers.json", {"papers": []}).get("papers", [])
    payload = _payload(papers, cfg)
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")  # 防止提前闭合 script

    tpl = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    html = (tpl
            .replace("__TITLE__", payload["site"]["title"])
            .replace("__SUBTITLE__", payload["site"]["subtitle"])
            .replace("__WINDOW__", str(payload["site"]["window_days"]))
            .replace("__LIMIT_NOTE__", "" if payload["total"] <= len(payload["papers"])
                     else f"（页面显示最近 {len(payload['papers'])} 篇，共 {payload['total']} 篇）")
            .replace("__BUILT_HUMAN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__DATA__", data_json))

    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "index.html"
    out.write_text(html, encoding="utf-8")
    write_json(SITE / "papers.json", payload)  # 顺带提供一份纯数据接口
    size_kb = len(html.encode("utf-8")) / 1024
    log(f"  · 已生成 {out.relative_to(DATA.parent).as_posix()} "
        f"（{len(papers)} 篇 / {size_kb:.0f} KB）")
    return str(out)
