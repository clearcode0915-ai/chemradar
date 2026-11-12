"""内容过滤：剔除期刊前置内容（封面、编委会、目录、出版信息）等非研究条目。

这些条目在 Crossref 里同样是 type:journal-article，只能用标题特征 + 结构特征识别。
结构特征很好用：真正的论文一定有作者，前置内容通常既无作者也无摘要。
"""

from __future__ import annotations

import re

# 兜底清单：config 里没写也能挡住最常见的几类（ACS/RSC/Wiley 的老套路）
DEFAULT_PATTERNS = [
    r"^(issue\s+)?(editorial\s+)?masthead$",
    r"issue\s+publication\s+information",
    r"^issue\s+information$",
    r"^(inside\s+)?(front|back)\s+cover$",
    r"^contents\s+list$",
    r"^table\s+of\s+contents$",
    r"^in\s+this\s+issue$",
    r"^front\s+matter$",
]


def compile_patterns(cfg: dict) -> list[re.Pattern]:
    raw = ((cfg.get("filter") or {}).get("drop_titles") or [])
    patterns = list(raw) if raw else list(DEFAULT_PATTERNS)
    out = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.I))
        except re.error:
            continue
    return out


def is_front_matter(paper: dict, patterns: list[re.Pattern], drop_anonymous: bool) -> bool:
    title = (paper.get("title") or "").strip()
    if any(p.search(title) for p in patterns):
        return True
    if drop_anonymous and not paper.get("authors") and not paper.get("abs"):
        return True
    return False


def apply(papers: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """返回 (保留的条目, 被剔除的条目)。"""
    patterns = compile_patterns(cfg)
    drop_anonymous = bool((cfg.get("filter") or {}).get("drop_anonymous", True))
    keep, dropped = [], []
    for p in papers:
        (dropped if is_front_matter(p, patterns, drop_anonymous) else keep).append(p)
    return keep, dropped
