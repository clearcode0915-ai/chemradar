"""摘要补全：APS（PRL 等）不向 Crossref 提供摘要，只能从文章页取。

APS 的 landing page 把摘要放在 `id="abstract-section-content"` 里，
DOI 会跳转到 `/prl/accepted/...` 或 `/prl/abstract/...`，两种都能取到。
结果按 DOI 缓存，每篇只取一次；失败只影响该条没有摘要，不阻塞其它流程。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from src.util import DATA, log, read_json, write_json

CACHE = DATA / "abstracts.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"

_SEC = re.compile(
    r'id="abstract-section-content"[^>]*>(.*?)(?=</section>|<section)', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(fragment: str) -> str:
    text = _TAG.sub(" ", fragment)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    text = _WS.sub(" ", text).strip()
    return text


def fetch_abstract(doi: str, timeout: float = 15.0) -> str:
    """取一篇 APS 文章的摘要；取不到返回空串。"""
    url = f"https://doi.org/{doi}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""
    found = _SEC.search(html)
    if not found:
        return ""
    text = _clean(found.group(1))
    return text if len(text) > 40 else ""


def enrich(papers: list[dict], cfg: dict) -> int:
    """给缺摘要的 APS 条目补摘要，返回本轮补上的条数。"""
    acfg = cfg.get("abstracts") or {}
    if not acfg.get("enabled", True):
        return 0

    cache: dict[str, str] = read_json(CACHE, {})
    todo = [p for p in papers
            if not p.get("abs") and (p.get("doi") or "").startswith("10.1103/")
            and p["doi"] not in cache]
    limit = int(acfg.get("max_per_run", 60))
    batch = todo[:limit]
    if not batch:
        return 0

    log(f"  · 摘要补全：处理 {len(batch)} 篇 APS 条目（另有 {len(todo) - len(batch)} 篇留到下次）")

    def work(p):
        return p["doi"], fetch_abstract(p["doi"])

    hit = 0
    with ThreadPoolExecutor(max_workers=int(acfg.get("workers", 3))) as pool:
        for doi, txt in pool.map(work, batch):
            cache[doi] = txt
            hit += bool(txt)
    log(f"  · 摘要补全：成功 {hit}/{len(batch)}")

    for p in papers:                      # 回填到本轮数据
        text = cache.get(p.get("doi") or "")
        if text and not p.get("abs"):
            p["abs"] = text

    alive = {p.get("doi") for p in papers}
    cache = {k: v for k, v in cache.items() if k in alive}
    write_json(CACHE, cache)
    return hit
