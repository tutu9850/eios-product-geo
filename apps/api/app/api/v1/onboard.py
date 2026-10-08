"""GEO 自动配置（Auto-Configure）——首次使用引导编排

流程（用户拍板）：空态触发 → 知识库检测 → 勾选确认 → 竞品发现 → 自动建对象
→ 自动监测（lite）→ 蒸馏闭环 → 内容选项卡生成（前端）。

设计：分步接口（前端引导组件逐步驱动，勾选确认在步骤间）：
- POST /auto-config  body: {"step": "detect"}                  → 实体候选（公司/产品/行业）
- POST /auto-config  body: {"step": "discover", "products": []} → 竞品候选
- POST /auto-config  body: {"step": "create", ...}              → 建对象
- POST /auto-config  body: {"step": "run"}                      → 自动监测
- POST /auto-config  body: {"step": "distill"}                  → 蒸馏闭环

诚实原则：企业知识库无企业资料 → 空候选 + 提示上传，不编造；竞品 LLM 输出失败 → 提示手填。
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
    city: str | None = None  # 所在地（Owner 2026-09-21：竞品发现按所在地问，不再靠抠公司名）
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
    """从模型回答里尽力取出 JSON 数组；**取不到就返回空，绝不抛异常**。

    模型输出被 max_tokens 截断是常态（实测：一条 45 行的数组在第 31 列断掉）。
    以前这里第一句 `json.loads(text)` 没兜底 —— 一次截断就会让整步失败。
    """
    import re

    raw = (text or "").strip()
    if raw.startswith("["):
        try:
            m = json.loads(raw)
            if isinstance(m, list):
                return m
        except Exception:  # noqa: BLE001 — 截断/夹杂说明文字都不该炸
            pass
    m = re.search(r"\[[\s\S]*\]", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass
    return []


def _salvage_pairs(text: str) -> list[dict]:
    """截断的 JSON 里逐条把 `"name": "...", "company": "..."` 抠出来。

    比逐行文本提取准得多：即使数组没闭合，前面完整的对象仍然可用。
    """
    import re

    out: list[dict] = []
    for chunk in re.finditer(r'\{[^{}]*\}', text or ""):
        blob = chunk.group(0)
        name = re.search(r'"name"\s*:\s*"([^"]+)"', blob)
        company = re.search(r'"company"\s*:\s*"([^"]+)"', blob)
        if name and name.group(1).strip():
            out.append({"name": name.group(1).strip(),
                        "company": company.group(1).strip() if company else ""})
    return out


# ── step 1：知识库检测（实体提取 + LLM 语义分类） ───────────
def _ent_name(e) -> str:
    return str(e.get("canonical_name") or e.get("name") or "").strip()


def _ent_evidence_count(e) -> int:
    ev = e.get("evidence_ids")
    return len(ev) if isinstance(ev, list) else 0


#: 公司名尾巴 / 业务特征词（候选池的粗筛规则，真正的归类交给 LLM，见 ``_classify_*``）
_COMPANY_SUFFIX = ("公司", "科技", "集团", "工作室", "有限", "研究院", "事务所", "厂", "店")
_BIZ_MARK = ("版", "Agent", "OS", "系统", "平台", "终端", "服务", "套餐", "方案", "课程", "产品")


def _dedup_list(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        x = str(raw).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _merge_pool(existing: list[str], pool: list[str]) -> list[str]:
    """把规则池并进已经勾出来的那一行，但不制造「打板服务 / 3D建模与打板服务」这种重复。

    规则池的取词有长度上限，会切短（``3D建模与打板服务`` → ``打板服务``），直接并进去
    页面上就会出现两条几乎一样的 chip。所以按包含关系收口：池子里更具体的名字替换掉被它
    包含的短名，短名则是已经有一条更具体的就跳过。
    """
    out = list(existing)
    for raw in pool or []:
        name = str(raw or "").strip()
        if not name:
            continue
        covered = [x for x in out if x and x != name and x in name]
        if covered:
            out = [x for x in out if x not in covered]
            out.append(name)
            continue
        if any(name in x for x in out if x):
            continue
        out.append(name)
    return out


async def _finalize_detect(
    result: dict, *, biz_fallback: list[str], service_fallback: list[str] | None = None
) -> dict:
    """LLM 挑完之后的收口：去重 / 跨类互斥 / industry + keywords 补全 / 最后兜底。

    知识库那一档和内容资产那一档**共用这一段** —— 换的只是候选池从哪来，
    归类口径与兜底顺序不许出现两套。
    """
    # ⓪ 尾巴定性（Owner 2026-09-22）：以「服务 / 课程」收尾的名字是**服务**，不是货。
    # 第一版把「服务」也当产品尾巴，「设计服务」就摆进了「产品」那一行 —— 页面上一眼错。
    # 这里不猜语义，只按尾巴挪行：模型把服务写进 products 也照样挪回去。
    from services.product_identity import is_service_name

    moved = [str(p) for p in (result.get("products") or []) if is_service_name(str(p))]
    result["products"] = [p for p in (result.get("products") or []) if not is_service_name(str(p))]
    # 兜底池也要按同一条尾巴规则分家：知识库那一档的池子（``biz_names``）里混着服务，
    # 直接当产品兜底就又把它塞回「产品」行了。
    pool_services = [*(service_fallback or []), *[p for p in biz_fallback if is_service_name(str(p))]]
    pool_products = [p for p in biz_fallback if not is_service_name(str(p))]
    result["services"] = _merge_pool(
        _dedup_list([*(result.get("services") or []), *moved]), pool_services
    )
    if not result["products"]:
        # LLM 没给出产品时的兜底：候选池里带产品特征词的先上（池子本身已经筛过）
        result["products"] = pool_products[:10]

    prods = _dedup_list(result["products"])
    svcs = _dedup_list(result["services"])
    prods = [p for p in prods if p not in svcs]
    svcs = [s for s in svcs if s not in prods]
    # 模板/提问词（如「哪个品牌」）不是企业主体。任何来源（规则、知识库或模型）
    # 都必须经过同一扇门，不能让一个占位词进入后续监测配置。
    from services.company_identity import is_placeholder_company_name

    company = _dedup_list(
        name for name in (result.get("company") or []) if not is_placeholder_company_name(name)
    )
    kws = _dedup_list(result["keywords"])

    # ④ 补全调用：LLM 第一次分类常漏 industry/keywords（实测两次全漏）——
    # 基于已确认的公司/产品/服务再聚焦问一次（比从几百个噪声里猜准得多）
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
                    kws = _dedup_list([str(x).strip() for x in (m.get("keywords") or []) if str(x).strip()])[:10]
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
    kws = [
        k
        for k in kws
        if k not in own_all and not any(o and (o in k or k in o) for o in company if len(o) >= 3)
    ][:10]

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


# ── step 1（档 A）：从 GEO 自己的内容资产自动配置 ────────────
async def _step_detect_from_materials():
    """内容资产（GEO 自己的素材库）→ 候选名单 → LLM 归类（Owner 2026-09-22）。

    Owner 原话：「自动配置这里，要从内容资产里面的文章去自动配置」。素材就是用户自己
    上传/新建的公司资料与文章，指向性强，所以：

    1. 公司候选：从素材标题与正文里按公司名特征**猜**（``services.company_identity``
       那套规则，比知识库那档放松 —— 见那边的注释）；
    2. 业务候选：把素材标题当材料交给 LLM 读，让它认出产品/服务/行业/关键词，
       **不把整条标题当产品名**喂回去；
    3. 一条素材都没有 → 空候选 + 提示先上传内容资产（或先做知识库同步），不编造；
    4. 全程不打知识库（GEO 运行时不许实时读知识库，Owner 2026-09-22）。
    """
    from app.services.store import get_store
    from services.company_identity import company_candidates_from_materials
    from services.product_identity import (
        looks_like_style_word,
        product_candidates_from_materials,
        service_candidates_from_materials,
    )

    try:
        materials = get_store().load("kb") or []
    except Exception as e:  # noqa: BLE001 — 读自己的库失败要如实报，不假装「还没有素材」
        logger.warning("detect(materials): load kb failed: %s", e)
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "error": str(e)[:300],
            "classification_source": None,
            "hint": f"读取 GEO 自己的内容资产失败：{str(e)[:200]}",
        }

    if not materials:
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "error": None,
            "classification_source": None,
            "hint": "还没有内容资产——先在「内容资产」上传公司资料/文章，或先做一次「知识库同步」，再来自动配置",
        }

    company_cands = company_candidates_from_materials(materials)
    # 规则先自己找一遍产品（纯规则，不调模型）—— 这是「能找到产品的算法」的确定性下限，
    # 也是给模型的参考池；模型给不出来的话产品那一行就用它，而不是拿素材标题凑。
    product_pool = product_candidates_from_materials(materials)
    # 服务同一套规则、同一份证据，只是按尾巴（「服务 / 课程」）归到另一行。
    service_pool = service_candidates_from_materials(materials)
    corpus = _material_corpus(materials)
    titles = [
        str(m.get("title") or "").strip()
        for m in materials
        if str(m.get("title") or "").strip()
    ][:30]
    result: dict = {
        "company": company_cands[:5],
        "products": [],
        "services": [],
        "industry": None,
        "keywords": [],
        "classification_source": "heuristic",
    }
    # 素材很小（没上传东西、或只有几条）时不必麻烦 LLM，规则给的候选已经够用。
    digest = _material_llm_digest(materials)
    if digest:
        try:
            from adapters.llm import chat

            text = await chat(
                "以下是一家企业自己上传的内容资产（标题 + 正文摘录，新上传的排前面）：\n"
                + digest
                + "\n\n请**读正文**判断这家企业自己是谁、在卖什么（只依据上面的材料，看不出来就留空，"
                "不要编造材料里没有的名字）：\n"
                "- company：这家企业自己的公司名 / 品牌名（材料里出现过才算）\n"
                "- products：正文里出现过的**具体产品 / 系列 / 版本名**（如「琥珀沙发」）。"
                "**绝对不要把材料标题当产品名** —— 标题是「这份材料叫什么」，不是企业在卖什么；"
                "**设计风格/调性词（「意式极简」「奶油风」「中古」「轻法式」）不是产品名**，归 keywords\n"
                + (
                    "\n规则从正文里挑出的候选（供参考，不限于此）："
                    + "、".join(product_pool[:20])
                    + "\n"
                    if product_pool
                    else ""
                )
                + (
                    "规则挑出的服务候选（供参考，不限于此）："
                    + "、".join(service_pool[:20])
                    + "\n"
                    if service_pool
                    else ""
                )
                + "- services：正文里出现过的服务 / 课程类名（以「服务」「课程」收尾的，"
                "一律放这一行，不要放进 products）\n"
                "- industry：所属行业（一句话）\n"
                "- keywords：普通用户找这类企业会搜的行业词 / 痛点词 6-10 个"
                "（要来自正文说的业务；不要公司名、不要品牌名、不要材料标题里的词）\n"
                '严格 JSON 输出：{"company": [...], "products": [...], "services": [...], '
                '"industry": "...", "keywords": ["..."]}',
                max_tokens=800,
            )
            blob = text.strip()
            if not blob.startswith("{"):
                import re as _re

                m = _re.search(r"\{[\s\S]*\}", blob)
                blob = m.group(0) if m else ""
            picked = json.loads(blob) if blob else {}
            allowed = set(company_cands) | set(titles)
            title_set = set(titles)
            for key in ("company", "products", "services"):
                # 材料里出现过的名字才收。**素材标题本身不算产品名**：标题是「这份材料叫什么」，
                # 不是「企业在卖什么」（实测模型会把标题原样列进产品候选）。
                vals: list[str] = []
                for raw in picked.get(key) or []:
                    name = str(raw).strip()
                    if not name:
                        continue
                    if name not in company_cands and (
                        name in title_set or not _grounded_in_materials(name, corpus, allowed)
                    ):
                        continue
                    if key != "company" and looks_like_style_word(name):
                        continue
                    # 模型常把名字截短（实测公司给了「笔革」而不是「笔革家居」）——
                    # 扩回候选池里更完整的同名项。产品/服务不许扩成素材标题。
                    name = _expand_to_pool_name(
                        name,
                        allowed,
                        blocked=title_set if key != "company" else (),
                        preferred=set(company_cands),
                    )
                    if name not in vals:
                        vals.append(name)
                if key == "products":
                    # 规则池是**产品**的确定性下限：模型没提到的产品也带上（正文里有证据）。
                    # 注意不能并进服务那一行 —— 那会把「琥珀沙发」显示成服务。
                    vals = _merge_pool(vals, product_pool)
                if vals:
                    result[key] = vals if key != "company" else vals[:5]
                    result["classification_source"] = "llm"
            if picked.get("industry"):
                result["industry"] = str(picked["industry"]).strip() or None
                result["classification_source"] = "llm"
            if picked.get("keywords"):
                result["keywords"] = [str(x).strip() for x in picked["keywords"] if str(x).strip()]
        except Exception as e:  # noqa: BLE001 — LLM 只是归类器，失败不阻塞检测
            logger.warning("detect(materials) classify failed: %s", e)

    # 业务候选的兜底：**不用素材标题**（2026-09-22 修）。
    # 原来这里把「标题里不带噪声词」的素材标题当产品候选，于是文件名直接进了
    # 「产品（点击取消不想监测的）」那一行 —— 实测就是 export_1785221955586 /
    # 三品牌战略+奢侈品调研-前31页 / 笔革家居主理人访谈纪要。标题不是产品名：
    # 正文里认不出来就如实留空 + 一句人话提示，让人去补，而不是拿文件名充数。
    out = await _finalize_detect(
        result, biz_fallback=product_pool[:10], service_fallback=service_pool[:8]
    )
    if out["empty"]:
        # 一条都没认出来（例如只上传了文件名像流水号的材料）：别拿「知识库」顶包，
        # 这里读的是 GEO 自己的内容资产，就直说内容资产。
        out["hint"] = (
            "没从这些内容资产里认出公司名或产品名：可以在「内容资产」补一份公司介绍/产品资料"
            "再回来重新检测，或直接在公司/产品里手动填写。"
        )
    elif not out["products"] and not out["services"]:
        out["hint"] = (
            "只认出公司名，没从材料正文里认出产品名：可以在「内容资产」补一份产品资料再回来，"
            "或在下面的「产品」里手动写一个。"
        )
    return out


def _expand_to_pool_name(
    name: str, pool: set[str], *, blocked: set[str] | tuple = (), preferred: set[str] | tuple = ()
) -> str:
    """把模型截短的名字扩回候选池里更完整的那个：``笔革`` → ``笔革家居``。

    为什么需要：实测模型从正文里认出的是「笔革」「凡客」这种半截名字，页面上就直接显示成
    「笔革」。规则取词明明已经有完整的「笔革家居」，没有理由让半截的上桌。

    优先取 ``preferred``（规则挑出来的公司候选）里的那一个：只按长度取最长会把
    素材标题「笔革家居主理人访谈纪要」选上来 —— 那更不是名字。扩不了就原样返回。
    """
    if name in pool:
        return name
    longer = [p for p in pool if len(p) > len(name) and p.startswith(name) and p not in blocked]
    if not longer:
        return name
    picked_from_preferred = [p for p in longer if p in preferred]
    return sorted(picked_from_preferred or longer, key=len)[-1]


def _material_llm_digest(materials: list[dict], *, per_material: int = 1200, total: int = 6000) -> str:
    """给模型看的材料摘录：**标题 + 正文开头**（2026-09-22 修）。

    为什么不能只喂标题：只给标题时，模型能拿到的信息就是那几个文件名 —— 实测它于是把
    标题原样当成「产品」交回来（``export_1785221955586``、``三品牌战略+奢侈品调研-前31页``），
    关键词也全是标题里的词。看一眼正文，它才认得出这家企业在卖什么。
    """
    parts: list[str] = []
    used = 0
    for m in materials or []:
        title = str(m.get("title") or "").strip()
        body = " ".join(str(m.get("content") or "").split())
        piece = f"【材料】{title}\n{body[:per_material]}".strip()
        if not piece:
            continue
        if used + len(piece) > total:
            piece = piece[: max(0, total - used)]
        if not piece:
            break
        parts.append(piece)
        used += len(piece)
        if used >= total:
            break
    return "\n\n".join(parts)


def _material_corpus(materials: list[dict], *, per_material: int = 4000) -> str:
    """素材标题 + 正文拼成一份文本，用来核对「模型说的名字材料里确实出现过」。"""
    parts = []
    for m in materials or []:
        title = str(m.get("title") or "").strip()
        body = str(m.get("content") or "")[:per_material]
        parts.append(f"{title}\n{body}")
    return "\n".join(parts)


def _grounded_in_materials(name: str, corpus: str, pool: set[str]) -> bool:
    """这个名字有没有依据 —— 出现在素材标题/候选里，或它的 3 字片段出现在素材正文里。

    为什么要核：Owner 2026-09-22 要的是「从内容资产里面的文章去自动配置」，
    模型顺口编一个名单外的新产品就成了假的自动配置。看不出来就留空（宁缺毋造）。
    """
    if not name:
        return False
    if name in pool or any(len(name) >= 3 and (name in p or p in name) for p in pool):
        return True
    if name in corpus:
        return True
    if len(name) >= 3:
        return any(name[i : i + 3] in corpus for i in range(len(name) - 2))
    return False


# ── step 1（档 B）：从企业知识库检测（只有「知识库同步」用这一档） ──
async def _step_detect_from_knowledge():
    """企业知识库 → 候选名单 → LLM 归类（公司/产品/服务/行业/搜索词）

    2026-09-20 改造（知识源从换知识源前的老适配器换成 EIOS 知识库）：EIOS 的知识对象只有
    ``entity`` / ``fact`` 两种 type，公司/产品/服务那套分类在 Semantic 不在 Knowledge。
    所以「按 object_type 分组」这条老路在 EIOS 上恒为空 —— 之前的实现就是这么静默
    变成「知识库暂无企业资料」的。现在：
    1. 取企业知识对象（只读，含被引用频次）+ 企业文档标题；
    2. 候选池 = 出现在文档标题里 / 带公司后缀的 → 公司候选，带产品服务特征词的 → 业务候选；
    3. LLM 只做「从候选池里挑」，选不出就留空（不允许编造名单外的名字）；
    4. LLM 顺带补 industry / keywords（见 ④）。
    兜底：LLM 不可用 → company=公司候选前几名，products=业务候选前几名；
    知识库确实没有资料 → 空候选 + 提示上传，不编造。

    **调用方必须先开门**（``adapters.eios.knowledge_read_grant``）：这一档会实时读知识库，
    目前只有 ``/api/v1/kb-init/scan``（页面上的「知识库同步」按钮）有资格。
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
            "classification_source": None,
            "hint": f"企业知识库读不到（这不等于知识库是空的）：{str(e)[:200]}",
        }

    if not entities:
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True,
            "error": None,
            "classification_source": None,
            "hint": "知识库暂无企业资料——请先在知识库上传产品说明/公司介绍后重试",
        }

    # ① 候选池：EIOS 的知识对象只有 entity / fact 两种 type —— 公司/产品/服务那套分类在
    #    Semantic，不在 Knowledge。所以这里不再假装按 object_type 分类（换知识源前的老适配器有
    #    company/product/service 字段，那条路在 EIOS 不存在），改成：
    #    名称规则 + 被文档引用频次 → 候选池 → 交给 LLM 归类（见 ②）。
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

    return await _finalize_detect(result, biz_fallback=biz_names[:10])


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


