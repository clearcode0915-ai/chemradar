"""标题翻译层：MyMemory 免费接口 + 哈希缓存 + 单轮字符预算闸。

三条设计原则：
1. 只翻标题（几十字符），一天 40 篇 ≈ 4500 字符，匿名额度都够用。
2. 缓存按「原文哈希」存，翻过的不再花配额；换了标题才重翻。
3. 预算用完就停，不报错——下次运行自动接着补，页面先显示英文标题。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse

from src.util import DATA, http_get, log, read_json, write_json

MM = "https://api.mymemory.translated.net/get"
CACHE = DATA / "translations.json"

# 保护化学术语：按「词」判定，不靠正则硬啃——避免 CCSD(T) 掉括号、GFN2-xTB 被切碎
_TOKEN = re.compile(r"[A-Za-z0-9ωΩ()\-+]+")
_STOP = {"A", "I", "AN", "THE", "OF", "IN", "ON", "TO", "AND", "FOR", "IS", "AS",
         "AT", "BY", "OR", "WE", "IT", "NO", "NOT", "ALL", "CAN", "VIA", "US"}

_exhausted = threading.Event()   # 配额用尽
_throttled = threading.Event()   # 被限流（429）


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _is_term(part: str) -> bool:
    """DFT / CCSD(T) / XPS / B3LYP / GFN2 / xTB / Cu(111) / DeepMD → True"""
    if not part or part.upper() in _STOP:
        return False
    letters = [c for c in part if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    has_digit = any(c.isdigit() for c in part)
    if upper >= 2 and not any(c.islower() for c in letters):
        return True                                   # 全大写缩写：DFT / CCSD / XPS
    if has_digit and upper >= 1:
        return True                                   # 带数字：B3LYP / GFN2 / TiO2 / 3D
    return upper >= 2 and upper / len(letters) >= 0.5  # 驼峰式：DeepMD / xTB


def _protect(title: str) -> tuple[str, dict[str, str]]:
    """把不该被翻的术语换成 QQQnQQQ 占位符（实测 MyMemory 会原样返回）。

    单次扫描 + 整词分类：占位符生成后不会被二次匹配，杜绝嵌套占位符。
    """
    mapping: dict[str, str] = {}
    out: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(title):
        parts, changed = [], False
        for part in match.group(0).split("-"):
            if _is_term(part):
                key = f"QQQ{len(mapping) + 1}QQQ"
                mapping[key] = part
                parts.append(key)
                changed = True
            else:
                parts.append(part)
        if changed:
            out.append(title[pos:match.start()])
            out.append("-".join(parts))
            pos = match.end()
    out.append(title[pos:])
    return "".join(out), mapping


def _restore(text: str, mapping: dict[str, str]) -> str:
    for key, val in mapping.items():
        text = text.replace(key, val)
    text = re.sub(r"\s+([，。；：、）])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def translate_title(title: str, lang: str, email: str) -> str | None:
    """返回中文标题；None 表示这次没译成（配额或限流）。"""
    masked, mapping = _protect(title)
    params = {"q": masked, "langpair": f"en|{lang}"}
    if email:
        params["de"] = email
    url = f"{MM}?{urllib.parse.urlencode(params)}"
    try:
        payload = json.loads(http_get(url, timeout=30, retries=1).decode("utf-8", "replace"))
    except Exception as exc:
        if "429" in str(exc):
            _throttled.set()
        return None
    data = payload.get("responseData") or {}
    text = (data.get("translatedText") or "").strip()
    if payload.get("responseStatus") != 200 or not text or "MYMEMORY WARNING" in text.upper():
        if "MYMEMORY WARNING" in text.upper() or payload.get("quotaFinished"):
            _exhausted.set()
        return None
    return _restore(text, mapping)


def translate_papers(papers: list[dict], cfg: dict, budget: int | None = None,
                     pace: float = 0.5) -> dict[str, str]:
    """返回 {paper_id: 中文标题}，并把新译文写进缓存。

    顺序执行 + 固定间隔：免费接口按 IP 限流，并发只会换来 429。
    失败按 5/10/20/40s 退避重试，连续 6 次仍失败或退避累计超 300s 则本轮收工；
    已译部分每 20 条落盘一次，跑一半中断也不白干。
    """
    tcfg = cfg.get("translate", {}) or {}
    if (tcfg.get("backend") or "none").lower() != "mymemory":
        log("  · 翻译已关闭（backend != mymemory）")
        return {}

    cache: dict[str, str] = read_json(CACHE, {})
    lang = tcfg.get("lang", "zh-CN")
    email = (tcfg.get("email") or "").strip()
    auto = 45000 if email else 4500          # 有 email 额度 5 万字符，否则按匿名 5 千
    budget = int(budget or tcfg.get("max_chars_per_run") or 0) or auto
    out: dict[str, str] = {}
    todo: list[tuple[str, str]] = []
    used = hits = 0

    for paper in papers:                      # 已按时间倒序，优先翻最新的
        title = paper["title"]
        key = _hash(title)
        if key in cache:
            out[paper["id"]] = cache[key]
            hits += 1
            continue
        if used + len(title) > budget:
            continue
        used += len(title)
        todo.append((paper["id"], title))

    done = fails = slept = 0
    for pid, title in todo:
        zh = translate_title(title, lang, email)
        if zh:
            cache[_hash(title)] = zh
            out[pid] = zh
            done += 1
            fails = 0
            if done % 20 == 0:
                write_json(CACHE, cache)
            time.sleep(pace)
            continue
        # 失败：退避后再试，别因为一次 429 就放弃剩下的几百条
        fails += 1
        wait = min(45, 5 * 2 ** (fails - 1))
        if fails >= 6 or slept + wait > 300 or _exhausted.is_set():
            log(f"  · 连续 {fails} 次失败（已退避 {slept}s），本轮提前收工")
            break
        time.sleep(wait)
        slept += wait

    # 只保留仍在用的译文，避免缓存无限增长
    alive = {_hash(p["title"]) for p in papers}
    cache = {k: v for k, v in cache.items() if k in alive}
    write_json(CACHE, cache)

    missing = sum(1 for p in papers if p["id"] not in out)
    note = ""
    if _exhausted.is_set():
        note = "，免费配额已用尽（下次运行续译，或填 translate.email 提到 5 万/天）"
    elif _throttled.is_set():
        note = "，接口限流（下次运行续译）"
    log(f"  · 翻译：本次新增 {done} 条（{used} 字符 / 预算 {budget}），"
        f"缓存命中 {hits} 条，仍缺 {missing} 条{note}")
    return out
