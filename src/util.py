"""公共工具：配置加载、带重试的 HTTP GET、日志。零第三方依赖。"""

from __future__ import annotations

import html
import json
import os
import re
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
TEMPLATES = ROOT / "templates"

_UA = "lit-radar/1.0 (literature feed; +https://github.com/)"


def load_config(path: Path | None = None) -> dict:
    path = path or (ROOT / "config.toml")
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    # 环境变量优先，方便在 GitHub Actions 里用 secrets 覆盖
    if os.environ.get("CROSSREF_MAILTO"):
        cfg.setdefault("fetch", {})["mailto"] = os.environ["CROSSREF_MAILTO"]
    if os.environ.get("MYMEMORY_EMAIL"):
        cfg.setdefault("translate", {})["email"] = os.environ["MYMEMORY_EMAIL"]
    return cfg


def http_get(url: str, *, timeout: int = 45, retries: int = 3, mailto: str = "",
             headers: dict | None = None, accept: str = "application/json") -> bytes:
    """GET，遇到 429/5xx/网络抖动自动退避重试。"""
    hdrs = {"User-Agent": f"{_UA} mailto:{mailto}" if mailto else _UA, "Accept": accept}
    if headers:
        hdrs.update(headers)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ssl.create_default_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1) + (4 if exc.code == 429 else 0))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET 失败：{url} -> {last}")


def get_json(url: str, **kw) -> dict:
    return json.loads(http_get(url, **kw).decode("utf-8", "replace"))


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log(f"警告：{path.name} 解析失败，已当作空文件处理")
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def log(*args) -> None:
    print(*args, file=sys.stderr, flush=True)


def clean_markup(text: str) -> str:
    """去掉 JATS/HTML 标签与多余空白，用于摘要。"""
    if not text:
        return ""
    text = re.sub(r"<jats:title>.*?</jats:title>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(abstract|摘要)[:：\s]+", "", text, flags=re.I)
    return text


__all__ = ["ROOT", "DATA", "SITE", "TEMPLATES", "load_config", "http_get", "get_json",
           "read_json", "write_json", "log", "clean_markup"]