# ── 竞品发现：按所在地 + 行业/产品/服务分问，问部署里能答的每个模型 ─────────
#: 城市表与抠取逻辑抽到 app/services/region.py：监测探针也要按同一个城市问「本地」，
#: 两处各留一份词表迟早会不一致（2026-09-23 Owner：监测里问的还是「国内」）。
from app.services.region import clean_city, extract_city as _extract_city  # noqa: E402


#: 一次发现问几组问题：行业 1 + 产品 ≤2 + 服务 ≤2（Owner 2026-09-21：
#: 「问这几个 ai，成都本地的家装都有哪些公司，笔革家居下面的全案定制成都都有哪些公司」）
_MAX_PRODUCT_QUESTIONS = 2
_MAX_SERVICE_QUESTIONS = 2
#: 给用户勾选的候选上限（Owner：「用排名前十的给用户选择」）
_DISCOVERY_LIMIT = 10
#: 并发上限：问题 × 模型最坏 5×6=30 次调用，串行太慢，但要压住对模型入口的冲击
_DISCOVERY_CONCURRENCY = 4


def _discovery_questions(*, company: str, city: str, industry: str,
                         products: list[str], services: list[str]) -> list[dict]:
    """构造「问 AI 找同行」的问题：行业一句、产品/服务各不超过两句。

    只列中国品牌；自家名字明确排除（模型很爱把自己也列进来）。
    """
    where = city or "本地"
    ind = (industry or "").strip()
    out: list[dict] = []

    if ind:
        out.append({"kind": "industry", "topic": ind,
                    "text": f"{where}的{ind}都有哪些公司？"})
    for p in [x for x in products if (x or "").strip()][:_MAX_PRODUCT_QUESTIONS]:
        name = p.strip()
        out.append({"kind": "product", "topic": name,
                    "text": f"{company or '我们公司'}旗下的{name}，{where}都有哪些公司在做？"})
    for sv in [x for x in services if (x or "").strip()][:_MAX_SERVICE_QUESTIONS]:
        name = sv.strip()
        out.append({"kind": "service", "topic": name,
                    "text": f"{name}{where}本地有哪些公司？"})
    return out


