"""封面层：ACS 目录图（TOC graphic）的获取。

两条路：
1. `collect()`   —— 出版方 RSS（最权威，但 pubs.acs.org 对机房 IP 常不可达）
2. `probe_acs()` —— **直接问 CDN**：图片托管在 acs.silverchair-cdn.com，不校验签名。
   URL 形状固定：/{刊路径}/pap/{DOI 下划线化}/1/{前缀}{稿件号}_{图号}.png
   图号不可推导，但实测「最大存在的图号 = 目录图」（与参考站 9/9 一致），
   不存在的图号 CDN 返回 403，所以从大到小试，第一个 200 就是目录图。

注意：这是尽力而为的探测，不是官方接口。结果按 DOI 缓存，每篇只探一次；
CDN 若限流，只是拿不到封面，不影响其它流程。
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from src.util import DATA, http_get, log, read_json, write_json

CDN = "https://acs.silverchair-cdn.com/acs/content_public/journal"
CACHE = DATA / "covers.json"
_UA = "Mozilla/5.0 (compatible; lit-radar/1.0)"

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>,;)]+", re.I)
_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def _clean_doi(doi: str) -> str:
    return doi.rstrip(".,;)").lower()


# ─────────────────────────── 1. RSS ───────────────────────────
def _img_from_item(item: ET.Element) -> str:
    for node in item.iter():
        if node.tag.endswith("}content") or node.tag.endswith("}thumbnail"):
            url = node.get("url") or ""
            if url and (node.get("type", "").startswith("image") or
                        re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", url, re.I)):
                return url
    for node in item.iter():
        if node.tag.endswith("enclosure"):
            url = node.get("url") or ""
            if url and (node.get("type") or "").startswith("image"):
                return url
    for node in item.iter():
        if node.tag.endswith("}encoded") or node.tag.endswith("}description") or node.tag == "description":
            found = _IMG.search(node.text or "")
            if found:
                return found.group(1)
    return ""


def parse_feed(raw: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        log(f"  ! RSS 解析失败：{exc}")
        return {}
    out: dict[str, str] = {}
    for item in root.iter("item"):
        blob = ET.tostring(item, encoding="unicode")
        dois = _DOI.findall(blob)
        if not dois:
            continue
        img = _img_from_item(item)
        for doi in dois:
            key = _clean_doi(doi)
            if img:
                out[key] = img
            else:
                out.setdefault(key, "")
    return out


def _host_of(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def collect(cfg: dict, workers: int = 6, timeout: int = 12) -> dict[str, str]:
    """并发拉取各刊 RSS；同一域名只要一个不通，就跳过该域后续的刊。"""
    jobs = [(j, (j.get("rss") or "").strip()) for j in cfg.get("journals", [])]
    jobs = [(j, u) for j, u in jobs if u]
    if not jobs:
        return {}

    dead: set[str] = set()
    lock = threading.Lock()

    def one(job):
        journal, url = job
        host = _host_of(url)
        with lock:
            if host in dead:
                return journal["label"], None, "skip"
        try:
            raw = http_get(url, timeout=timeout, retries=0,
                           accept="application/rss+xml, application/xml;q=0.9, */*;q=0.8")
        except Exception as exc:
            with lock:
                dead.add(host)
            return journal["label"], None, type(exc).__name__
        return journal["label"], parse_feed(raw), ""

    covers: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for label, got, err in pool.map(one, jobs):
            if got is None:
                if err != "skip":
                    log(f"  ! {label:8s} RSS 不可达（{err}）")
                continue
            have = sum(1 for v in got.values() if v)
            log(f"  · {label:8s} RSS {len(got):>3} 条，带图 {have:>3} 条")
            covers.update({k: v for k, v in got.items() if v})
    return covers


# ─────────────────────── 2. CDN 反推（主用） ───────────────────────
def _head_ok(url: str, timeout: float = 6.0) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False          # 403/404 = 这个图号不存在
    except Exception:
        return False          # 网络问题当作没有，别阻塞整轮


def _acs_url(doi: str, key: str, prefix: str, n: int) -> str:
    art = prefix + doi.rsplit(".", 1)[-1]
    return f"{CDN}/{key}/pap/{doi.replace('/', '_')}/1/{art}_{n:04d}.png"


def _probe(doi: str, key: str, prefix: str, top: int) -> str:
    for n in range(top, 0, -1):
        url = _acs_url(doi, key, prefix, n)
        if _head_ok(url):
            return url
    return ""


def probe_acs(papers: list[dict], cfg: dict) -> dict[str, str]:
    """给 ACS 各刊条目反推目录图地址；按 DOI 缓存，每篇只探一次。"""
    ccfg = cfg.get("covers") or {}
    if not ccfg.get("probe_acs", True):
        return {}
    acs = {j["label"]: (j["acs_key"], j["acs_prefix"])
           for j in cfg.get("journals", []) if j.get("acs_key") and j.get("acs_prefix")}
    if not acs:
        return {}

    cache: dict[str, str] = read_json(CACHE, {})
    todo = [p for p in papers
            if p["j"] in acs and (p.get("doi") or "").startswith("10.1021/")
            and p["doi"] not in cache]
    limit = int(ccfg.get("max_probe_per_run", 250))
    batch = todo[:limit]
    if not batch:
        log(f"  · 封面：探测缓存已覆盖（{len(cache)} 条）")
    else:
        top = int(ccfg.get("probe_max_index", 16))
        log(f"  · 封面：探测 {len(batch)} 篇（另有 {len(todo) - len(batch)} 篇留到下次）")

        def work(p):
            key, prefix = acs[p["j"]]
            return p["doi"], _probe(p["doi"], key, prefix, top)

        hit = 0
        with ThreadPoolExecutor(max_workers=int(ccfg.get("probe_workers", 4))) as pool:
            for doi, url in pool.map(work, batch):
                cache[doi] = url
                hit += bool(url)
        log(f"  · 封面：本轮命中 {hit}/{len(batch)}")

    alive = {p.get("doi") for p in papers}
    cache = {k: v for k, v in cache.items() if k in alive}
    write_json(CACHE, cache)

    got = {k: v for k, v in cache.items() if v}
    if got:
        log(f"  · 封面：累计 {len(got)} 篇有真图")
    return got
