"""GEO 自动配置（Auto-Configure）——首次使用引导编排

流程（用户拍板）：空态触发 → 知识库检测 → 勾选确认 → 竞品发现 → 自动建对象
→ 自动监测（lite）→ 蒸馏闭环 → 内容选项卡生成（前端）。

设计：分步接口（前端引导组件逐步驱动，勾选确认在步骤间）：
- POST /auto-config  body: {"step": "detect"}                  → 实体候选（公司/产品/行业）
- POST /auto-config  body: {"step": "discover", "products": []} → 竞品候选
- POST /auto-config  body: {"step": "create", ...}              → 建对象
- POST /auto-config  body: {"step": "run"}                      → 自动监测
- POST /auto-config  body: {"step": "distill"}                  → 蒸馏闭环

诚实原则：Kernel 无企业资料 → 空候选 + 提示上传，不编造；竞品 LLM 输出失败 → 提示手填。
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok, err

logger = logging.getLogger("eios.geo.onboard")

router = APIRouter(prefix="/api/v1/onboard")


# ── 入参 ───────────────────────────────────────────────
class AutoConfigIn(BaseModel):
    step: str  # detect / discover / create / run / distill
    company: str | None = None
    aliases: list[str] = []
    products: list[str] = []
    services: list[str] = []
    industry: str | None = None
    competitors: list[dict] = []  # [{name, company}]
    keywords: list[str] = []  # 行业搜索词（detect 挖出）→ 建 keyword 对象扩大监测面
    monitor_ids: list[str] = []  # 本次 create 返回的对象 id（run 只跑这些）


# ── 内部复用（monitor / distill 现成函数） ───────────────
def _load_items():
    from app.services.store import get_store

    return get_store().load("monitor_items")


def _save_items(items):
    from app.services.store import get_store

    get_store().save("monitor_items", items)


def _new_monitor_id() -> str:
    return f"mi_{uuid.uuid4().hex[:10]}"


def _item_company(it) -> str:
    cfg = it.get("config_json") or {}
    return cfg.get("company") or cfg.get("target") or it.get("entity") or ""


def _extract_json_array(text: str) -> list:
    m = json.loads(text) if text.strip().startswith("[") else None
    if isinstance(m, list):
        return m
    import re

    m = re.search(r"\[[\s\S]*\]", text or "")
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass
    return []


# ── step 1：知识库检测（实体提取 + LLM 语义分类） ───────────
def _ent_name(e) -> str:
    return str(e.get("canonical_name") or e.get("name") or "").strip()


def _ent_evidence_count(e) -> int:
    ev = e.get("evidence_ids")
    return len(ev) if isinstance(ev, list) else 0


async def _step_detect():
    """Kernel 实体 → 按 object_type 分组 → LLM 语义分类（产品/服务/公司/行业/搜索词）

    2026-08-11 改造（用户实测：自家公司识别不出、行业不对）：
    旧实现把 549 个实体按创建时间截前 120 个让 LLM 猜——真正的公司实体
    （object_type='company'，如「亚宇臻隆科技」引用 65 次）排在 300+ 位被截掉，
    前 120 全是职位/外部工具/文件名噪声 → company 空、industry null。
    新实现：
    1. 直接用 Kernel 的 object_type 分类：company 类作公司候选，person/department/
       project/policy 噪声类剔除；
    2. 公司候选带引用频次（被文档引用最多 = 企业主体）；
    3. 产品/服务候选 = material/procedure/supplier 等业务类高频实体；
    4. LLM 顺带挖行业搜索词（keywords）→ create 时建 keyword 对象扩大监测面。
    兜底：LLM 失败 → company=公司类频次最高，products=业务类高频特征词。
    """
    from adapters.eios import get_entities

    entities = []
    try:
        entities = await get_entities() or []
    except Exception as e:  # noqa: BLE001
        logger.warning("get_entities failed: %s", e)

    if not entities:
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "hint": "知识库暂无企业资料——请先在知识库上传产品说明/公司介绍后重试",
        }

    # ① 按 Kernel 分类分组（entity 对象自带 object_type；None 归入业务候选）
    company_ents = [e for e in entities if e.get("object_type") == "company"]
    noise_kinds = {"person", "department", "project", "policy"}
    biz_ents = [
        e for e in entities
        if e.get("object_type") not in noise_kinds and e.get("object_type") != "company"
    ]
    # 排序：引用频次降序（自家公司/核心产品被文档引用最多）
    company_ents.sort(key=_ent_evidence_count, reverse=True)
    biz_ents.sort(key=_ent_evidence_count, reverse=True)

    # ② 候选清单（不再无脑截前 120：公司类全保留，业务类按频次取前 100）
    company_cands = [_ent_name(e) for e in company_ents if _ent_name(e)][:30]
    biz_names: list[str] = []
    seen = set()
    for e in biz_ents:
        n = _ent_name(e)
        if n and n not in seen and len(n) <= 30:
            seen.add(n)
            biz_names.append(n)
        if len(biz_names) >= 100:
            break

    # ②.5 优先用 Kernel 的 object_type 分类（2026-08-21 用户拍板：LLM 猜 products/company 不可靠）
    #     公司=object_type company；产品=object_type product；服务=object_type service（排除 deprecated）。
    #     LLM 只负责补 industry/keywords（见 ④ 补全调用），不再让它重猜实体分类。
    def _kind_names(kind: str) -> list[str]:
        out: list[str] = []
        for e in entities:
            if e.get("object_type") == kind and e.get("status") != "deprecated":
                n = _ent_name(e)
                if n and n not in out:
                    out.append(n)
        return out

    result = {
        "company": _kind_names("company"),
        "products": _kind_names("product"),
        "services": _kind_names("service"),
        "industry": None,
        "keywords": [],
    }

    # 去重 + 跨类互斥 + 自家清洗
    def _dedup(lst):
        out, seen = [], set()
        for x in lst:
            x = str(x).strip()
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    prods = _dedup(result["products"])
    svcs = _dedup(result["services"])
    prods = [p for p in prods if p not in svcs]
    svcs = [s for s in svcs if s not in prods]
    company = _dedup(result["company"])
    kws = _dedup(result["keywords"])

    # ④ 补全调用：LLM 第一次分类常漏 industry/keywords（实测两次全漏）——
    # 基于已确认的公司/产品/服务再聚焦问一次（比从 549 个噪声里猜准得多）
    if (not result["industry"] or not kws) and (company or prods or svcs):
        try:
            from adapters.llm import chat

            parts = []
            if company:
                parts.append(f"公司：{'、'.join(company[:3])}")
            if prods:
                parts.append(f"产品：{'、'.join(prods[:8])}")
            if svcs:
                parts.append(f"服务：{'、'.join(svcs[:5])}")
            focus = "；".join(parts)
            text = await chat(
                f"以下是一家企业的信息：{focus}\n"
                "请回答：\n"
                "- industry：所属行业（一句话，如「AI数字员工与自媒体获客服务」）\n"
                "- keywords：普通用户找这类服务时会搜索的行业词/痛点词/场景词 6-10 个"
                "（如「AI数字员工」「自媒体代运营」「AI获客」；不要公司名、不要品牌名）\n"
                '严格 JSON 输出：{"industry": "...", "keywords": ["..."]}',
                max_tokens=400,
            )
            m = json.loads(text) if text.strip().startswith("{") else None
            if m:
                if not result["industry"]:
                    result["industry"] = str(m.get("industry") or "").strip() or None
                if not kws:
                    kws = _dedup([str(x).strip() for x in (m.get("keywords") or []) if str(x).strip()])[:10]
        except Exception as e:  # noqa: BLE001
            logger.warning("industry/keywords fill failed: %s", e)

    # ⑤ 最后兜底：industry 仍空 → 从产品/服务名拆行业线索词；keywords 仍空 → industry 顶上
    if not result["industry"]:
        for n in [*prods, *svcs]:
            if "Agent" in n or "AI" in n:
                result["industry"] = "AI数字员工服务"
                break
            if "自媒体" in n or "矩阵" in n or "获客" in n:
                result["industry"] = "自媒体获客服务"
                break
    if not kws and result["industry"]:
        kws = [result["industry"]]
    # keywords 不与公司/产品重名
    own_all = set(company) | set(prods) | set(svcs)
    kws = [k for k in kws if k not in own_all and not any(o and (o in k or k in o) for o in company if len(o) >= 3)][:10]

    return {
        "company": company,
        "aliases": company[1:],
        "products": prods[:10],
        "services": svcs[:8],
        "industry": result["industry"],
        "keywords": kws,
        "empty": not company and not prods and not svcs and not result["industry"],
        "hint": None,
    }


# ── step 2：竞品发现 ────────────────────────────────────
def _is_own(name: str, own_names: list[str]) -> bool:
    """自家实体判定：同名，或互为子串（≥3 字防误杀），如「云启视界」vs「云启视界·AI工业质检平台」"""
    n = (name or "").strip()
    if not n:
        return True
    for o in own_names:
        o = (o or "").strip()
        if not o:
            continue
        if n == o:
            return True
        if len(o) >= 3 and len(n) >= 3 and (o in n or n in o):
            return True
    return False


# ── 竞品发现：按所在地对标（问豆包，一次回答里的所有品牌） ─────────
_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "重庆", "武汉", "西安", "苏州", "天津", "南京",
    "郑州", "长沙", "东莞", "青岛", "沈阳", "宁波", "昆明", "大连", "厦门", "合肥", "佛山", "福州",
    "哈尔滨", "济南", "无锡", "长春", "温州", "石家庄", "南宁", "常州", "泉州", "南昌", "贵阳", "太原",
    "烟台", "嘉兴", "南通", "金华", "珠海", "惠州", "徐州", "海口", "乌鲁木齐", "绍兴", "中山", "台州",
    "兰州", "潍坊", "保定", "镇江", "扬州", "桂林", "唐山", "三亚", "湖州", "汕头", "新乡", "廊坊",
    "呼和浩特", "赣州", "盐城", "泰州", "洛阳", "宜昌", "襄阳", "绵阳", "泸州", "遵义", "佛山",
]


def _extract_city(company: str) -> str:
    """从公司名提取城市（成都笔革设计公司 → 成都）；提取不到返回空（用「本地」）"""
    for c in _CITIES:
        if c in (company or ""):
            return c
    return ""


async def _chat_doubao(prompt: str, max_tokens: int = 800) -> str:
    """豆包引擎对话（OpenAI 兼容：ark.cn-beijing.volces.com）"""
    import httpx

    from app.core.config import ENGINES, engine_api_key

    doubao = next((e for e in ENGINES if e["id"] == "doubao"), None)
    key = engine_api_key("doubao") if doubao else None
    if not doubao or not key:
        return ""
    try:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            resp = await client.post(
                doubao["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": doubao["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
            )
        if resp.status_code != 200:
            logger.warning("doubao http %s: %s", resp.status_code, resp.text[:150])
            return ""
        data = resp.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("doubao call failed: %s", e)
        return ""


def _extract_brands(content: str) -> list[str]:
    """从豆包一次回答里提取所有品牌/公司名：按行/编号/顿号拆分，过滤噪声词"""
    out: list[str] = []
    for line in content.splitlines():
        name = line.strip().lstrip("0123456789.、)）·-— \t")
        name = name.split("：")[-1].strip()
        if not name or len(name) > 24:
            continue
        if any(t in name for t in ("公司", "品牌", "比如", "例如", "介绍", "以上", "回答", "包括", "主要", "还有", "相关", "可以", "以下", "这类")):
            continue
        out.append(name)
    return out


async def _step_discover(products: list[str], own_names: list[str] | None = None, company: str = "", industry: str = ""):
    """竞品发现（按所在地对标）：基于公司/产品/行业构造本地问题问豆包，
    豆包一次回答里提到的所有品牌记下来 = 竞品。
    豆包失败（无 key/异常/空结果）→ 回退原逻辑（通用产品对标）。
    """
    from adapters.llm import chat

    own_names = [o for o in (own_names or []) if o]
    own_text = "、".join(own_names[:12]) if own_names else "（无）"
    results: dict[str, dict] = {}  # name → {name, company}

    # ① 主路径：问豆包（按所在地对标）
    city = _extract_city(company)
    city_text = f"{city}" if city else "本地"
    q_text = (
        f"我们是{company or '一家公司'}，主要产品/服务：{'、'.join(products[:3])}，"
        f"属于{industry or '相关'}行业。\n"
        f"请问{city_text}的{industry or '相关'}行业里，有哪些公司/品牌在做类似产品或服务？\n"
        "请把你了解到的所有相关公司/品牌一次列全，每个都带所属公司。\n"
        f"注意：以下名称属于我们自己，绝对不能列出来：{own_text}\n"
        "只列中国企业和中国品牌（如字节跳动、腾讯、阿里、华为、百度等），绝对不要国外品牌（OpenAI/Google/Microsoft/Salesforce 等）。\n"
        '严格 JSON 数组输出：[{"name": "竞品品牌名", "company": "所属公司名"}]'
    )
    doubao_text = await _chat_doubao(q_text)
    if doubao_text:
        # 2026-08-19：优先 JSON 解析（带 company）；失败退回文本品牌提取（company 空）
        parsed = _extract_json_array(doubao_text)
        if parsed:
            for it in parsed:
                name = str(it.get("name") or "").strip()
                if name and name not in results and not _is_own(name, own_names):
                    results[name] = {"name": name, "company": str(it.get("company") or "").strip()}
        else:
            for name in _extract_brands(doubao_text):
                if name and name not in results and not _is_own(name, own_names):
                    results[name] = {"name": name, "company": ""}
        logger.info("discover(doubao) brands: %s", list(results.keys())[:10])

    # ② 回退：豆包没结果 → 原通用逻辑（产品 → chat）
    if not results:
        for p in products[:5]:
            try:
                text = await chat(
                    f"当前市面上「{p}」的主要产品/平台有哪些？列出 5-8 个，每个带所属公司。\n"
                    f"注意：以下名称属于本公司或本公司产品，绝对不能输出它们：{own_text}\n"
                    "只列外部竞争对手的产品/平台。\n"
                    "只列中国企业和中国品牌（如字节跳动、腾讯、阿里、华为、百度等），"
                    "绝对不要国外品牌（如 OpenAI、Google、Microsoft、Salesforce 等）。\n"
                    '严格 JSON 数组输出：[{"name": "飞书", "company": "字节跳动"}]',
                    max_tokens=600,
                )
                for it in _extract_json_array(text):
                    name = str(it.get("name") or "").strip()
                    if name and name not in results and not _is_own(name, own_names):
                        results[name] = {"name": name, "company": str(it.get("company") or "").strip()}
            except Exception as e:  # noqa: BLE001
                logger.warning("discover failed for %s: %s", p, e)
    items = list(results.values())[:10]
    return {
        "competitors": items,
        "empty": not items,
        "hint": None if items else "大模型未返回竞品清单——请手动在监测中心添加竞品对象",
        "city": city,
        "question": q_text if not items else None,
    }


# ── step 3：自动建对象 ──────────────────────────────────
async def _step_create(cfg: AutoConfigIn):
    """确认后建对象：brand / product×N / keyword / competitor×N（config 全自动）"""
    from app.api.v1.monitor import generate_queries

    items = _load_items()
    created = []
    now = datetime.now(timezone.utc).isoformat()

    def _mk(type_: str, config: dict, entity: str):
        item = {
            "monitor_id": _new_monitor_id(),
            "type": type_,
            "config_json": config,
            "entity": entity,
            "query_count": len(generate_queries({"type": type_, "config_json": config, "entity": entity})),
            "status": "active",
            "created_time": now,
            "updated_time": now,
        }
        items.append(item)
        created.append(item)
        return item

    aliases = [a for a in (cfg.aliases or []) if a]
    products = [p for p in (cfg.products or []) if p]
    services = [s for s in (cfg.services or []) if s]
    if cfg.company:
        _mk("brand", {"company": cfg.company, "aliases": aliases, "product": products, "industry": cfg.industry, "tier": "lite"}, cfg.company)
    for p in products:
        _mk("product", {"product": p, "company": cfg.company, "competitor": []}, p)
    if cfg.industry:
        _mk("keyword", {"keyword": cfg.industry, "extras": products}, cfg.industry)
    # 行业搜索词（detect 挖出）→ 每个建 keyword 对象：监测面从「1 个行业词」扩到「N 个用户真实搜索词」
    seen_kw: set[str] = set()
    for kw in (cfg.keywords or []):
        kw = str(kw).strip()
        if kw and kw != cfg.industry and kw not in seen_kw:
            seen_kw.add(kw)
            _mk("keyword", {"keyword": kw, "extras": products}, kw)
    for c in (cfg.competitors or []):
        name = str(c.get("name") or "").strip()
        if name:
            _mk("competitor", {"company": cfg.company, "target": cfg.company, "competitor": [name], "product": products, "industry": cfg.industry}, f"{cfg.company} vs {name}")
    _save_items(items)
    return {"created": created, "count": len(created)}


# ── step 4：自动监测（后台任务 + 进度轮询，不卡请求） ──────
import asyncio

_RUN_BY_TENANT: dict[str, dict] = {}


def _empty_run_progress() -> dict:
    return {"running": False, "phase": None, "done": 0, "total": 0, "error": None, "summary": None, "distill": None, "started_at": None}


def _progress() -> dict:
    """入驻/监测进度按 GEO 柜分槽，两部门同时配置互不覆盖。"""
    from app.services.store import current_tenant

    tid = current_tenant()
    slot = _RUN_BY_TENANT.get(tid)
    if slot is None:
        slot = _empty_run_progress()
        _RUN_BY_TENANT[tid] = slot
    return slot


async def _step_run(monitor_ids: list[str] | None = None, products: list[str] | None = None, industry: str | None = None, company: str | None = None):
    """启动后台监测任务，立即返回（进度由 GET /onboard/run-status 轮询）

    monitor_ids 为空 → 跑全部 active；传本次新建的 id → 只跑新建对象（自动配置场景）
    run 完成后后台自动接蒸馏闭环（问题生成→缺口→内容机会），页面关闭不中断。
    """
    all_items = _load_items()
    if monitor_ids:
        items = [i for i in all_items if i.get("monitor_id") in monitor_ids and i.get("status") == "active"]
    else:
        items = [i for i in all_items if i.get("status") == "active"]
    if not items:
        return {"started": False, "error": "没有可运行的监测对象（未建对象或全部归档）"}
    if _progress()["running"]:
        return {"started": False, "error": "已有监测任务在运行中，请等待完成"}

    from app.services.store import current_tenant, set_tenant
    tid = current_tenant()

    async def _worker():
        from app.api.v1.monitor import run_batch_items
        from app.api.v1 import distill as D

        set_tenant(tid)
        p = _progress()

        def _cb(done, total):
            p["done"] = done
            p["total"] = total

        p.update({"running": True, "phase": "run", "done": 0, "total": 0, "error": None, "summary": None, "distill": None, "started_at": datetime.now(timezone.utc).isoformat()})
        try:
            _progress()["summary"] = await run_batch_items(items, company_name=company or "", engines=None, progress_cb=_cb)
        except Exception as e:  # noqa: BLE001
            logger.exception("onboard run failed")
            _progress()["error"] = str(e)[:300]
            _progress()["running"] = False
            _progress()["phase"] = "done"
            return

        # 等解析排空（用户要求：跑完监测 → 先解析 AI 回复 → 再出内容机会）。
        # 解析是 asyncio 后台队列（每条 evidence 一次 LLM 调用），必须等它跑完，
        # 否则内容机会/缺口基于未解析数据生成 → 驴唇不对马嘴。
        # 进度实时写回 _progress()（前端 2s 轮询展示「解析中 N/M 条」）
        _progress()["phase"] = "parse"
        try:
            from services.intelligence import queue as Q

            while True:
                snap = await Q.snapshot()
                _progress()["parse"] = snap
                _progress()["done"] = snap["succeeded"] + snap["failed"]
                # total 含队列里未入库的（本次抓取的新回答）：否则显示 243/244 假象
                _progress()["total"] = max(snap["total"] + snap["queue_size"], 1)
                if snap["queue_size"] == 0 and snap["running"] == 0:
                    break
                await asyncio.sleep(2.0)
        except Exception as e:  # noqa: BLE001
            logger.exception("onboard wait parse failed")
            _progress()["parse"] = {"drained": False, "error": str(e)[:200]}

        # run + 解析完成 → 自动接蒸馏闭环（问题生成 → 缺口 → 内容机会），不依赖前端触发
        _progress()["phase"] = "distill"
        try:
            seeds = [s for s in (products or []) if s] + ([industry] if industry else [])
            distill = {"questions": None, "gaps": None, "opportunities": None, "error": None}
            distill_steps = [s for s in [("questions", bool(seeds)), ("gaps", True), ("opportunities", True)] if s[1]]
            for i, (key, _flag) in enumerate(distill_steps):
                _progress()["done"] = i
                _progress()["total"] = len(distill_steps)
                if key == "questions":
                    qr = await D.gen_questions(D.QuestionsIn(seed_keywords=seeds, count=10))
                    distill["questions"] = qr.get("data") or qr
                elif key == "gaps":
                    gr = await D.detect_gaps(limit=30)
                    distill["gaps"] = gr.get("data") or gr
                elif key == "opportunities":
                    orr = await D.gen_opportunities(limit=15)
                    distill["opportunities"] = orr.get("data") or orr
            _progress()["done"] = len(distill_steps)
            _progress()["distill"] = distill
        except Exception as e:  # noqa: BLE001
            logger.exception("onboard distill failed")
            _progress()["distill"] = {"questions": None, "gaps": None, "opportunities": None, "error": str(e)[:300]}
        finally:
            _progress()["running"] = False
            _progress()["phase"] = "done"

    asyncio.get_running_loop().create_task(_worker())
    # 探针总数预估（与 run_batch_items 内部一致）
    from app.api.v1.monitor import generate_queries

    total = sum(len(generate_queries(it, {"company_name": ""})) for it in items)
    return {"started": True, "total_queries": total, "items": len(items)}


def _overall_pct(p: dict) -> int:
    """加权总进度：抓取 run 0-60% / 解析 parse 60-90% / 蒸馏 distill 90-100%。"""
    phase = p.get("phase")
    if phase == "done":
        return 100
    if phase == "run":
        total = p.get("total") or 0
        done = p.get("done") or 0
        return min(60, round(done / total * 60)) if total else 5
    if phase == "parse":
        snap = p.get("parse") or {}
        ptotal = snap.get("total") or 0
        pdone = (snap.get("succeeded") or 0) + (snap.get("failed") or 0)
        return min(90, 60 + (round(pdone / ptotal * 30) if ptotal else 5))
    if phase == "distill":
        total = p.get("total") or 1
        done = p.get("done") or 0
        return min(100, 90 + round(done / total * 10))
    return 5  # 刚启动


@router.get("/run-status")
async def onboard_run_status():
    """后台监测+蒸馏进度（前端轮询；finished 后带 distill 结果 + intelligence 统计）"""
    p = _progress()
    # intelligence 统计（动态查库：监测回答经钩子自动解析，进度与 worker 状态无关）
    intel = {"evidence": 0, "succeeded": 0, "failed": 0, "pending": 0, "mentions": 0}
    try:
        from sqlalchemy import func
        from app.models.geo_models import BrandMention, GeoEvidence, GeoExtraction, SessionLocal, init_db

        init_db()
        with SessionLocal() as db:
            from app.services.store import current_tenant

            tid = current_tenant()
            ids = [x[0] for x in db.query(GeoEvidence.id).filter(GeoEvidence.tenant_id == tid).all()]
            if not ids:
                intel = {"evidence": 0, "succeeded": 0, "failed": 0, "pending": 0, "mentions": 0}
            else:
                intel = {
                    "evidence": len(ids),
                    "succeeded": db.query(func.count(GeoExtraction.id)).filter(
                        GeoExtraction.status == "succeeded", GeoExtraction.evidence_id.in_(ids)
                    ).scalar() or 0,
                    "failed": db.query(func.count(GeoExtraction.id)).filter(
                        GeoExtraction.status == "failed", GeoExtraction.evidence_id.in_(ids)
                    ).scalar() or 0,
                    "pending": db.query(func.count(GeoExtraction.id)).filter(
                        GeoExtraction.status == "running", GeoExtraction.evidence_id.in_(ids)
                    ).scalar() or 0,
                    "mentions": db.query(func.count(BrandMention.id)).filter(BrandMention.evidence_id.in_(ids)).scalar() or 0,
                }
    except Exception:  # noqa: BLE001
        pass
    return ok({
        "running": p["running"],
        "phase": p["phase"],  # run / parse / distill / done
        "done": p["done"],
        "total": p["total"],
        "error": p["error"],
        "started_at": p["started_at"],
        "finished": p["phase"] == "done" and p["summary"] is not None,
        "summary": p["summary"],
        "distill": p["distill"],  # run 完成后自动生成（问题/缺口/机会）
        "parse": p.get("parse"),  # 解析队列快照（succeeded/failed/total/queue_size）
        "intelligence": intel,  # 认知分析自动解析进度（全智解析数据源）
        # 加权总进度：抓取 0-60% / 解析 60-90% / 蒸馏 90-100%（前端进度条直接用它）
        "overall_pct": _overall_pct(p),
    })


# ── step 5：蒸馏闭环（后台任务——问题生成→缺口→计划，页面关闭不中断） ──
async def _step_distill(cfg: AutoConfigIn):
    if _progress()["running"]:
        return {"started": False, "error": "已有任务在运行中，请等待完成"}
    products = [s for s in (cfg.products or []) if s]
    industry = cfg.industry

    from app.services.store import current_tenant, set_tenant
    tid = current_tenant()

    async def _worker():
        from app.api.v1 import distill as D

        set_tenant(tid)
        _progress().update({"running": True, "phase": "distill", "done": 0, "total": 0, "error": None, "summary": None, "distill": None, "started_at": datetime.now(timezone.utc).isoformat()})
        try:
            # 先等解析排空（若监测刚跑完解析还在后台），再蒸馏——机会基于完整解析数据
            try:
                from services.intelligence import queue as Q

                _progress()["parse"] = await Q.wait_drained(timeout=600)
            except Exception as e:  # noqa: BLE001
                logger.warning("distill wait parse failed: %s", e)
            # 种子：显式传入优先 → 监测对象（product/keyword/brand 即种子来源）→ detect 兜底
            seeds = [s for s in products if s] + ([industry] if industry else [])
            if not seeds:
                seen = set()
                for it in _load_items():
                    cfg = it.get("config_json") or {}
                    t = it.get("type")
                    cand = None
                    if t == "product":
                        cand = cfg.get("product")
                    elif t == "keyword":
                        cand = cfg.get("keyword")
                    elif t == "brand":
                        cand = cfg.get("company")
                    if cand and str(cand).strip() and str(cand).strip() not in seen:
                        seen.add(str(cand).strip())
                        seeds.append(str(cand).strip())
                    if len(seeds) >= 10:
                        break
            if not seeds:
                try:
                    det = await _step_detect()
                    seeds = [s for s in (det.get("products") or []) if s] + ([det.get("industry")] if det.get("industry") else [])
                except Exception:  # noqa: BLE001
                    seeds = []
            distill = {"questions": None, "gaps": None, "opportunities": None, "error": None}
            # 无条件生成问题（gen_questions 内部兜底：种子空则 _auto_keywords）
            qr = await D.gen_questions(D.QuestionsIn(seed_keywords=seeds, count=10))
            distill["questions"] = qr.get("data") or qr
            gr = await D.detect_gaps(limit=30)
            distill["gaps"] = gr.get("data") or gr
            orr = await D.gen_opportunities(limit=15)
            distill["opportunities"] = orr.get("data") or orr
            _progress()["distill"] = distill
        except Exception as e:  # noqa: BLE001
            logger.exception("onboard distill failed")
            _progress()["distill"] = {"questions": None, "gaps": None, "opportunities": None, "error": str(e)[:300]}
        finally:
            _progress()["running"] = False
            _progress()["phase"] = "done"

    asyncio.get_running_loop().create_task(_worker())
    return {"started": True, "phase": "distill"}


# ── 路由 ────────────────────────────────────────────────
@router.get("/status")
async def onboard_status():
    """空态检测：items + questions 全空 → 显示「自动配置」按钮"""
    items = _load_items()
    from app.services.store import get_store

    questions = get_store().load("questions")
    empty = len(items) == 0 and len(questions) == 0
    return ok({"empty": empty, "items": len(items), "questions": len(questions)})


@router.post("/auto-config")
async def auto_config(payload: AutoConfigIn):
    step = (payload.step or "").strip()
    try:
        if step == "detect":
            return ok(await _step_detect())
        if step == "discover":
            return ok(
                await _step_discover(
                    [p for p in (payload.products or []) if p],
                    own_names=[payload.company, *payload.aliases, *payload.products, *payload.services],
                    company=payload.company or "",
                    industry=payload.industry or "",
                )
            )
        if step == "create":
            return ok(await _step_create(payload))
        if step == "run":
            return ok(await _step_run([str(x) for x in (payload.monitor_ids or [])] or None, payload.products, payload.industry, payload.company))
        if step == "distill":
            return ok(await _step_distill(payload))
        return err("invalid_input", f"step 必须是 detect/discover/create/run/distill，当前: {step}")
    except Exception as e:  # noqa: BLE001
        logger.exception("auto-config %s failed", step)
        return err("onboard_error", f"自动配置步骤 {step} 失败：{str(e)[:200]}")
