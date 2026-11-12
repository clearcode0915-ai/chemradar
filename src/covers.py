"""封面层：从期刊 RSS 里取 TOC 图形（目录图）URL。

为什么不用 Crossref：Crossref 只有元数据，没有图。ACS 的目录图托管在
acs.silverchair-cdn.com，URL 形如
  /acs/content_public/journal/{刊代码}/pap/{DOI}/1/{art}_{图号}.png
图号不可推导，只能从 RSS/文章页里读。RSS 是唯一不依赖反爬的入口。

网络现实：pubs.acs.org 在国内常被阻断，GitHub Actions 上一般可达。
因此本模块失败时只记一行日志，页面会退回「生成封面」，不影响其它流程。
"""

from __future__ import annotations

import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from src.util import http_get, log

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>,;)]+", re.I)
_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}


def _clean_doi(doi: str) -> str:
    return doi.rstrip(".,;)").lower()


def _img_from_item(item: ET.Element) -> str:
    # 1) media:content / media:thumbnail（ACS、Wiley 常见）
    for tag in ("media:content", "media:thumbnail"):
        for node in item.iter():
            if node.tag.endswith("}content") or node.tag.endswith("}thumbnail"):
                url = node.get("url") or ""
                if url and (node.get("type", "").startswith("image") or
                            re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", url, re.I)):
                    return url
    # 2) enclosure type=image/*
    for node in item.iter():
        if node.tag.endswith("enclosure"):
            url = node.get("url") or ""
            if url and (node.get("type") or "").startswith("image"):
                return url
    # 3) 描述/正文里内嵌的 <img>
    for node in item.iter():
        if node.tag.endswith("}encoded") or node.tag.endswith("}description") or node.tag == "description":
            found = _IMG.search(node.text or "")
            if found:
                return found.group(1)
    return ""


def parse_feed(raw: bytes) -> dict[str, str]:
    """返回 {doi: 图片URL}；取不到 DOI 或图的条目直接跳过。"""
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
    """并发拉取各刊 RSS；同一域名只要有一个不通，就跳过该域后续的刊。

    实测出版方站点对机房 IP 常直接不通，逐个等超时会让整个任务白等几分钟。
    """
    jobs = [(j, (j.get("rss") or "").strip()) for j in cfg.get("journals", [])]
    jobs = [(j, u) for j, u in jobs if u]
    if not jobs:
        log("  · 封面：未配置 RSS，全部使用生成封面")
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
                if err == "skip":
                    log(f"  · {label:8s} 跳过（同域已判定不可达）")
                else:
                    log(f"  ! {label:8s} RSS 不可达（{err}）")
                continue
            have = sum(1 for v in got.values() if v)
            log(f"  · {label:8s} RSS {len(got):>3} 条，带图 {have:>3} 条")
            covers.update({k: v for k, v in got.items() if v})

    if covers:
        log(f"  · 封面：{len(covers)} 条可用")
    else:
        log("  · 封面：无可用真图，全部使用生成封面")
    return covers
