"""「本公司是谁」的唯一解析入口（**只读**）。

为什么要有它：内容生成 / 内容评分 / 企业画像 / 内容机会 各自猜过一遍公司名，四次实现
规则还不一样。最松的那个（``services.content._auto_company``）只要名字里带「企业」就认，
实测把知识库里的**素材标题**「企业AI获客入口改造」当成了公司名 —— 生成出来的内容张冠李戴，
评分还把这条错名字当成「画像已解析」。这里把来源按可信度排一次，其余调用方只读这一个结果。

三个来源，全部已经存在，**不新建 Authority / 不建第二套 Store / 只读知识库**：

1. ``profile``：用户点选确认过的知识库初始化档案（``kb-init`` 扫 → 人点选 → 落
   ``geo_knowledge_snapshots``）。这是 Owner 2026-09-21 拍板的那条路，最可信。
2. ``monitor_item``：用户建监测对象时确认过的 brand 对象（company + 别名）。
3. ``own_materials``：GEO 自己的**内容资产**里按公司名特征猜出来的（Owner 2026-09-22：
   「根据这里面的信息去猜公司，这里就不严格了，基本上也是针对性比较强的公司内容」）。
   这一档故意比知识库那档松：素材是用户自己上传的公司资料/文章，指向性强，按出现频次取第一名。
4. ``knowledge_scan``：GEO 自己柜里的知识库快照里按公司名特征严格扫出来的（纯规则，不调模型）。
   找不到就**返回 None**，让上游如实说「未识别到企业名称」，而不是拿一个像标题的名字顶上。
"""
from __future__ import annotations

from typing import Any

#: 名字里出现这些词就不是公司名（知识库里这类对象很多是文档/素材/流程标题）。
_TITLE_WORDS = (
    "改造", "入口", "方案", "计划", "流程", "制度", "清单", "模板", "白皮书", "目录",
    "报告", "诊断", "官网", "预算", "会议", "通知", "培训", "话术", "报价单", "知识库",
    "系统", "平台", "服务包", "套餐", "案例集", "操作手册", "指南", "手册", "规范",
)
#: 组织单元/岗位/场地 —— 也是「名字里带公司味但不是一家公司」的重灾区
#: （实测名单里有「会销中心」「销售中心」「陈礼 负责人 销售中心」「成都演示间 负责 StoryClaw终端」）。
_UNIT_WORDS = (
    "中心", "部门", "负责", "展厅", "演示间", "样板间", "门店", "分店", "团队", "小组",
    "负责人", "岗位", "分部", "办事处",
)
#: 公司名尾巴（只有这几个够硬；「中心/厂」不算 —— 那些更常是内部单元）。
_COMPANY_SUFFIX = ("有限公司", "有限责任公司", "股份有限公司", "集团", "工作室", "事务所")
#: 没有尾巴时只认这些行业词 + 短名（实测名单里唯一命中的就是「亚宇臻隆科技」）。
_MID_WORDS = ("科技", "软件", "网络", "信息", "数据", "智能", "电子", "通信", "生物", "医药")
_MID_MAX_LEN = 15
#: 名字长度上限：再长就不是公司名了（句子/标题）。
_MAX_LEN = 20

# 自动识别里最危险的一类误报：材料中的提问/模板词被当成企业名。
# 这些词不能进入“本公司是谁”的任何下游，否则会把整套监测绑定到一个不存在的主体。
_PLACEHOLDER_COMPANY_NAMES = {
    "品牌", "品牌名", "品牌名称", "企业", "企业名", "企业名称", "公司名", "公司名称",
    "哪个品牌", "什么品牌", "某个品牌", "目标品牌", "当前品牌", "本品牌", "我方品牌", "自有品牌",
    "哪个企业", "哪个公司", "哪家公司", "我们的公司", "你的公司", "你们公司",
}


def is_placeholder_company_name(name: str) -> bool:
    """Return whether ``name`` is a template/question phrase rather than an identity.

    This is intentionally conservative.  We only reject exact generic phrases and a few
    question-shaped ``*品牌`` variants; real company names remain evidence-driven.
    """
    n = "".join(str(name or "").split()).strip("：:，,。.!！?？/\\")
    if not n:
        return True
    if n in _PLACEHOLDER_COMPANY_NAMES:
        return True
    if n.endswith("品牌") and any(token in n for token in ("哪个", "什么", "哪家", "哪些", "某个", "目标", "当前", "本", "我方", "自有", "你的", "你们")):
        return True
    return False


