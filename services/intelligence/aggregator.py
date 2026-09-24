"""Intelligence 分析引擎 — 聚合层（无 LLM）

从 brand_mention + 最新 succeeded extraction 滚出：
- matrix：差距矩阵（维度榜 + 三色 + 观察区）
- perception：认知标签分布

规则（Owner 拍板 + 外部评审钉死）：
- 同义词合并只在聚合层做（库内存 LLM 原文 factor）
- 出现 ≥2 次才算正式维度；1 次进观察区
- 三色以「AI 回答有没有提到」为准：🔴 他方被夸≥1 且我方<2 → 补；
  🟢 我方被夸≥2 → 已有；观察区 = 总提及 1 次
- 竞品名单：monitor_item config_json.competitor 或 context.competitors；
  无竞品时不出假数据（他方提及仍统计并标注 brand）
- gap_type（企业知识库对照）属 S2，matrix 留空字段
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models.geo_models import (
    BrandMention,
    GeoEvidence,
    GeoExtraction,
    SessionLocal,
    init_db,
)

from services.intelligence import repo
from services.repository import current_tenant_or_default

logger = logging.getLogger("eios.intelligence.aggregator")

DEFAULT_TENANT = "tenant_corp_01"


def _resolve_tenant(tenant: str | None) -> str:
    """没显式传租户时用**当前请求的柜**（账号分柜，Owner 2026-09-22）。

    显式传进来的租户一律照用 —— 脚本和后台任务靠这个跑指定柜，不能被悄悄改道。
    """
    return tenant or current_tenant_or_default()


# 企业名后缀剥离（与 monitor 规则一致）
_COMPANY_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "科技", "股份",
)


def _strip_company_suffix(name: str) -> str:
    n = (name or "").strip()
    changed = True
    while changed and len(n) > 1:
        changed = False
        for s in _COMPANY_SUFFIXES:
            if n.endswith(s) and len(n) > len(s):
                n = n[: -len(s)]
                changed = True
                break
    return n


def _is_self(brand: str, company: str) -> bool:
    if not company:
        return False
    b = (brand or "").strip()
    if b == company:
        return True
    bs = _strip_company_suffix(b)
    cs = _strip_company_suffix(company)
    if bs == cs and len(bs) > 1:
        return True
    # 前缀判定（≥2 字）：「云启」vs「云启智能」——简称算我方；2 字门槛防 1 字误杀
    if len(bs) >= 2 and len(cs) >= 2 and (cs.startswith(bs) or bs.startswith(cs)):
        return True
    return False


def _monitor_brand_set(company: str | None, tenant: str) -> set[str]:
    """监测对象品牌清单：monitor_items 的 entity（我方产品/对象）+ config 的 competitor/别名。

    聚合层兜底：只统计清单内品牌（配合提取层硬限制，双保险）。返回空集 = 无监测对象
    （保持旧行为：他方提及仍统计），有清单则非清单品牌不进竞品区。
    """
    init_db()
    brands: set[str] = set()
    try:
        from app.models.geo_models import GeoMonitorItems

        with SessionLocal() as db:
            rows = db.query(GeoMonitorItems).filter(GeoMonitorItems.tenant_id == tenant).all()
        for r in rows:
            try:
                data = json.loads(r.data_json or "{}")
            except Exception:
                continue
            cfg = data.get("config_json") or {}
            e = (data.get("entity") or "").strip()
            if e:
                brands.add(e)
            comp = cfg.get("competitor") or data.get("competitor") or []
            if isinstance(comp, str):
                comp = [comp]
            for x in comp:
                x = (x or "").strip()
                if x:
                    brands.add(x)
            aliases = (cfg.get("aliases") or []) + (data.get("aliases") or [])
            comp_aliases = cfg.get("competitor_aliases") or []
            for a in aliases + comp_aliases:
                a = (a or "").strip()
                if a:
                    brands.add(a)
    except Exception:  # 清单读取失败不阻塞聚合（回退旧行为）
        logger.warning("aggregator: _monitor_brand_set 读取失败，回退不过滤", exc_info=True)
    return brands


def _brand_in_set(brand: str, brand_set: set[str]) -> bool:
    """品牌是否属于清单（归一化：剥后缀 + 互为子串防「华为云」vs「华为」）"""
    b = _strip_company_suffix((brand or "").strip())
    if not b:
        return False
    for x in brand_set:
        x2 = _strip_company_suffix(x)
        if b == x2 or (len(b) >= 3 and (b in x2 or x2 in b)):
            return True
    return False


def _filter_mentions(mentions: list[dict], company: str | None, tenant: str) -> list[dict]:
    """D0 竞品范围过滤（matrix/compare 共用）：只保留我方 + 监测清单内品牌。

    无监测对象（清单空）时不过滤（保持旧行为：他方提及仍统计并标注 brand）。
    """
    monitor_set = _monitor_brand_set(company, tenant)
    if not monitor_set:
        return mentions
    out = []
    for m in mentions:
        subject = m.get("subject_company") or company or ""
        if _is_self(m["brand_name"], subject):
            out.append(m)
        elif _brand_in_set(m["brand_name"], monitor_set):
            out.append(m)
    return out


def _succeeded_evidence_ids(since_dt: datetime, company: str | None, source_type: str, tenant: str) -> set[str]:
    """满足过滤条件且最新 extraction 为 succeeded 的 evidence_id 集合。"""
    init_db()
    with SessionLocal() as db:
        sub = (
            db.query(
                GeoExtraction.evidence_id,
                func.max(GeoExtraction.version).label("maxv"),
            )
            .group_by(GeoExtraction.evidence_id)
            .subquery()
        )
        latest = (
            db.query(GeoExtraction)
            .join(sub, (GeoExtraction.evidence_id == sub.c.evidence_id) & (GeoExtraction.version == sub.c.maxv))
            .filter(GeoExtraction.status == "succeeded")
            .subquery()
        )
        q = db.query(GeoEvidence.id).join(latest, GeoEvidence.id == latest.c.evidence_id)
        q = q.filter(GeoEvidence.tenant_id == tenant)
        # source_type=all|*|空 → 不按来源过滤（UI「全部」）；其余精确匹配
        if source_type and source_type not in ("all", "*", "any"):
            q = q.filter(GeoEvidence.source_type == source_type)
        if company:
            q = q.filter(GeoEvidence.subject_company == company)
        if since_dt:
            q = q.filter(GeoEvidence.observed_at >= since_dt)
        return {r[0] for r in q.all()}


def _load_mentions(evidence_ids: set[str], tenant: str) -> list[dict]:
    if not evidence_ids:
        return []
    init_db()
    with SessionLocal() as db:
        # 版本过滤（2026-08-15 修复）：只计入"最新一次 succeeded 解析"的 mentions，
        # 旧版本/失败残留的 mentions 不计入聚合（防提及数虚高）
        from sqlalchemy import func as _func
        latest = (
            db.query(
                GeoExtraction.evidence_id,
                _func.max(GeoExtraction.version).label("max_version"),
            )
            .filter(GeoExtraction.status == "succeeded")
            .group_by(GeoExtraction.evidence_id)
            .subquery()
        )
        rows = (
            db.query(BrandMention, GeoEvidence.subject_company)
            .join(GeoEvidence, BrandMention.evidence_id == GeoEvidence.id)
            .join(latest, latest.c.evidence_id == BrandMention.evidence_id)
            .filter(BrandMention.evidence_id.in_(evidence_ids))
            .order_by(BrandMention.created_at.asc())
            .all()
        )
        out = []
        for m, subject in rows:
            d = repo._row_to_dict(m)
            d["subject_company"] = subject  # self 判定基准（不依赖查询参数）
            out.append(d)
        return out


def matrix(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str | None = None,
) -> dict:
    """差距矩阵（S1：维度提及聚合 + 三色；gap_type 留 S2 企业知识库对照）。"""
    tenant = _resolve_tenant(tenant)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = _succeeded_evidence_ids(since_dt, company, source_type, tenant)
    mentions = _load_mentions(ev_ids, tenant)
    syn_map = repo.list_synonyms(tenant)

    # 1. 同义词合并 + 去重（同 evidence+品牌+类型+维度+quote 只算一次）
    #    missing 类型单独归类（不进维度榜，S2 知识缺口用）
    seen: set[tuple] = set()
    dims: dict[str, dict] = {}
    missing_notes: list[dict] = []
    # D0：竞品范围过滤（我方 + 监测清单内品牌，非清单品牌不进竞品区）
    mentions = _filter_mentions(mentions, company, tenant)
    for m in mentions:
        subject = m.get("subject_company") or company or ""
        if m["mention_type"] == "missing":
            missing_notes.append(
                {"brand": m["brand_name"], "quote": m["evidence_quote"], "subject_company": subject}
            )
            continue
        factor = syn_map.get(m.get("factor") or "", m.get("factor") or "__missing__")
        key = (m["evidence_id"], m["brand_name"], m["mention_type"], factor, m["evidence_quote"])
        if key in seen:
            continue
        seen.add(key)
        d = dims.setdefault(
            factor,
            {"dimension": factor, "self_mentions": 0, "other_mentions": 0, "total_mentions": 0, "quotes": [], "brands": {}},
        )
        d["total_mentions"] += 1
        if _is_self(m["brand_name"], subject):
            d["self_mentions"] += 1
        else:
            d["other_mentions"] += 1
            d["brands"][m["brand_name"]] = d["brands"].get(m["brand_name"], 0) + 1
            if len(d["quotes"]) < 3:
                d["quotes"].append({"brand": m["brand_name"], "quote": m["evidence_quote"], "evidence_id": m["evidence_id"]})

    # 2. 分档：正式维度（≥2）vs 观察区（=1）
    formal = {k: v for k, v in dims.items() if v["total_mentions"] >= 2}
    watch = {k: v for k, v in dims.items() if v["total_mentions"] == 1}

    # 3. 三色（以 AI 回答有没有提到为准）：
    #    🔴 red：他方被夸≥1 且我方<2 → 补
    #    🟢 green：我方被夸≥2 → 已有
    out = []
    for factor, d in sorted(formal.items(), key=lambda kv: -kv[1]["total_mentions"]):
        if d["self_mentions"] >= 2:
            band, label = "green", "🟢 已有"
        elif d["other_mentions"] >= 1:
            band, label = "red", "🔴 补"
        else:
            band, label = "green", "🟢 已有"
        # 胜负判定（我方 vs 他方提及）
        if d["self_mentions"] > d["other_mentions"]:
            verdict = "win"
        elif d["self_mentions"] < d["other_mentions"]:
            verdict = "loss"
        else:
            verdict = "tie"
        out.append(
            {
                "dimension": factor,
                "band": band,
                "band_label": label,
                "verdict": verdict,  # win=我方提及多 / loss=他方提及多 / tie
                "total_mentions": d["total_mentions"],
                "self_mentions": d["self_mentions"],
                "other_mentions": d["other_mentions"],
                "competitor_mentions": d["brands"],
                "quotes": d["quotes"],
                "gap_type": None,  # S2 企业知识库对照后填
            }
        )

    watch_out = []
    for factor, d in sorted(watch.items(), key=lambda kv: -kv[1]["total_mentions"]):
        watch_out.append(
            {
                "dimension": factor,
                "band": "watch",
                "band_label": "👁 观察区（1 次）",
                "total_mentions": 1,
                "self_mentions": d["self_mentions"],
                "other_mentions": d["other_mentions"],
                "competitor_mentions": d["brands"],
                "quotes": d["quotes"],
                "gap_type": None,
            }
        )

    # missing 去重（同 quote 只留一条）
    seen_missing = set()
    missing_out = []
    for mn in missing_notes:
        if mn["quote"] in seen_missing:
            continue
        seen_missing.add(mn["quote"])
        missing_out.append(mn)

    return {
        "company": company,
        "source_type": source_type,
        "days": days,
        "evidence_count": len(ev_ids),
        "dimensions": out,
        "observation": watch_out,
        "missing": missing_out,  # AI 提到我方但未推荐（S2 知识缺口输入）
        "total_mentions": len(seen),
    }


def _evidence_intents(ev_ids: set[str]) -> dict[str, str]:
    """evidence_id → 最新 succeeded extraction 的 intent（推荐/对比/认知等）。"""
    if not ev_ids:
        return {}
    init_db()
    with SessionLocal() as db:
        latest = (
            db.query(
                GeoExtraction.evidence_id,
                GeoExtraction.analysis_json,
                func.row_number()
                .over(partition_by=GeoExtraction.evidence_id, order_by=GeoExtraction.version.desc())
                .label("rn"),
            )
            .filter(GeoExtraction.evidence_id.in_(ev_ids))
            .subquery()
        )
        rows = (
            db.query(latest.c.evidence_id, latest.c.analysis_json)
            .filter(latest.c.rn == 1)
            .all()
        )
    out = {}
    for eid, aj in rows:
        try:
            d = json.loads(aj) if isinstance(aj, str) else aj
            out[eid] = d.get("intent") or "other"
        except Exception:  # noqa: BLE001
            out[eid] = "other"
    return out


COMPARISON_INTENTS = {"recommendation", "comparison"}


def brand_overview(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str | None = None,
    mode: str = "all",
) -> dict:
    """品牌提及概览：每个主体（我方+他方）被提及的 evidence 数 + 提及率%。

    口径（诚实标注，防"问题池围绕我方生成"造成的虚高）：
    - mode="all"：分母 = 全部已解析回答（我方专属问题多 → 我方提及率偏高，受问题分布影响）
    - mode="comparison"：分母 = 推荐/对比类回答（intent ∈ recommendation|comparison），
      我方与竞品在同一场景下公平比较
    提及率 = 提及该主体的 evidence 数（去重） / 对应分母。
    """
    tenant = _resolve_tenant(tenant)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = _succeeded_evidence_ids(since_dt, company, source_type, tenant)
    if mode == "comparison" and ev_ids:
        intents = _evidence_intents(ev_ids)
        ev_ids = {e for e in ev_ids if intents.get(e) in COMPARISON_INTENTS}
    mentions = _load_mentions(ev_ids, tenant)
    total = len(ev_ids)
    brand_ev: dict[str, set] = {}
    self_brands: set[str] = set()
    for m in mentions:
        if m["mention_type"] == "missing":
            continue  # missing 是"提到但未推荐"，不算正面提及；单独统计
        subject = m.get("subject_company") or company or ""
        if _is_self(m["brand_name"], subject):
            self_brands.add(m["brand_name"])
        brand_ev.setdefault(m["brand_name"], set()).add(m["evidence_id"])
    brands = []
    for name, evs in sorted(brand_ev.items(), key=lambda kv: -len(kv[1])):
        brands.append(
            {
                "name": name,
                "is_self": name in self_brands,
                "mentions": len(evs),
                "rate": round(len(evs) / total * 100, 1) if total else 0.0,
            }
        )
    return {
        "company": company,
        "mode": mode,
        "total_evidence": total,
        "brands": brands,
        "self_name": company or "",
    }


def share_of_voice(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str | None = None,
) -> dict:
    """SOV 声量份额（2026-08-15 新增，汇报第一指标）。

    口径（诚实标注）：
    - 提及份额：品牌被提及的 evidence 数 / 全部品牌提及总数（含 missing）
    - 推荐份额：品牌被推荐（mention_type=reason/trust，非 missing）数 / 全部推荐总数
      —— 这才是「AI 声量」：AI 推荐你 vs 推荐竞品的比例
    - 缺失份额：missing / 提及总数（AI 认知了但没推荐 = 机会面）
    - 趋势：按周窗口的推荐份额变化（≥2 周才有趋势）
    返回按推荐份额降序的品牌列表 + 我方标记 + 汇总。
    """
    tenant = _resolve_tenant(tenant)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = _succeeded_evidence_ids(since_dt, company, source_type, tenant)
    mentions = _load_mentions(ev_ids, tenant)

    brand_mention_n: dict[str, int] = {}
    brand_reco_n: dict[str, int] = {}
    brand_missing_n: dict[str, int] = {}
    self_brands: set[str] = set()
    for m in mentions:
        name = m["brand_name"]
        subject = m.get("subject_company") or company or ""
        if _is_self(name, subject):
            self_brands.add(name)
        brand_mention_n[name] = brand_mention_n.get(name, 0) + 1
        if m["mention_type"] == "missing":
            brand_missing_n[name] = brand_missing_n.get(name, 0) + 1
        else:
            brand_reco_n[name] = brand_reco_n.get(name, 0) + 1

    total_mention = sum(brand_mention_n.values())
    total_reco = sum(brand_reco_n.values())

    brands = []
    for name in brand_mention_n:
        mn = brand_mention_n.get(name, 0)
        rn = brand_reco_n.get(name, 0)
        xn = brand_missing_n.get(name, 0)
        brands.append({
            "brand": name,
            "is_self": name in self_brands,
            "mention_count": mn,
            "mention_share": round(mn / total_mention * 100, 1) if total_mention else 0.0,
            "recommend_count": rn,
            "recommend_share": round(rn / total_reco * 100, 1) if total_reco else 0.0,
            "missing_count": xn,
        })
    brands.sort(key=lambda b: -b["recommend_share"])

    # 趋势：按周窗口推荐份额（mention.created_at）
    week_map: dict[str, dict[str, int]] = {}  # 周 → {brand: reco_n}
    for m in mentions:
        if m["mention_type"] == "missing":
            continue
        ts = m.get("created_at") or m.get("observed_at") or ""
        wk = str(ts)[:10]  # 简化：按天，日报趋势；周报可后续聚周
        week_map.setdefault(wk, {})
        week_map[wk][m["brand_name"]] = week_map[wk].get(m["brand_name"], 0) + 1
    trend = []
    for wk in sorted(week_map.keys()):
        wk_total = sum(week_map[wk].values()) or 1
        trend.append({
            "period": wk,
            "brands": [
                {"brand": b, "recommend_share": round(n / wk_total * 100, 1)}
                for b, n in sorted(week_map[wk].items(), key=lambda kv: -kv[1])
            ][:5],
        })

    self_share = next((b for b in brands if b["is_self"]), None)
    return {
        "company": company,
        "period_days": days,
        "total_mention": total_mention,
        "total_recommend": total_reco,
        "self": self_share,
        "brands": brands,
        "trend": trend,
        "note": "推荐份额 = AI 推荐你 vs 推荐竞品的比例（mention_type=reason/trust）；缺失=认知但未推荐（机会面）",
    }


def trend_delta(
    company: str | None = None,
    days: int | None = 60,
    source_type: str = "ai_answer",
    tenant: str | None = None,
    window_days: int = 7,
) -> dict:
    """推荐率趋势变化（2026-08-15 新增）：对比相邻周期（默认 7 天）的品牌推荐变化。

    输出：
    - periods：已积累的周期列表（每周期各品牌推荐数）
    - gained：本周新被推荐的品牌（上周无）
    - lost：上周有、本周消失的品牌
    - rising / falling：推荐数升/降的品牌（含幅度）
    无 ≥2 周期时返回空变化（诚实：数据不足不编造）。
    """
    tenant = _resolve_tenant(tenant)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = _succeeded_evidence_ids(since_dt, company, source_type, tenant)
    mentions = _load_mentions(ev_ids, tenant)

    # 按周期窗口分组：{period_key: {brand: reco_n}}
    from datetime import timedelta as _td

    now = datetime.now(timezone.utc)
    periods: dict[str, dict[str, int]] = {}
    for m in mentions:
        if m["mention_type"] == "missing":
            continue
        ts_raw = m.get("created_at") or m.get("observed_at") or ""
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        days_ago = (now - ts).days
        wk = days_ago // window_days  # 0=本周, 1=上周...
        key = f"第{max(0, wk) + 1}周期"
        periods.setdefault(key, {})
        periods[key][m["brand_name"]] = periods[key].get(m["brand_name"], 0) + 1

    ordered = sorted(periods.items())  # key 是 "第N周期" 字符串排序 OK
    if len(ordered) < 2:
        return {
            "periods": [{"period": k, "brands": v} for k, v in ordered],
            "gained": [], "lost": [], "rising": [], "falling": [],
            "note": "不足两个周期，趋势变化待数据积累（每 7 天一个周期）",
        }

    cur_key, cur = ordered[-1]
    prev_key, prev = ordered[-2]
    gained = [b for b in cur if b not in prev]
    lost = [b for b in prev if b not in cur]
    common = [b for b in prev if b in cur]
    rising = []
    falling = []
    for b in common:
        d = cur[b] - prev[b]
        if d > 0:
            rising.append({"brand": b, "from": prev[b], "to": cur[b], "delta": d})
        elif d < 0:
            falling.append({"brand": b, "from": prev[b], "to": cur[b], "delta": d})
    rising.sort(key=lambda x: -x["delta"])
    falling.sort(key=lambda x: x["delta"])

    return {
        "periods": [{"period": k, "brands": v} for k, v in ordered],
        "current_period": cur_key,
        "previous_period": prev_key,
        "gained": gained,
        "lost": lost,
        "rising": rising,
        "falling": falling,
        "note": "对比最近两个周期（每 7 天）的 AI 推荐品牌变化；rising/falling 为推荐次数变化",
    }


def keywords(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str | None = None,
    top_n: int = 20,
) -> list[dict]:
    """必备关键词：高频维度（正式+观察区）按提及数排序，供下次内容生产围绕。"""
    tenant = _resolve_tenant(tenant)
    m = matrix(company=company, days=days, source_type=source_type, tenant=tenant)
    out = []
    for d in m["dimensions"]:
        out.append({"keyword": d["dimension"], "mentions": d["total_mentions"], "band": d["band"]})
    for o in m["observation"]:
        out.append({"keyword": o["dimension"], "mentions": 1, "band": "watch"})
    return sorted(out, key=lambda k: -k["mentions"])[:top_n]


def perception(
    company: str | None = None,
    days: int | None = 30,
    source_type: str = "ai_answer",
    tenant: str | None = None,
) -> dict:
    """认知标签分布：扫最新 succeeded extraction 的 analysis_json.perception_tags。"""
    tenant = _resolve_tenant(tenant)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ev_ids = _succeeded_evidence_ids(since_dt, company, source_type, tenant)
    if not ev_ids:
        return {"company": company, "tags": [], "self_tags": [], "evidence_count": 0}

    init_db()
    with SessionLocal() as db:
        rows = (
            db.query(GeoExtraction)
            .filter(GeoExtraction.evidence_id.in_(ev_ids), GeoExtraction.status == "succeeded")
            .all()
        )

    tag_count: dict[str, int] = {}
    self_tag_count: dict[str, int] = {}
    tag_quotes: dict[str, list] = {}
    for r in rows:
        try:
            aj = repo._row_to_dict(r).get("analysis_json") or {}
        except Exception:  # noqa: BLE001
            continue
        for b in aj.get("brands") or []:
            for t in b.get("perception_tags") or []:
                t = str(t).strip()
                if not t:
                    continue
                tag_count[t] = tag_count.get(t, 0) + 1
                tag_quotes.setdefault(t, []).append(b.get("name", ""))
        sb = aj.get("self_brand") or {}
        for t in sb.get("perception_tags") or []:
            t = str(t).strip()
            if not t:
                continue
            self_tag_count[t] = self_tag_count.get(t, 0) + 1

    tags = [
        {"tag": t, "count": c, "subjects": list(dict.fromkeys(tag_quotes.get(t, [])))[:5]}
        for t, c in sorted(tag_count.items(), key=lambda kv: -kv[1])
    ]
    self_tags = [
        {"tag": t, "count": c} for t, c in sorted(self_tag_count.items(), key=lambda kv: -kv[1])
    ]
    return {
        "company": company,
        "source_type": source_type,
        "days": days,
        "evidence_count": len(ev_ids),
        "tags": tags,
        "self_tags": self_tags,
    }
