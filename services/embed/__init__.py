"""embed 服务 — 素材向量化 + 混合检索（S1b）

中文召回实验结论（2026-08-07，20 条语料同义改写查询）：nomic-embed-text 召回@3=4/5
但目标常排 2-3 名、相似度区分度差（0.68-0.84 挤在一起）→ **不可单独依赖向量**。

方案：n-gram 关键词为主 + 向量语义补充的混合检索：
- n-gram：查询核心词（去停用字）在标题/内容的重叠计分（精确、确定性）
- 向量：Ollama nomic-embed-text → Qdrant collection geo_materials（无 Qdrant 落内存，重启重建）
- 混合：两边 top-k 合并去重，n-gram 命中加权，向量仅作语义补充

诚实：向量无效时（Ollama 挂/embed 失败）自动降级为纯 n-gram，不报错不编造。
"""
import hashlib
import json
import math
import re
import time
from pathlib import Path

import httpx

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

DATA_DIR = Path(__file__).resolve().parents[2] / "apps" / "data"

# 停用字（中文检索核心词提取用）
_STOP = set("的了是和我你有他这那在也都不就与及或而于被把让给对从到去个们吧吗呢啊呀吧")

# 内存缓存：{material_id: {"title":..., "content":..., "vector":[...]}}（无 Qdrant 模式）
_mem_index: dict[str, dict] = {}
_mem_loaded = False

_QDRANT_URL = "http://127.0.0.1:6333"
_QDRANT_COLL = "geo_materials"