def _discovery_prompt(question: str, own_names: list[str]) -> str:
    own_text = "、".join(own_names[:12]) if own_names else "（无）"
    return (
        f"{question}\n"
        "请把你了解到的相关公司/品牌一次列全，每个都带所属公司。\n"
        f"注意：以下名称属于我们自己，绝对不能列出来：{own_text}\n"
        "只列中国企业和中国品牌（如字节跳动、腾讯、阿里、华为、百度等），"
        "绝对不要国外品牌（OpenAI/Google/Microsoft/Salesforce 等）。\n"
        '严格 JSON 数组输出：[{"name": "公司或品牌名", "company": "所属公司名"}]'
    )


#: 逐行兜底时要扔掉的「这是人话不是公司名」标记。只放句子特征词，
#: 不放「公司 / 设计 / 家装」这类**正当名字里会出现**的词（「蜀韵装饰有限公司」是候选，不是噪声）。
_PROSE_MARKS = (
    "以上", "以下", "我们", "哪些", "什么", "为什么", "回答", "介绍", "例如", "比如", "包括",
    "主要", "还有", "其他", "这些", "那些", "总结", "备注", "结论", "建议", "希望", "根据",
    "相关", "可以", "这类", "如下", "首先", "其次", "最后", "好的", "注意",
)