def looks_like_company_name(name: str) -> bool:
    """名字像不像一家公司（纯规则）。"""
    n = str(name or "").strip()
    if is_placeholder_company_name(n):
        return False
    if not n or len(n) > _MAX_LEN:
        return False
    if any(w in n for w in _TITLE_WORDS) or any(w in n for w in _UNIT_WORDS):
        return False
    if any(n.endswith(s) for s in _COMPANY_SUFFIX):
        return True
    return bool(any(w in n for w in _MID_WORDS)) and len(n) <= _MID_MAX_LEN


def _from_profile() -> tuple[str | None, list[str]]:
    """用户点选确认过的知识库初始化档案（kb-init）。没人点过就是空。"""
    try:
        from app.api.v1.kb_init import PROFILE_KIND
        from app.services import knowledge_snapshot

        rows = knowledge_snapshot.list_recent(kind=PROFILE_KIND, limit=1)
        if not rows:
            return None, []
        companies = [str(x).strip() for x in ((rows[0].get("payload") or {}).get("companies") or [])]
        companies = [c for c in companies if c]
        return (companies[0], companies[1:]) if companies else (None, [])
    except Exception:  # noqa: BLE001 — 读档案失败不等于「没有公司」，交给下一档
        return None, []


def _from_monitor_item() -> tuple[str | None, list[str]]:
    """用户建过的 brand 监测对象（公司名 + 别名）——建对象时是人确认过的。"""
    try:
        from app.services.store import get_store

        for item in get_store().load("monitor_items"):
            if item.get("type") != "brand" or item.get("status") != "active":
                continue
            cfg = item.get("config_json") or {}
            name = str(cfg.get("company") or "").strip()
            if not name:
                continue
            aliases = [str(a).strip() for a in (cfg.get("aliases") or []) if str(a).strip()]
            return name, aliases
    except Exception:  # noqa: BLE001
        pass
    return None, []


#: 从用户自己的素材里认公司名时用的「品牌尾巴」（比知识库那档松 —— 素材是自家资料）。
_BRAND_TAIL = (
    "有限公司", "有限责任公司", "股份有限公司", "集团", "工作室", "事务所", "公司",
    "科技", "家居", "家装", "装饰", "设计", "建材", "家具", "橱柜", "电器", "软装",
    "传媒", "文化", "教育", "网络", "信息", "智能", "实业", "商贸", "品牌", "研究院",
)
#: 猜出来的名字最长多少字（再长就多半是句子/标题，不是公司名）。
_MATERIAL_MAX_LEN = 16
_STRIP_CHARS = " \t\u3000《》〈〉【】()（）[]［］「」“”\"'·—-_/,，。;；:：!！?？\n\r"
#: 名字**前缀**里出现这些字，多半是「往前吃字」吃进了句子，不是公司名。
#: 只放虚词/连接词/动词 —— 不放「华为」的「为」、「全友」的「有」这类**真名字里会有**的字。
_PREFIX_NOISE_CHARS = set(
    "的了是在和与这那其并及或把被对从到都也就才又还只很更而之该我你他它们些做"
    "为属已认超归暂确"
)
#: 前缀里的动词/修饰短语（整词判，比单字准）。实测这批把「主要来自过往家具」
#: 「优先选择上市公司」「全面梳理比格家居」「阐述笔革家居」这类句子片段挡在候选池外。
_PREFIX_NOISE_WORDS = (
    "提供", "以及", "面向", "旗下", "是一家", "可以", "就是", "作为", "通过", "公司是", "其中", "做的",
    "来自", "主要", "优先", "选择", "上市", "全面", "梳理", "阐述", "坚信", "传统", "属于", "归属",
    "确认", "暂无", "类似", "定位", "儿童房", "高净值", "服务于", "超越", "奢侈", "文化革命",
    "哪个", "什么", "哪家", "哪些",
)
#: 前缀以量词/序数开头 = 在说「三大/五个/两类…」，不是名字。
_QUANTIFIER_START = ("一", "二", "两", "三", "四", "五", "六", "七", "八", "九", "十", "几", "多", "各", "全")
#: 前缀里最多几个汉字：再长就是「往前多吃了几口」的句子片段（实测 6 字前缀全是垃圾）。
_PREFIX_MAX_CJK = 4


def _word_char(ch: str) -> bool:
    """这算不算「名字里的字」（汉字/字母/数字/·）——用来在长句里切出名字。"""
    return ch.isalnum() or ch == "·"


def _prefix_is_noise(prefix: str) -> bool:
    if not prefix:
        return True
    if any(ch in _PREFIX_NOISE_CHARS for ch in prefix):
        return True
    if any(w in prefix for w in _PREFIX_NOISE_WORDS):
        return True
    if prefix[0] in _QUANTIFIER_START:
        return True
    cjk = [c for c in prefix if "\u4e00" <= c <= "\u9fff"]
    # 纯汉字前缀超过 4 字 = 多半是把句子当名字吃进来了；带字母的（BG/ANKE）只看汉字数。
    return len(cjk) > _PREFIX_MAX_CJK