def _qdrant_alive() -> bool:
    try:
        r = httpx.get(f"{_QDRANT_URL}/collections", timeout=2)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _qdrant_ensure_collection() -> None:
    r = httpx.get(f"{_QDRANT_URL}/collections/{_QDRANT_COLL}", timeout=3)
    if r.status_code == 200:
        return
    httpx.put(
        f"{_QDRANT_URL}/collections/{_QDRANT_COLL}",
        json={"vectors": {"size": EMBED_DIM, "distance": "Cosine"}},
        timeout=5,
    )


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Ollama embed；失败返回 None（调用方降级）"""
    try:
        r = await httpx.AsyncClient(timeout=60).post(
            f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts}
        )
        r.raise_for_status()
        return r.json()["embeddings"]
    except Exception:  # noqa: BLE001
        return None


def _n_gram_keys(text: str) -> set[str]:
    """中文检索核心词：去停用字后的 2-gram 集合（标题+内容）"""
    chars = [c for c in text if c.strip() and c not in _STOP and not c.isspace()]
    keys = set()
    for i in range(len(chars) - 1):
        keys.add(chars[i] + chars[i + 1])
    if chars:
        keys.add(chars[0])
    return keys


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-12)


def _load_materials() -> list[dict]:
    from services._db import load_table

    return load_table("geo_kb")


def _load_mem_index() -> dict[str, dict]:
    """内存向量索引（无 Qdrant 模式）：懒加载 + embed 缓存"""
    global _mem_loaded
    if _mem_loaded:
        return _mem_index
    cache_file = DATA_DIR / "geo_material_vectors.json"
    try:
        if cache_file.exists():
            _mem_index.update(json.loads(cache_file.read_text("utf-8")))
    except Exception:  # noqa: BLE001
        pass
    _mem_loaded = True
    return _mem_index


def _save_mem_index() -> None:
    cache_file = DATA_DIR / "geo_material_vectors.json"
    try:
        cache_file.write_text(json.dumps(_mem_index, ensure_ascii=False), "utf-8")
    except Exception:  # noqa: BLE001
        pass


def _point_id(material_id: str) -> int:
    """素材 → Qdrant point id（与 ensure_vectors 的 upsert 计算保持一致）"""
    return int(hashlib.md5(str(material_id).encode()).hexdigest()[:16], 16)


async def delete_vectors(material_id: str) -> bool:
    """删除素材向量（Qdrant 点 + 内存索引），幂等。

    修复（审计 H5）：原 delete_material 只删 DB 行，Qdrant 残留孤儿点。
    返回 True=已尝试清理；Qdrant 不可用时静默（内存索引同样清理）。
    """
    # 内存索引清理（无 Qdrant 模式）
    _mem_index.pop(material_id, None)
    _save_mem_index()
    # Qdrant 点删除
    try:
        if not _qdrant_alive():
            return True
        r = await httpx.AsyncClient(timeout=10).post(
            f"{_QDRANT_URL}/collections/{_QDRANT_COLL}/points/delete?wait=true",
            json={"points": [_point_id(material_id)]},
        )
        return r.status_code in (200, 404)
    except Exception:  # noqa: BLE001
        return False


async def ensure_vectors(materials: list[dict] | None = None) -> dict:
    """素材向量化（幂等：status=vectorized 的跳过）；返回统计

    Qdrant 在 → upsert collection geo_materials；不在 → 内存索引 + 落盘缓存（重启重建）。
    """
    materials = materials if materials is not None else _load_materials()
    use_qdrant = _qdrant_alive()
    indexed = 0
    skipped = 0
    failed = 0

    if use_qdrant:
        _qdrant_ensure_collection()
        pts = []
        for m in materials:
            if m.get("status") == "vectorized":
                skipped += 1
                continue
            text = f"{m.get('title','')}\n{m.get('content','')}"
            if not text.strip():
                skipped += 1
                continue
            vecs = await embed_texts([text[:2000]])
            if not vecs:
                failed += 1
                continue
            pts.append({
                "id": int(hashlib.md5(str(m["id"]).encode()).hexdigest()[:16], 16),
                "vector": vecs[0],
                "payload": {"material_id": m["id"], "title": m.get("title", "")[:120]},
            })
            m["status"] = "vectorized"
            indexed += 1
        if pts:
            await httpx.AsyncClient(timeout=60).put(
                f"{_QDRANT_URL}/collections/{_QDRANT_COLL}/points?wait=true",
                json={"points": pts},
            )
        if indexed:
            from services._db import save_table

            save_table("geo_kb", materials)
    else:
        idx = _load_mem_index()
        for m in materials:
            if m.get("status") == "vectorized" or m["id"] in idx:
                skipped += 1
                continue
            text = f"{m.get('title','')}\n{m.get('content','')}"
            if not text.strip():
                skipped += 1
                continue
            vecs = await embed_texts([text[:2000]])
            if not vecs:
                failed += 1
                continue
            idx[m["id"]] = {"title": m.get("title", ""), "content": m.get("content", "")[:2000], "vector": vecs[0]}
            m["status"] = "vectorized"
            indexed += 1
        if indexed:
            from services._db import save_table

            save_table("geo_kb", materials)
        _save_mem_index()

    return {"use_qdrant": use_qdrant, "indexed": indexed, "skipped": skipped, "failed": failed, "total": len(materials)}


async def hybrid_search(q: str, top_k: int = 8) -> list[dict]:
    """混合检索：n-gram 关键词为主 + 向量语义补充（向量不可用自动降级纯 n-gram）

    懒向量化：collection 无点时自动先 ensure_vectors（素材已向量化的跳过，幂等秒过）。
    """
    q = (q or "").strip()
    if not q:
        return []
    materials = _load_materials()
    if not materials:
        return []

    # 懒向量化：Qdrant collection 不存在或空时先建（幂等：status=vectorized 跳过）
    try:
        if _qdrant_alive():
            coll = httpx.get(f"{_QDRANT_URL}/collections/{_QDRANT_COLL}", timeout=3)
            empty = coll.status_code != 200 or coll.json().get("result", {}).get("points_count", 0) == 0
            if empty:
                await ensure_vectors(materials)
        else:
            idx = _load_mem_index()
            if not idx:
                await ensure_vectors(materials)
    except Exception:  # noqa: BLE001
        pass  # 向量不可用不影响 n-gram 主路径

    q_keys = _n_gram_keys(q)

    # 1) n-gram 得分（标题 2x + 内容 1x）
    ng_scores: dict[str, float] = {}
    for m in materials:
        title = m.get("title", "")
        content = m.get("content", "")
        t_hit = len(q_keys & _n_gram_keys(title))
        c_hit = len(q_keys & _n_gram_keys(content))
        score = t_hit * 2.0 + c_hit
        if score > 0:
            ng_scores[m["id"]] = score

    # 2) 向量得分（语义补充）
    vec_scores: dict[str, float] = {}
    q_vec = await embed_texts([q[:500]])
    if q_vec:
        if _qdrant_alive():
            try:
                r = await httpx.AsyncClient(timeout=10).post(
                    f"{_QDRANT_URL}/collections/{_QDRANT_COLL}/points/search",
                    json={"vector": q_vec[0], "limit": top_k * 2, "with_payload": True},
                )
                for hit in r.json().get("result", []):
                    mid = hit.get("payload", {}).get("material_id")
                    if mid:
                        vec_scores[mid] = hit.get("score", 0)
            except Exception:  # noqa: BLE001
                vec_scores = {}
        if not vec_scores:
            # 内存模式：全量余弦
            idx = _load_mem_index()
            for mid, rec in idx.items():
                vec_scores[mid] = _cos(q_vec[0], rec["vector"])

    # 3) 混合：n-gram 命中为主（保底返回），向量结果补充合并
    combined: dict[str, dict] = {}
    for mid, s in ng_scores.items():
        combined[mid] = {"id": mid, "n_gram": round(s, 2), "vector": round(vec_scores.get(mid, 0) * 10, 2), "score": round(s + vec_scores.get(mid, 0) * 5, 2)}
    for mid, s in vec_scores.items():
        if mid not in combined:
            combined[mid] = {"id": mid, "n_gram": 0, "vector": round(s * 10, 2), "score": round(s * 5, 2)}

    ranked = sorted(combined.values(), key=lambda x: -x["score"])[:top_k]
    by_id = {m["id"]: m for m in materials}
    out = []
    for r in ranked:
        m = by_id.get(r["id"])
        if not m:
            continue  # 孤儿向量（素材已删除但 Qdrant/缓存点残留）→ 跳过不展示
        r["title"] = m.get("title", "")
        r["source_type"] = m.get("source_type", "text")
        out.append(r)
    return out


def _snippet(text: str, q: str, span: int = 60) -> str:
    """命中片段：定位 q 核心词附近"""
    if not text:
        return ""
    for key in sorted(_n_gram_keys(q), key=len, reverse=True):
        idx = text.find(key)
        if idx >= 0:
            return text[max(0, idx - span // 2): idx + span]
    return text[:span]