def _extract_brands(text: str) -> list[str]:
    """模型没按 JSON 答（改成编号列表 / 顿号串）→ 逐行抠公司名。

    这是 `_candidates_from` 的**最后一层兜底**：模型答「1. 成都锦华设计\n2. 蜀韵家装」
    这类文本时，JSON 与截断抢救都取不到东西，只能靠这个。
    宁可少取，不要取句子：带人话标记的整行/整段一律丢掉。
    """
    out: list[str] = []
    for line in (text or "").splitlines():
        raw = line.strip().lstrip("0123456789.、)）(（·-—*# \t").strip()
        if not raw or len(raw) > 60:
            continue
        if "？" in raw or "?" in raw:
            continue
        if "{" in raw or "}" in raw or '"' in raw:
            continue  # JSON 残渣：这行不是「人写的列表」
        # 「如：成都锦华设计」→「如」太短被丢掉，落到真名字；
        # 「成都锦华设计：本地龙头」→ 前半是真名字，后半是解释。
        parts = [x.strip() for x in raw.split("：")] if "：" in raw else [raw]
        segments: list[str] = []
        for piece in parts:
            segments.extend(x.strip() for x in piece.split("、"))
        for seg in segments:
            name = seg.strip().strip("。；;，,")
            if not (2 <= len(name) <= 24):
                continue
            if any(m in name for m in _PROSE_MARKS):
                continue
            if name not in out:
                out.append(name)
    return out


