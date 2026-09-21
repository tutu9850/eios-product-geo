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
    """企业知识库 → 候选名单 → LLM 归类（公司/产品/服务/行业/搜索词）

    2026-09-20 改造（知识源从老 Kernel 换成 EIOS 知识库）：EIOS 的知识对象只有
    ``entity`` / ``fact`` 两种 type，公司/产品/服务那套分类在 Semantic 不在 Knowledge。
    所以「按 object_type 分组」这条老路在 EIOS 上恒为空 —— 之前的实现就是这么静默
    变成「知识库暂无企业资料」的。现在：
    1. 取企业知识对象（只读，含被引用频次）+ 企业文档标题；
    2. 候选池 = 出现在文档标题里 / 带公司后缀的 → 公司候选，带产品服务特征词的 → 业务候选；
    3. LLM 只做「从候选池里挑」，选不出就留空（不允许编造名单外的名字）；
    4. LLM 顺带补 industry / keywords（见 ④）。
    兜底：LLM 不可用 → company=公司候选前几名，products=业务候选前几名；
    知识库确实没有资料 → 空候选 + 提示上传，不编造。
    """
    from adapters.eios import get_entities

    entities = []
    try:
        entities = await get_entities() or []
    except Exception as e:  # noqa: BLE001
        # 读不到 ≠ 知识库是空的。以前这里把两者混成同一句「知识库暂无企业资料」，
        # 于是适配层拨空号 / 票签不出来 / 知识库 503 全被显示成「请去上传资料」。
        logger.warning("get_entities failed: %s", e)
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "error": str(e)[:300],
            "hint": f"企业知识库读不到（这不等于知识库是空的）：{str(e)[:200]}",
        }

    if not entities:
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "error": None,
            "hint": "知识库暂无企业资料——请先在知识库上传产品说明/公司介绍后重试",
        }

    # ① 候选池：EIOS 的知识对象只有 entity / fact 两种 type —— 公司/产品/服务那套分类在
    #    Semantic，不在 Knowledge。所以这里不再假装按 object_type 分类（老 Kernel 有
    #    company/product/service 字段，那条路在 EIOS 不存在），改成：
    #    名称规则 + 被文档引用频次 → 候选池 → 交给 LLM 归类（见 ②）。
    _COMPANY_SUFFIX = ("公司", "科技", "集团", "工作室", "有限", "研究院", "事务所", "厂", "店")
    _BIZ_MARK = ("版", "Agent", "OS", "系统", "平台", "终端", "服务", "套餐", "方案", "课程", "产品")

    entities = [e for e in entities if e.get("status") != "deprecated"]
    entities.sort(key=_ent_evidence_count, reverse=True)

    doc_titles: list[str] = []
    try:
        from adapters.eios import list_documents

        doc_titles = [str(d.get("title") or "") for d in (await list_documents(limit=50) or [])]
    except Exception as e:  # noqa: BLE001 — 拿不到文档标题只是少一条公司判据
        logger.warning("list_documents failed: %s", e)

    def _appears_in_doc_title(name: str) -> bool:
        # 至少 3 个字：「项目」「回款」「部门」这类通用两字词也出现在文档标题里
        # （「14_项目信息表」），但它们不是公司名。
        return bool(name) and len(name) >= 3 and any(name in t for t in doc_titles)

    company_cands: list[str] = []
    biz_names: list[str] = []
    seen: set[str] = set()
    for e in entities:
        # fact 对象是「成都演示间 负责 StoryClaw终端」这种整句陈述，不是名称：
        # 放进候选名单会把句子当产品名显示出来（原来就这么显示的）。
        if e.get("object_type") == "fact":
            continue
        n = _ent_name(e)
        if not n or n in seen or len(n) > 30:
            continue
        seen.add(n)
        # 出现在文档标题里（「08_薪酬制度_亚宇臻隆2026」）或带公司后缀 → 公司候选。
        # 前者是这套数据里最强的自家公司信号：文档都是这家企业自己的。
        if _appears_in_doc_title(n) or n.endswith(_COMPANY_SUFFIX):
            if len(company_cands) < 30:
                company_cands.append(n)
            continue
        if any(m in n for m in _BIZ_MARK) or _ent_evidence_count(e) >= 2:
            if len(biz_names) < 100:
                biz_names.append(n)

    # ② 让 LLM 只做「在给定候选里挑」这一件事 —— EIOS 不给分类，猜必须有边界：
    #    prompt 里写明只能从名单里选，选不出就留空。失败就退回候选池本身（见下）。
    result: dict = {
        "company": company_cands[:10],
        "products": [],
        "services": [],
        "industry": None,
        "keywords": [],
        # 分类是 LLM 挑的还是名称规则兜底的，如实报出来（LLM 未配置时 industry/keywords
        # 只能是特征词兜底，页面上的数字要能看出这一点）。
        "classification_source": "heuristic",
    }
    pool = company_cands[:20] + biz_names[:60]
    if pool:
        try:
            from adapters.llm import chat

            text = await chat(
                "以下是从这家企业的知识库里抽出来的候选名称（按被文档引用次数排序，"
                "引用越多越可能是企业主体或核心业务）：\n"
                f"公司候选：{'、'.join(company_cands[:20]) or '（无）'}\n"
                f"业务候选：{'、'.join(biz_names[:60]) or '（无）'}\n\n"
                "请判断并**只从上面的名单里选**（选不出就留空数组，不要编造新名字，不要选客户/竞品）：\n"
                "- company：这家企业自己的公司名\n"
                "- products：产品/软件/版本名（如「企业版Agent OS」「GEO+知识库版」）\n"
                "- services：服务/课程类名\n"
                '严格 JSON 输出：{"company": [...], "products": [...], "services": [...]}',
                max_tokens=600,
            )
            blob = text.strip()
            if not blob.startswith("{"):
                import re as _re

                m = _re.search(r"\{[\s\S]*\}", blob)
                blob = m.group(0) if m else ""
            picked = json.loads(blob) if blob else {}
            allowed = set(pool)
            for key in ("company", "products", "services"):
                vals = [
                    str(x).strip()
                    for x in (picked.get(key) or [])
                    if str(x).strip() in allowed
                ]
                if vals:
                    result[key] = vals if key != "company" else vals[:5]
                    result["classification_source"] = "llm"
        except Exception as e:  # noqa: BLE001 — LLM 只是归类器，失败不阻塞检测
            logger.warning("detect classify failed: %s", e)
    # LLM 没给出产品时的兜底：业务候选里带产品/服务特征词的先上（候选池本身已经筛过）
    if not result["products"]:
        result["products"] = biz_names[:10]


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
        "error": None,
        "classification_source": result.get("classification_source"),
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


