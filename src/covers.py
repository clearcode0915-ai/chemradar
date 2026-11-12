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
import xml.etree.ElementTree as ET

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


def collect(cfg: dict) -> dict[str, str]:
    """遍历配置里带 rss 的期刊，汇总 {doi: 封面URL}。"""
    covers: dict[str, str] = {}
    total_items = total_img = 0
    for journal in cfg.get("journals", []):
        url = (journal.get("rss") or "").strip()
        if not url:
            continue
        label = journal["label"]
        try:
            raw = http_get(url, timeout=30, retries=1,
                           accept="application/rss+xml, application/xml;q=0.9, */*;q=0.8")
        except Exception as exc:
            log(f"  ! {label} 的 RSS 不可达（{type(exc).__name__}），跳过封面")
            continue
        got = parse_feed(raw)
        have = sum(1 for v in got.values() if v)
        total_items += len(got)
        total_img += have
        log(f"  · {label:8s} RSS {len(got):>3} 条，带图 {have:>3} 条")
        for doi, img in got.items():
            if img:
                covers[doi] = img
    if covers:
        log(f"  · 封面：{len(covers)} 条可用（共扫 {total_items} 条 RSS）")
    elif total_items == 0:
        log("  · 封面：未配置 RSS 或全部不可达，页面将使用生成封面")
    return covers