def _candidates_from(text: str, own_names: list[str]) -> list[dict]:
    """一条模型回答 → 候选公司列表。

    三层兜底：完整 JSON → 从截断 JSON 里抢救 name/company → 逐行品牌名。
    """
    out: list[dict] = []
    parsed = _extract_json_array(text)
    if not parsed:
        parsed = _salvage_pairs(text)
    if parsed:
        for it in parsed:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            if name and not _is_own(name, own_names):
                out.append({"name": name, "company": str(it.get("company") or "").strip()})
        return out
    for name in _extract_brands(text):
        if name and not _is_own(name, own_names):
            out.append({"name": name, "company": ""})
    return out


def _rank_candidates(hits: list[dict]) -> list[dict]:
    """候选去重 + 排序：**被越多的模型提到越靠前**，其次被越多组问题提到，再次按出现先后。

    hits: [{name, company, engine, kind, order}]
    """
    merged: dict[str, dict] = {}
    for h in hits:
        key = h["name"]
        cur = merged.get(key)
        if cur is None:
            merged[key] = {
                "name": key,
                "company": h["company"],
                "engines": {h["engine"]},
                "kinds": {h["kind"]},
                "order": h["order"],
            }
            continue
        cur["engines"].add(h["engine"])
        cur["kinds"].add(h["kind"])
        cur["order"] = min(cur["order"], h["order"])
        if not cur["company"] and h["company"]:
            cur["company"] = h["company"]

    _KIND_CN = {"industry": "行业", "product": "产品", "service": "服务"}
    rows = []
    for item in merged.values():
        rows.append({
            "name": item["name"],
            "company": item["company"],
            "mentioned_by": sorted(item["engines"]),
            "asked": [_KIND_CN.get(k, k) for k in sorted(item["kinds"])],
            "engine_count": len(item["engines"]),
            "kind_count": len(item["kinds"]),
            "order": item["order"],
        })
    rows.sort(key=lambda r: (-r["engine_count"], -r["kind_count"], r["order"]))
    return rows


