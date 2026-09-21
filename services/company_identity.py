"""「本公司是谁」的唯一解析入口（**只读**）。

为什么要有它：内容生成 / 内容评分 / 企业画像 / 内容机会 各自猜过一遍公司名，四次实现
规则还不一样。最松的那个（``services.content._auto_company``）只要名字里带「企业」就认，
实测把知识库里的**素材标题**「企业AI获客入口改造」当成了公司名 —— 生成出来的内容张冠李戴，
评分还把这条错名字当成「画像已解析」。这里把来源按可信度排一次，其余调用方只读这一个结果。

三个来源，全部已经存在，**不新建 Authority / 不建第二套 Store / 只读知识库**：

1. ``profile``：用户点选确认过的知识库初始化档案（``kb-init`` 扫 → 人点选 → 落
   ``geo_knowledge_snapshots``）。这是 Owner 2026-09-21 拍板的那条路，最可信。
2. ``monitor_item``：用户建监测对象时确认过的 brand 对象（company + 别名）。
3. ``knowledge_scan``：知识库对象名单里按公司名特征严格扫出来的（纯规则，不调模型）。
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


def looks_like_company_name(name: str) -> bool:
    """名字像不像一家公司（纯规则）。"""
    n = str(name or "").strip()
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


async def _from_knowledge_scan() -> str | None:
    """知识库对象名单里按公司名特征扫一遍（纯规则，不调模型）。

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

    ``source`` 如实写清这一条是从哪来的（``profile`` / ``monitor_item`` / ``knowledge_scan`` /
    ``unresolved``）——界面与日志据此说明「这个公司名是谁定的」，不编。
    """
    name, aliases = _from_profile()
    if name:
        return {"name": name, "aliases": aliases, "source": "profile"}
    name, aliases = _from_monitor_item()
    if name:
        return {"name": name, "aliases": aliases, "source": "monitor_item"}
    name = await _from_knowledge_scan()
    if name:
        return {"name": name, "aliases": [], "source": "knowledge_scan"}
    return {"name": None, "aliases": [], "source": "unresolved"}