#: 通用业务词 + 公司尾巴 = 行业泛称，不是公司名（「家装公司」「定制公司」「AI获客公司」）。
_GENERIC_PREFIX = {
    "家装", "家居", "定制", "全屋定制", "获客", "AI", "AI获客", "科技", "网络", "信息", "智能",
    "传媒", "文化", "营销", "服务", "品牌", "设计", "装饰", "建材", "家装设计", "软件",
}
#: 公司类尾巴（这些尾巴前面如果是泛称，就一定是行业泛称）
_COMPANY_TAIL_WORDS = ("公司", "有限公司", "有限责任公司", "股份有限公司", "集团", "工作室", "事务所", "研究院")


def _is_generic_name(name: str) -> bool:
    for tail in _COMPANY_TAIL_WORDS:
        if name.endswith(tail) and len(name) > len(tail):
            return name[: -len(tail)].strip() in _GENERIC_PREFIX
    return False


def _candidate_names(text: str) -> list[str]:
    """在一段文本里按「品牌尾巴」找出可能的公司/品牌名（纯规则，不调模型）。

    做法：找到每个尾巴词的位置，往前一路吃「名字字」（最多 6 个，够到「成都笔革家居」这种），
    得到一个候选串，再用知识库那档同一套排除词（标题词 / 组织单元词）+ 前缀虚词过一遍。
    同一次出现只给一个候选，不做「各种长度都试一遍」—— 那会把「案笔革家居」这种残片也塞进来。
    """
    out: list[str] = []
    raw = str(text or "")
    for tail in _BRAND_TAIL:
        start = 0
        while True:
            i = raw.find(tail, start)
            if i < 0:
                break
            start = i + len(tail)
            # 前缀只在**连续名字字**这一段里取（不许跨过「。」「】」这类边界；
            # 否则「…公司。笔革家居…」会拼出「制公司。笔革家居」这种垃圾）。
            run_start = i
            while run_start > 0 and _word_char(raw[run_start - 1]) and (i - run_start) < 8:
                run_start -= 1
            for take in (6, 4, 2):
                left = max(run_start, i - take)
                prefix = raw[left:i].strip(_STRIP_CHARS)
                if len(prefix) < 2:
                    continue
                name = (prefix + tail).strip(_STRIP_CHARS)
                if len(name) < 3 or len(name) > _MATERIAL_MAX_LEN:
                    continue
                if _prefix_is_noise(prefix):
                    continue
                if _is_generic_name(name):
                    continue
                if any(w in name for w in _TITLE_WORDS) or any(w in name for w in _UNIT_WORDS):
                    continue
                if name.startswith(("http", "www")):
                    continue
                if name not in out:
                    out.append(name)
    return out


#: 光秃秃一个行业词 = 通用词，不是专名（「AI设计」这种带字母的也要挡）。
_BARE_CATEGORY_WORDS = {
    "设计", "品牌", "装饰", "软装", "家具", "家居", "家装", "教育", "文化", "传媒",
    "建材", "电器", "橱柜", "科技", "网络", "信息", "智能", "公司", "集团", "工作室",
}


def _looks_like_proper_noun(name: str) -> bool:
    """这像不像一个**专名**（品牌/公司），而不是「正文里碰巧凑出来的四个字」。

    为什么需要：法律上「XX家居」「XX设计」这种尾巴满篇都是，规则取词必然在正文里
    凑出「国际知名设计」「未来审美设计」「净值人群家居」这类片段 —— 它们**每份材料里
    只出现一次**，而真名字要么被用户写进标题、要么在多份材料里反复出现、要么带字母/数字
    （ANKE、BG、MK）。实测口径：标题命中 / ≥2 份材料出现 / 含字母或数字，三者占其一。
    """
    if any(("a" <= c.lower() <= "z") or c.isdigit() for c in name):
        # 带字母/数字基本就是品牌（ANKE、BG笔革艺术、MK玛珂家具）；
        # 但「字母 + 光秃秃一个行业词」除外 —— 那是「AI设计」这种通用词，不是名字。
        cjk = "".join(c for c in name if "\u4e00" <= c <= "\u9fff")
        return cjk not in _BARE_CATEGORY_WORDS
    return False