async def _step_discover(products: list[str], own_names: list[str] | None = None, company: str = "",
                         industry: str = "", city: str = "", services: list[str] | None = None):
    """竞品发现（Owner 2026-09-21 重做）：按**所在地** + 行业/产品/服务分组提问。

    - 问题：行业 1 句 + 产品 ≤2 句 + 服务 ≤2 句（「成都本地的家装都有哪些公司」这类问法）；
    - 问谁：**部署登记且这次真能答的每个模型**（不再写死豆包）。某个模型没配凭据就如实跳过，
      结果里带上「N 个模型里 M 个答了」—— 谁配了 key 是部署的事，不是 GEO 能补的；
    - 汇总：合并去重 → 按「被几个模型提到」排序 → 取前 10 给用户勾选。

    以前这里只问**一个**模型、只问**一句**话，而且城市只能从公司名里抠；
    「笔革家居」抠不出城市 → 退化成全国，实测返回的是三维家/酷家乐/土巴兔一类的
    **全国性平台**，而不是成都本地的家装公司。
    """
    from adapters.engines import (
        EngineFaceError,
        EngineNotConfigured,
        ONBOARD_CONSUMER,
        ask,
        list_engines,
    )

    own_names = [o for o in (own_names or []) if o]
    # 「成都市」这类带市字的写法归一成「成都」，免得问出「成都市本地的家装……」
    asked_city = clean_city(city)
    parsed_city = _extract_city(company)
    city = asked_city or parsed_city
    city_source = "user" if asked_city else ("company_name" if parsed_city else "none")

    questions = _discovery_questions(
        company=company, city=city, industry=industry or "",
        products=products or [], services=services or [],
    )
    if not questions:
        return {
            "competitors": [], "empty": True, "city": city, "questions": [],
            "engines_total": 0, "engines_answered": 0,
            "hint": "还没有行业/产品可问——先在第 1 步确认行业与产品，再来发现竞品。",
        }

    try:
        engines = await list_engines()
    except (EngineNotConfigured, EngineFaceError) as exc:
        logger.warning("竞品发现拿不到模型清单：%s", str(exc)[:150])
        engines = []
    engines = [e for e in engines if e.get("id")]

    hits: list[dict] = []
    answered: set[str] = set()
    failed: list[str] = []
    order = 0

    if engines:
        sem = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def _one(engine_id: str, q: dict) -> tuple[str, dict, str]:
            async with sem:
                try:
                    text = await ask(engine_id, _discovery_prompt(q["text"], own_names),
                                     max_tokens=900, consumer=ONBOARD_CONSUMER)
                    return engine_id, q, (text or "")
                except EngineNotConfigured as exc:
                    # 「这个部署还没给这个模型配凭据」不是故障：如实跳过它，其余模型照问。
                    logger.info("竞品发现：模型 %s 未配置，跳过（%s）", engine_id, str(exc)[:120])
                    return engine_id, q, ""
                except EngineFaceError as exc:
                    logger.info("竞品发现：模型 %s 没答（%s）", engine_id, str(exc)[:120])
                    return engine_id, q, ""
                except Exception as exc:  # noqa: BLE001 — 单个模型坏掉不该毁掉整次发现
                    logger.warning("竞品发现：模型 %s 异常 %s", engine_id, str(exc)[:150])
                    return engine_id, q, ""

        results = await asyncio.gather(*[_one(e["id"], q) for q in questions for e in engines])
        for engine_id, q, text in results:
            if not text.strip():
                continue
            answered.add(engine_id)
            for c in _candidates_from(text, own_names):
                order += 1
                hits.append({"name": c["name"], "company": c["company"],
                             "engine": engine_id, "kind": q["kind"], "order": order})
    else:
        failed.append("这个部署还没登记任何模型")

    ranked = _rank_candidates(hits)
    items = [{k: r[k] for k in ("name", "company", "mentioned_by", "asked")}
             for r in ranked[:_DISCOVERY_LIMIT]]

    hint = None
    if not items:
        hint = ("没有任何模型返回候选——请手动在监测中心添加竞品对象"
                if engines else "这个部署还没有可用模型，请手动添加竞品对象")
    return {
        "competitors": items,
        "empty": not items,
        "hint": hint,
        "city": city,
        "city_source": city_source,
        "questions": [q["text"] for q in questions],
        "engines_total": len(engines),
        "engines_answered": len(answered),
        "engines_used": sorted(answered),
        "not_answered": [e["id"] for e in engines if e["id"] not in answered],
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
    # 所在地（Owner 2026-09-23）：以前只喂给「发现竞品」，**没写进对象** ——
    # 于是监测探针不知道企业在哪，行业问句只能写死「国内」。现在写进每个对象的 config，
    # 探针按「成都本地的家居家具公司有哪些？」问。没填就不写这个键（探针如实退回通用问法）。
    city = clean_city(cfg.city)

    def _c(config: dict) -> dict:
        if city:
            config["city"] = city
        return config

    if cfg.company:
        _mk("brand", _c({"company": cfg.company, "aliases": aliases, "product": products, "industry": cfg.industry, "tier": "lite"}), cfg.company)
    for p in products:
        _mk("product", _c({"product": p, "company": cfg.company, "competitor": []}), p)
    # 服务也要建对象（2026-09-22 修）：以前这里算了 services 却**从没用过** ——
    # 用户在页面上勾的服务等于没勾，不产生任何监测。用 kind=service 让探针问得像服务，
    # 展示上仍是既有的「产品服务」类型（没有新增类型、没有新增契约）。
    for sv in services:
        _mk("product", _c({"product": sv, "kind": "service", "company": cfg.company, "competitor": []}), sv)
    if cfg.industry:
        _mk("keyword", _c({"keyword": cfg.industry, "extras": products}), cfg.industry)
    # 行业搜索词（detect 挖出）→ 每个建 keyword 对象：监测面从「1 个行业词」扩到「N 个用户真实搜索词」
    seen_kw: set[str] = set()
    for kw in (cfg.keywords or []):
        kw = str(kw).strip()
        if kw and kw != cfg.industry and kw not in seen_kw:
            seen_kw.add(kw)
            _mk("keyword", _c({"keyword": kw, "extras": products}), kw)
    for c in (cfg.competitors or []):
        name = str(c.get("name") or "").strip()
        if name:
            _mk("competitor", _c({"company": cfg.company, "target": cfg.company, "competitor": [name], "product": products, "industry": cfg.industry}), f"{cfg.company} vs {name}")
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
                    det = await _step_detect_from_materials()
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
            # Owner 2026-09-22：自动配置从 GEO 自己的内容资产来（不再实时读知识库）
            return ok(await _step_detect_from_materials())
        if step == "discover":
            return ok(
                await _step_discover(
                    [p for p in (payload.products or []) if p],
                    own_names=[payload.company, *payload.aliases, *payload.products, *payload.services],
                    company=payload.company or "",
                    industry=payload.industry or "",
                    city=payload.city or "",
                    services=[x for x in (payload.services or []) if x],
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
