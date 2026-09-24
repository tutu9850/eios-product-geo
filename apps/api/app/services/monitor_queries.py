"""Monitor query generation domain service.

This module owns the deterministic MonitorItem -> probe query mapping.
It deliberately has no persistence or HTTP dependencies so the generator can
be tested and evolved independently from the API router.
"""
from app.services.region import clean_city

def _item_company(item: dict) -> str:
    """item 的主企业名（brand=company；competitor=target；其余取 entity 兜底）"""
    cfg = item.get("config_json") or {}
    if item.get("type") == "brand":
        return cfg.get("company") or item.get("entity") or ""
    if item.get("type") == "competitor":
        return cfg.get("target") or item.get("entity") or ""
    return cfg.get("company") or item.get("entity") or ""


_BRAND_TIER_COUNT = {"lite": 2, "standard": 4, "deep": 8}
_BRAND_CATEGORY_LABELS = {
    "awareness": "品牌认知", "trust": "信任判断", "recommend": "推荐意图",
    "comparison": "竞品比较", "scenario": "场景需求", "risk": "风险认知",
}

#: 行业长句截短用的句读（自动配置 detect 出来的行业是**一句话**，见 onboard ③）；
#: 探针模板里塞整句会问出「国内家居家具行业，主营沙发、软床及定制家具的设计、生产与销售平台有哪些？」
_SENTENCE_SEPS = ("，", ",", "。", "！", "；", ";", "\n")
_INDUSTRY_TAILS = ("行业", "领域", "赛道", "产业")


def _probe_term(text: str) -> str:
    """行业/关键词长句 → 探针里能读的短词（「家居家具行业，主营沙发……」→「家居家具」）。

    只做两件事：有句读的长句取第一个分句；再去掉尾部「行业/领域/赛道/产业」。
    短词（「家装设计」「琥珀沙发」）原样返回 —— 不误伤正常关键词。
    """
    t = (text or "").strip()
    if not t:
        return ""
    for sep in _SENTENCE_SEPS:
        idx = t.find(sep)
        if idx > 0:
            t = t[:idx].strip()
            break
    for tail in _INDUSTRY_TAILS:
        if t.endswith(tail) and len(t) > len(tail):
            t = t[: -len(tail)].strip()
            break
    return t


def generate_brand_queries(cfg: dict, tier: str = "standard") -> dict:
    """品牌认知探针：6 类维度 × 档位数量（lite 2 / standard 4 / deep 8）

    维度链 = 认识我→信任我→推荐我→比较我→联想到我→为什么不选我；
    推荐意图用**间接探针**（问品类/场景，不问自己——真实用户不会问"推荐云启吗"）。
    """
    company = (cfg.get("company") or "").strip()
    products = cfg.get("product") or []
    if isinstance(products, str):
        products = [products]
    products = [p.strip() for p in products if p and p.strip()]
    product = products[0] if products else ""
    # 行业长句截短（「家居家具行业，主营……」→「家居家具」）；所在地用于「本地」问法
    industry = _probe_term(cfg.get("industry"))
    city = clean_city(cfg.get("city"))
    local = f"{city}的" if city else ""
    customer = (cfg.get("customer") or "").strip()
    competitors = cfg.get("competitor") or []
    if isinstance(competitors, str):
        competitors = [competitors]
    competitors = [c.strip() for c in competitors if c and c.strip()]

    n = _BRAND_TIER_COUNT.get(tier, 4)
    cats: dict[str, list[str]] = {}

    # 1 基础认知（认识我）
    a = []
    if company:
        a += [f"{company}是什么？", f"{company}是做什么的？"]
        if product:
            a.append(f"{company}有哪些产品？")
        if customer:
            a.append(f"{company}服务哪些客户？")
        if industry:
            a.append(f"{company}属于哪个行业？")
    cats["awareness"] = a[:n]

    # 2 信任判断（敢不敢推荐）
    t = []
    if company:
        t += [f"{company}靠谱吗？", f"{company}值得合作吗？"]
        if product:
            t.append(f"{company}的{product}有什么优势？")
        t.append(f"{company}有什么成功案例？")
    cats["trust"] = t[:n]

    # 3 推荐意图（间接探针，不问自己）——「本地」的答案才有商业价值：
    #   2026-09-23 Owner：「行业还是国内，不是成都，不是根据自动配置的行业问的，问的时候要加本地」。
    #   以前这里写死「国内{industry}平台有哪些？」—— 企业所在地明明在自动配置里填过，
    #   探针却问全国；现在改成「成都本地的家居家具公司有哪些？」。没填所在地就如实退回通用问法，
    #   不硬写「国内」，也不编一个城市。
    r = []
    if product:
        r.append(f"{local}{product}推荐哪些公司？")
    if industry:
        r.append(f"{city}本地的{industry}公司有哪些？" if city else f"{industry}公司有哪些？")
    if customer:
        r.append(f"适合{customer}的AI系统有哪些？")
    if product and customer:
        r.append(f"如果{customer}想部署{product}，推荐什么？")
    if company:
        r.append(f"有没有类似{company}的产品？")
    cats["recommend"] = r[:n]

    # 4 竞品比较（为什么别人赢）
    c = []
    for comp in competitors:
        if company:
            c.append(f"{company}和{comp}哪个好？")
            c.append(f"{company}和{comp}有什么区别？")
    if product and competitors:
        c.append(f"{product}应该选{company or '哪家'}还是{competitors[0]}？")
    cats["comparison"] = c[:n]

    # 5 场景需求（什么时候想到我）
    s = []
    if product:
        s.append(f"企业如何建立{product}？")
    if industry:
        s.append(f"{industry}有哪些应用方案？")
    if customer:
        s.append(f"{customer}如何应用AI？")
    if product or industry or customer:
        s.append("企业数字化转型应该选择什么工具？")
    cats["scenario"] = s[:n]

    # 6 风险认知（为什么不选我）
    risk = []
    if company:
        # 2026-09-21（Owner 点名「怎么还会问这么愚蠢的问题」）：删掉
        # 「使用{company}需要注意什么？」—— 公司不是能「使用」的东西，这句话本身不成立；
        # 而且这类探针不问事实，只逼模型替我们编一份「注意事项」，
        # 于是监测里出现「输出正常但不正确」的条目（实测：模型答「建议查工商信息/警惕风险」，
        # 被记成 negative，再进总览当负面情绪）。
        # 留下的四句都是真实用户在决策前会搜的话，测的是「AI 会不会说我们坏话」，不是让 AI 编坏话。
        risk += [f"{company}有哪些缺点？", f"{company}有什么负面评价？"]
        risk += [f"{company}适合哪些企业？", f"{company}不适合哪些企业？"]
    cats["risk"] = risk[:n]

    # 展平（去重保序）
    queries: list[str] = []
    for k in ("awareness", "trust", "recommend", "comparison", "scenario", "risk"):
        for q in cats[k]:
            if q not in queries:
                queries.append(q)
    return {"categories": cats, "queries": queries}