def company_candidates_from_materials(materials: list[dict[str, Any]]) -> list[str]:
    """从 GEO 自己的内容资产里猜公司/品牌名，按「出现得多 + 上过标题」排序。

    一条素材里同一个名字只算一次（不然正文里反复出现的品牌会把分数堆爆），
    标题里出现过 ×3 加权 —— 标题是用户自己给这份材料定的名字，指向性最强。

    2026-09-22 修（Owner：「为什么能有那么多公司呢」）：加两道闸 ——
    取词阶段挡掉句子片段（见 ``_prefix_is_noise``），排序前再要求候选是**专名**
    （标题命中 / 全文出现 ≥2 次 / 含字母数字）。只冒出来一次的纯汉字片段一律不进名单：
    那是正文里凑出来的字（「主要来自过往家具」「全面梳理比格家居」），不是谁的名字。
    """
    score: dict[str, float] = {}
    occurrences: dict[str, int] = {}
    title_hits: set[str] = set()
    for material in materials or []:
        title = str(material.get("title") or "")
        content = str(material.get("content") or "")
        for name in set(_candidate_names(title)):
            score[name] = score.get(name, 0.0) + 3.0
            title_hits.add(name)
        for name in set(_candidate_names(content[:4000])):
            score[name] = score.get(name, 0.0) + 1.0
        for name in set(_candidate_names(title)) | set(_candidate_names(content[:4000])):
            occurrences[name] = occurrences.get(name, 0) + title.count(name) + content.count(name)
    score = {
        name: value
        for name, value in score.items()
        if not is_placeholder_company_name(name)
        and (name in title_hits or occurrences.get(name, 0) >= 2 or _looks_like_proper_noun(name))
    }
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    # 后缀收敛：「臻隆科技」是「亚宇臻隆科技」的后缀、「有限公司」是「笔革家居有限公司」的后缀
    # —— 同一次出现产生的短后缀不算另一个公司，只留长的那个。
    #
    # 2026-09-22 修：原规则**只要**存在更长的后缀就把短的丢掉，方向反了 ——
    # 实测「笔革家居」（标题命中，4 分）被正文里的碎片「阐述笔革家居」（1 分）吃掉，
    # 「比格家居」被「全面梳理比格家居」「梳理比格家居」吃掉，于是一份 5 条的公司名单里
    # 好名字全没了、只剩碎片。现在只在**长的那个分不低**时才收敛。
    names = [name for name, _s in ranked]
    kept: list[str] = []
    for name in names:
        suppressed = any(
            other != name
            and other.endswith(name)
            and len(other) > len(name)
            and score.get(other, 0.0) >= score.get(name, 0.0)
            for other in names
        )
        if suppressed:
            continue
        kept.append(name)
    return kept[:20]


async def _from_own_materials() -> str | None:
    """从 GEO 自己的内容资产里猜「本公司」（Owner 2026-09-22）。

    Owner 原话：「根据这里面的信息去猜公司，这里就不严格了」。所以这里**不要求唯一候选**
    （知识库那档才要求）：按出现频次取第一名。一条都猜不出就返回 None —— 如实说没识别到，
    不拿标题硬顶。
    """
    try:
        from app.services.store import get_store

        names = company_candidates_from_materials(get_store().load("kb"))
    except Exception:  # noqa: BLE001 — 读自己的素材失败不放行去猜别的，如实没有
        return None
    return names[0] if names else None


async def _from_knowledge_scan() -> str | None:
    """GEO 柜里的知识库快照（同步带回来的那份）里按公司名特征扫一遍（纯规则，不调模型）。

    **只有唯一候选才算**：名单里出现两个像公司的名字（我方 + 客户/供应商）时，规则分不出
    哪个是「我们家」，这时候就该返回 None 让人去点选 —— 猜错会让后面所有内容张冠李戴。
    """
    try:
        from adapters.eios import get_entities

        matched = [
            str(e.get("canonical_name") or e.get("name") or "").strip()
            for e in await get_entities()
        ]
    except Exception:  # noqa: BLE001 — 知识库读不到就如实没有，不猜
        return None
    strong = [n for n in matched if looks_like_company_name(n)]
    return strong[0] if len(strong) == 1 else None


async def resolve_self_company(tenant_id: str | None = None) -> dict[str, Any]:  # noqa: ARG001 — 兼容调用方签名
    """解析「本公司」：返回 ``{name, aliases, source}``。

    ``source`` 如实写清这一条是从哪来的（``profile`` / ``monitor_item`` / ``own_materials`` /
    ``knowledge_scan`` / ``unresolved``）——界面与日志据此说明「这个公司名是谁定的」，不编。
    """
    name, aliases = _from_profile()
    if name:
        return {"name": name, "aliases": aliases, "source": "profile"}
    name, aliases = _from_monitor_item()
    if name:
        return {"name": name, "aliases": aliases, "source": "monitor_item"}
    name = await _from_own_materials()
    if name:
        return {"name": name, "aliases": [], "source": "own_materials"}
    name = await _from_knowledge_scan()
    if name:
        return {"name": name, "aliases": [], "source": "knowledge_scan"}
    return {"name": None, "aliases": [], "source": "unresolved"}