async def _ask_deployment_model(prompt: str, max_tokens: int = 800) -> str:
    """竞品发现要一次「问 AI」：走部署的统一模型入口。

    以前这里是 GEO 自己拿豆包的 key 直连 —— Owner 2026-09-21：「GEO 不保留 Builder /
    .env / 自己的模型 Key」「Model Capability 必须成为所有产品统一调用模型的唯一正规入口」。
    所以凭据、base_url、model、温度全部归部署；GEO 只说「我要一段文本」。

    失败（部署没模型 / 权威侧拒绝）一律返回空串，调用方回退到通用对标逻辑 —— 与改造前
    豆包失败时的行为一致。
    """
    from adapters.llm import LLMError, LLMNotConfiguredError, chat

    try:
        return (await chat(prompt, max_tokens=max_tokens)).strip()
    except (LLMNotConfiguredError, LLMError) as exc:
        logger.warning("竞品发现问模型失败（回退通用对标）：%s", str(exc)[:150])
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
    doubao_text = await _ask_deployment_model(q_text)
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
    """空态检测 + 三种「素材」各有多少（2026-09-20 修正标签错位）。

    历史上这个接口只回 items/questions，前端就把 items（监测对象）当「知识素材」显示 ——
    于是「企业资料 已就绪 / 知识素材 7 个」说的是监测对象，跟企业资料没关系。
    现在分开如实报：

    - ``items``        监测对象数（GEO 监测谁）
    - ``questions``    客户问题池
    - ``materials``    GEO 自己的素材库（geo_kb）
    - ``knowledge``    企业知识库读到的快照概况（``app.services.knowledge_snapshot``）。
      读本地快照表，不去打知识库；``read_ever=false`` 就是「还没读过知识库」，
      不是「知识库是空的」。
    """
    items = _load_items()
    from app.services import knowledge_snapshot
    from app.services.store import get_store

    store = get_store()
    questions = store.load("questions")
    materials = store.load("kb")
    empty = len(items) == 0 and len(questions) == 0
    return ok(
        {
            "empty": empty,
            "items": len(items),
            "questions": len(questions),
            "materials": len(materials),
            "knowledge": knowledge_snapshot.summary(),
        }
    )


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
