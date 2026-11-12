"""抓取层：Crossref(按 ISSN) + 可选 arXiv 预印本。

设计取舍：不爬 ACS/AIP 页面（Cloudflare 会拦），直接用 Crossref 的元数据接口——
实测 12 种目标期刊的摘要都由出版方 deposit 到了 Crossref，一次请求就拿全字段。
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET

from src.util import clean_markup, get_json, http_get, log

CROSSREF = "https://api.crossref.org/works"
ARXIV = "https://export.arxiv.org/api/query"

SELECT = ",".join([
    "DOI", "title", "subtitle", "author", "abstract", "container-title", "issued",
    "created", "published-online", "published-print", "volume", "issue", "page",
    "type", "is-referenced-by-count", "URL", "license", "link", "publisher",
])

ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


# ────────────────────────────── 小工具 ──────────────────────────────
def _date_parts(item: dict, key: str) -> tuple[dt.datetime | None, int]:
    """返回 (时间, 精度)；精度 1=只到年、2=到月、3=到日。

    RSC 等出版方常只给年份，硬按 1 月 1 日算会把这些「新文章」误判成半年前，
    进而被历史窗口过滤掉——所以精度必须一起返回。
    """
    parts = (item.get(key) or {}).get("date-parts") or [[None]]
    ymd = parts[0] if parts else [None]
    if not ymd or not ymd[0]:
        return None, 0
    y = int(ymd[0])
    m = int(ymd[1]) if len(ymd) > 1 and ymd[1] else 1
    d = int(ymd[2]) if len(ymd) > 2 and ymd[2] else 1
    precision = len([x for x in ymd[:3] if x])
    try:
        return dt.datetime(y, m, d, tzinfo=dt.timezone.utc), precision
    except ValueError:
        return None, 0


def _norm_title(title: str) -> str:
    title = clean_markup(title).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title)[:120]


def _authors(item: dict) -> list[str]:
    out = []
    for a in item.get("author") or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p)
        if not name:
            name = a.get("name") or ""
        name = re.sub(r"\s+", " ", name).strip()
        if name:
            out.append(name)
    return out


def _is_oa(item: dict) -> bool:
    for lic in item.get("license") or []:
        if "creativecommons.org" in (lic.get("URL") or ""):
            return True
    return False


def _pdf_link(item: dict) -> str:
    for link in item.get("link") or []:
        if (link.get("content-type") or "").lower() == "application/pdf":
            return link.get("URL") or ""
    return ""


# ────────────────────────────── Crossref ──────────────────────────────
def fetch_journal(journal: dict, since: dt.date, mailto: str, rows: int = 500) -> list[dict]:
    label, issn = journal["label"], journal["issn"]
    params = {
        "filter": f"issn:{issn},from-created-date:{since.isoformat()},type:journal-article",
        "rows": str(min(rows, 1000)),
        "sort": "created",
        "order": "desc",
        "select": SELECT,
    }
    url = f"{CROSSREF}?{urllib.parse.urlencode(params)}"
    try:
        msg = get_json(url, mailto=mailto)["message"]
    except Exception as exc:  # 单刊失败不影响整体
        log(f"  ! {label} 抓取失败：{exc}")
        return []

    items = msg.get("items") or []
    total = msg.get("total-results", len(items))
    if total > len(items):
        log(f"  ! {label} 返回 {len(items)}/{total} 条，已按接口上限截断")

    out = []
    for it in items:
        doi = (it.get("DOI") or "").lower()
        if not doi:
            continue
        title = clean_markup((it.get("title") or [""])[0]) or "(untitled)"
        sub = clean_markup((it.get("subtitle") or [""])[0])
        if sub and sub.lower() not in title.lower():
            title = f"{title}: {sub}"

        online, p_on = _date_parts(it, "published-online")
        issued, p_is = _date_parts(it, "issued")
        created, _ = _date_parts(it, "created")
        # 优先用精确到日的出版日期；只有年份的日期不可信，退回 DOI 注册时间
        if online and p_on >= 2:
            stamp, edate = online, False
        elif issued and p_is >= 2:
            stamp, edate = issued, False
        elif created:
            stamp, edate = created, True
        elif online or issued:
            stamp, edate = (online or issued), True
        else:
            continue

        volume, page = it.get("volume"), it.get("page")
        out.append({
            "id": doi,
            "doi": doi,
            "title": title,
            "authors": _authors(it),
            "j": label,
            "jname": clean_markup((it.get("container-title") or [journal["name"]])[0]),
            "ts": int(stamp.timestamp()),
            "date": stamp.date().isoformat(),
            "edate": edate,          # True = 日期其实是 DOI 注册日，不是出版日
            "asap": bool(online and not volume and not page),
            "oa": _is_oa(it),
            "pre": False,
            "abs": clean_markup(it.get("abstract") or ""),
            "pdf": _pdf_link(it),
            "url": it.get("URL") or f"https://doi.org/{doi}",
            "cites": it.get("is-referenced-by-count") or 0,
            "src": "crossref",
        })
    log(f"  · {label:8s} {len(out):>4} 篇")
    return out


# ────────────────────────────── arXiv ──────────────────────────────
def fetch_arxiv(categories: list[str], since: dt.date, max_results: int = 400) -> list[dict]:
    query = " OR ".join(f"cat:{c}" for c in categories)
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    url = f"{ARXIV}?{urllib.parse.urlencode(params)}"
    try:
        root = ET.fromstring(http_get(url, accept="application/atom+xml", timeout=60))
    except Exception as exc:
        log(f"  ! arXiv 抓取失败：{exc}")
        return []

    cutoff = dt.datetime.combine(since, dt.time.min, tzinfo=dt.timezone.utc)
    out = []
    for entry in root.findall("a:entry", ATOM):
        pub = entry.findtext("a:published", default="", namespaces=ATOM)
        try:
            stamp = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp < cutoff:
            continue
        raw_id = entry.findtext("a:id", default="", namespaces=ATOM)
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
        title = clean_markup(entry.findtext("a:title", default="", namespaces=ATOM))
        title = re.sub(r"\s+", " ", title)
        authors = []
        for a in entry.findall("a:author", ATOM):
            name = (a.findtext("a:name", default="", namespaces=ATOM) or "").strip()
            if name:
                authors.append(name)
        doi = (entry.findtext("arxiv:doi", default="", namespaces=ATOM) or "").lower()
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = ""
        for link in entry.findall("a:link", ATOM):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
        out.append({
            "id": doi or f"arxiv:{arxiv_id}",
            "doi": doi,
            "arxiv": arxiv_id,
            "title": title,
            "authors": authors,
            "j": "arXiv",
            "jname": "arXiv preprint",
            "ts": int(stamp.timestamp()),
            "date": stamp.date().isoformat(),
            "edate": False,          # 预印本提交日期就是准确日期
            "asap": False,
            "oa": True,
            "pre": True,
            "abs": clean_markup(entry.findtext("a:summary", default="", namespaces=ATOM)),
            "pdf": pdf_url or abs_url.replace("/abs/", "/pdf/"),
            "url": doi and f"https://doi.org/{doi}" or abs_url,
            "cites": 0,
            "src": "arxiv",
        })
    log(f"  · {'arXiv':8s} {len(out):>4} 篇")
    return out


# ────────────────────────────── 合并 ──────────────────────────────
def merge(fresh: list[dict], history: list[dict], keep_days: int) -> list[dict]:
    """新抓的覆盖旧的；同标题的预印本挂到正式发表条目上，避免重复。"""
    by_id: dict[str, dict] = {p["id"]: dict(p) for p in history}
    by_title: dict[str, str] = {_norm_title(p["title"]): p["id"] for p in history}

    for p in fresh:
        key = _norm_title(p["title"])
        twin = by_title.get(key)
        if twin and twin != p["id"] and twin in by_id:
            target = by_id[twin]
            if p["src"] == "arxiv" and target["src"] == "crossref":
                target["arxiv"] = p.get("arxiv", "")
                target["pdf"] = target.get("pdf") or p.get("pdf", "")
                target["pre"] = True
                continue
            if p["src"] == "crossref" and target["src"] == "arxiv":
                by_id.pop(twin, None)
        by_id[p["id"]] = dict(p)
        by_title[key] = p["id"]

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)
    papers = [p for p in by_id.values() if p["ts"] >= cutoff.timestamp()]
    papers.sort(key=lambda p: (p["ts"], p["id"]), reverse=True)
    return papers
