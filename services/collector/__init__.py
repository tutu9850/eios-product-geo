"""collector 模块 — 外部采集（官网/新闻/知乎 URL → raw 落盘）

S1 激活：复用 diagnose 的抓取方式（httpx + UA + bs4 正文提取）。
规则：独立目录、独立日志、只走接口调用；反爬失败返回明确错误，绝不编造内容。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from app.security.url import UnsafeURL, redirect_url, validate_public_url

RAW_FILE = Path(__file__).resolve().parents[2] / "apps" / "data" / "geo_collect_raw.json"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _load_raw() -> list[dict]:
    from services._db import load_table

    return load_table("geo_collect_raw")


def _save_raw(items: list[dict]) -> None:
    from services._db import save_table

    save_table("geo_collect_raw", items)


def _extract_text(soup: BeautifulSoup, max_len: int = 4000) -> str:
    """正文提取：去 script/style/nav/footer，取文本截断"""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:max_len]


async def fetch_page(url: str) -> dict:
    """抓取单页 → {title, text, url, error}；失败返回 error 不抛（诚实：受限/失败如实说）"""
    try:
        current = validate_public_url(url)
        async with httpx.AsyncClient(
            timeout=12, follow_redirects=False,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        ) as client:
            for _ in range(4):
                resp = await client.get(current)
                if resp.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = resp.headers.get("location")
                if not location:
                    return {"url": url, "title": "", "text": "", "error": "重定向缺少目标地址"}
                current = redirect_url(current, location)
            else:
                return {"url": url, "title": "", "text": "", "error": "重定向次数过多"}
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""
            if not title:
                h1 = soup.find("h1")
                title = h1.get_text(strip=True)[:80] if h1 else url
            return {"url": url, "title": title[:120], "text": _extract_text(soup)}
    except UnsafeURL as exc:
        return {"url": url, "title": "", "text": "", "error": f"UnsafeURL: {str(exc)[:120]}"}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "title": "", "text": "", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


async def collect_url(watch_item: dict) -> dict:
    """采集单个关注项 → raw 记录（重复采集追加新记录，保留历史）"""
    url = (watch_item.get("url") or "").strip()
    if not url:
        return {"error": "该关注项没有 URL，暂无法采集（关键词监控待接入）", "watch_id": watch_item.get("id")}
    fetched = await fetch_page(url)
    if fetched.get("error"):
        return {"error": fetched["error"], "watch_id": watch_item.get("id")}
    raw = {
        "id": f"s_{uuid.uuid4().hex[:10]}",
        "watch_id": watch_item.get("id"),
        "source_type": watch_item.get("type", "website"),
        "source_name": watch_item.get("name", ""),
        "url": url,
        "title": fetched["title"] or url,
        "text": fetched["text"],
        "status": "raw",  # raw → extracted → confirmed(写企业知识库) / planned(入计划) / ignored
        "facts": [],
        "extracted_at": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_raw()
    items.insert(0, raw)
    _save_raw(items)
    return {"signal": raw}


def set_signal_status(signal_id: str, status: str, facts: list | None = None) -> dict | None:
    """更新信号状态（extracted/confirmed/planned/ignored），返回更新后的信号"""
    items = _load_raw()
    for s in items:
        if s.get("id") == signal_id:
            s["status"] = status
            if facts is not None:
                s["facts"] = facts
            _save_raw(items)
            return s
    return None