def generate_queries(item: dict, context: dict | None = None) -> list[str]:
    """MonitorItem → 本次运行要问 AI 的查询问题列表（探针）

    context（预留扩展点）：未来可带 industry/region/intent 等上下文，
    模板只是第一版实现，后续在不动调用方的前提下替换生成策略。
    """
    t = item.get("type")
    cfg = item.get("config_json") or {}
    city = clean_city(cfg.get("city"))
    local = f"{city}的" if city else ""  # 本地问法前缀（没填所在地就为空）
    queries: list[str] = []

    if t == "brand":
        # 6 类维度 × 档位（lite/standard/deep），推荐意图用间接探针
        tier = cfg.get("tier") or "standard"
        queries = generate_brand_queries(cfg, tier)["queries"]
    elif t == "product":
        product = cfg.get("product") or item.get("entity") or ""
        # kind=service（自动配置勾的服务）：问法要像服务，不像一件货
        # （「量尺哪个好？」这种问出来没有意义）。
        is_service = str(cfg.get("kind") or "") == "service"
        if product and is_service:
            queries = [
                f"{local}{product}哪家公司做得好？",
                f"{product}怎么收费？",
                f"{product}一般包含哪些内容？",
            ]
        elif product:
            queries = [
                # 「{product}推荐？」缺宾语（问出来是半句话，模型只能反问「你想推荐什么」）
                f"{local}{product}推荐哪些公司？",
                f"{product}价格多少？",
                f"{product}哪个好？",
            ]
    elif t == "competitor":
        # 0.4 竞品分析：5 类竞争探针（brand/comparison/selection/capability/scenario）
        # 双主体信息：我方 company/aliases/product/industry + 竞品名/别名
        target = cfg.get("company") or cfg.get("target") or item.get("entity") or ""
        comp = cfg.get("competitor") or ""
        if isinstance(comp, list):
            comp = comp[0] if comp else ""
        product = cfg.get("product") or ""
        if isinstance(product, list):
            product = product[0] if product else ""
        industry = _probe_term(cfg.get("industry"))
        if target and comp:
            # ① 品牌/比较类
            queries.extend(
                [
                    f"{target}和{comp}哪个好？",
                    f"{target}和{comp}有什么区别？",
                    f"{comp}为什么被推荐？",
                ]
            )
            # ② 选择类（用户决策场景）
            if industry:
                queries.append(f"{industry}应该选择{target}还是{comp}？")
            if product:
                queries.append(f"{product}应该选{target}还是{comp}？")
            # ③ 能力类
            queries.append(f"{target}和{comp}分别有什么优势？")
            # ④ 场景类（结合我方行业）
            # 2026-09-21：原来这里写死了「企业知识管理应该选择X还是Y？」—— 家装公司也会被问
            # 「企业知识管理…」，跟它的生意毫无关系，而且当行业存在时与上一句完全重复。
            if industry:
                queries.append(f"{industry}领域，{comp}和{target}谁更适合？")
    elif t == "keyword":
        # 关键词/行业同样是长句截短：自动配置建的这个对象，keyword 就是那句行业话术
        kw = _probe_term(cfg.get("keyword"))
        industry = _probe_term(cfg.get("industry"))
        if kw:
            suffix = f"{industry}（{kw}）" if industry else kw
            queries = [
                f"{local}{kw}哪个好？",
                f"{kw}有哪些推荐？",
                f"怎么选{suffix}？",
            ]
    elif t == "review":
        audience = cfg.get("audience") or item.get("entity") or ""
        scenario = cfg.get("scenario") or ""
        if audience or scenario:
            base = audience or "用户"
            queries = [
                f"{base}为什么要用知识库？",
                f"{base}最关心哪些功能？",
            ]
            if scenario:
                queries.append(f"{scenario}怎么办？")
    elif t == "question":
        q = cfg.get("query") or ""
        if q:
            queries = [q]
    # 去重保序：竞品分支是逐条 append 的，写法一变就可能出现同一句问两遍（白烧模型额度）
    deduped: list[str] = []
    for q in queries:
        q = (q or "").strip()
        if q and q not in deduped:
            deduped.append(q)
    return deduped


