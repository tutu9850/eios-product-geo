"""链接管理（收录检测真实版）

- 清单管理：添加/列表/删除（本地 JSON 存储）
- 收录检测：服务端请求 百度搜索 `site:域名` 判断是否收录（真实查询，非估算）
  反爬/超时时返回 unknown（检测受限），绝不造假。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok

router = APIRouter(prefix="/api/v1/links")

_DATA = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "geo_links.json"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _load() -> list[dict]:
    from app.services.store import get_store

    items = get_store().load("links")
    # 兼容：旧字段 status → index_status
    for item in items:
        if "index_status" not in item and "status" in item:
            item["index_status"] = item.pop("status", "pending")
        item.setdefault("index_status", "pending")
        item.setdefault("status_note", "待检测")
    return items


def _save(items: list[dict]) -> None:
    from app.services.store import get_store

    get_store().save("links", items)


async def _check_indexed(url: str) -> tuple[str, str]:
    """真实收录检测：百度优先，备用引擎兜底。返回 (状态, 说明)"""
    try:
        domain = urlparse(url).netloc
    except Exception:  # noqa: BLE001
        return "unknown", "URL 格式错误"
    if not domain:
        return "unknown", "无有效域名"

    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}, trust_env=False) as client:
        # 1) 百度
        try:
            r = await client.get(f"https://www.baidu.com/s?wd=site%3A{domain}")
            text = r.text
            if "百度安全验证" in text or "wappass" in text:
                pass  # 被反爬拦，换备用引擎
            elif "没有找到该URL" in text or "抱歉，没有找到" in text or "未找到相关结果" in text:
                return "failed", "百度未收录"
            elif "百度为您找到相关结果" in text:
                return "indexed", "百度已收录"
            else:
                # 结果列表特征
                if "c-container" in text and domain in text:
                    return "indexed", "百度已收录"
                return "unknown", "百度结果异常"
        except Exception:  # noqa: BLE001
            pass

        # 2) 备用引擎兜底
        try:
            r = await client.get(f"https://cn.bing.com/search?q=site%3A{domain}")
            text = r.text
            if "没有与此相关的结果" in text or "未找到任何结果" in text or "No results found" in text:
                return "failed", "未收录（搜索引擎查询）"
            if 'class="b_algo"' in text:
                return "indexed", "已收录"
            return "unknown", "查询结果异常"
        except Exception:  # noqa: BLE001
            pass

    return "unknown", "检测受限（反爬/超时）"


class LinkIn(BaseModel):
    url: str
    name: str = ""


@router.get("")
async def list_links():
    items = _load()
    indexed = sum(1 for l in items if l.get("index_status") == "indexed")
    failed = sum(1 for l in items if l.get("index_status") == "failed")
    pending = sum(1 for l in items if l.get("index_status") in (None, "pending"))
    unknown = sum(1 for l in items if l.get("index_status") == "unknown")
    return ok({"items": items, "stats": {"total": len(items), "indexed": indexed, "failed": failed, "pending": pending, "unknown": unknown}})


@router.post("")
async def add_link(payload: LinkIn):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    items = _load()
    if any(l["url"] == url for l in items):
        return ok({"added": False, "reason": "duplicate"})
    items.insert(
        0,
        {
            "id": "l_" + uuid.uuid4().hex[:12],
            "url": url,
            "name": payload.name.strip() or url,
            "index_status": "pending",
            "status_note": "待检测",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _save(items)
    return ok({"added": True, "id": items[0]["id"]})


@router.delete("/{link_id}")
async def delete_link(link_id: str):
    items = _load()
    new_items = [l for l in items if l["id"] != link_id]
    _save(new_items)
    return ok({"deleted": len(items) != len(new_items)})


class CheckIn(BaseModel):
    id: str | None = None
    url: str | None = None


@router.post("/check")
async def check_link(payload: CheckIn):
    """检测单个链接收录状态（真实查询百度，备用引擎兜底）"""
    items = _load()
    item = None
    if payload.id:
        item = next((l for l in items if l["id"] == payload.id), None)
    if not item and payload.url:
        item = next((l for l in items if l["url"] == payload.url), None)
    if not item:
        return ok({"checked": False, "reason": "not_found"})

    status, note = await _check_indexed(item["url"])
    item["index_status"] = status
    item["status_note"] = note
    item["checked_at"] = datetime.now(timezone.utc).isoformat()
    _save(items)
    return ok({"checked": True, "index_status": status, "status_note": note})


@router.post("/check-all")
async def check_all():
    """批量检测：所有非 indexed 的链接"""
    items = _load()
    results = []
    for item in items:
        if item.get("index_status") == "indexed":
            results.append({"id": item["id"], "index_status": "indexed", "status_note": "跳过（已收录）"})
            continue
        status, note = await _check_indexed(item["url"])
        item["index_status"] = status
        item["status_note"] = note
        item["checked_at"] = datetime.now(timezone.utc).isoformat()
        results.append({"id": item["id"], "index_status": status, "status_note": note})
    _save(items)
    return ok({"checked": len(results), "results": results})
