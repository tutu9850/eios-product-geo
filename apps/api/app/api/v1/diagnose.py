"""官网诊断（P2：为什么 AI 不推荐你）

抓取官网页面 → 检查 Schema 结构化数据 / Title+Meta / 内容结构 / 内容深度 / 品牌提及 / FAQ 结构
→ 逐项评分（0-100）+ 改进建议。

参考：GEORank diagnostics 思路（评分+建议），实现为轻量版（单页抓取，不做全站爬虫）。
"""
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.envelope import ok, err

router = APIRouter(prefix="/api/v1/diagnose")

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_WEIGHT = {
    "schema": 20,
    "meta": 15,
    "structure": 20,
    "depth": 15,
    "brand": 10,
    "faq": 10,
    "accessibility": 10,
}


def _parse_schema(soup: BeautifulSoup) -> list[str]:
    """提取页面里的 Schema 类型（JSON-LD 优先，Microdata 兜底）"""
    types: list[str] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        text = script.get_text()
        for t in re.findall(r'"@type"\s*:\s*"?([^",}]+)"?', text):
            types.append(t.strip())
        for t in re.findall(r'"@type"\s*:\s*\[([^\]]+)\]', text):
            for item in t.split(","):
                types.append(item.strip().strip('"'))
    for tag in soup.find_all(attrs={"itemtype": True}):
        types.append(tag.get("itemtype", "").split("/")[-1].lower())
    return list(dict.fromkeys(types))


def _diag_schema(types: list[str]) -> tuple[int, str]:
    score = 0
    notes = []
    if types:
        score += 12
        notes.append(f"检测到结构化数据：{', '.join(types[:5])}")
        good = [t for t in types if t.lower() in ("organization", "product", "service", "faqpage", "article", "localbusiness")]
        if good:
            score += 8
            notes.append(f"含高价值类型（Organization/Product/FAQPage 等）：{', '.join(good[:3])}")
        else:
            notes.append("建议补充 Organization/Product/FAQPage 等类型（AI 更容易识别企业信息）")
    else:
        notes.append("未检测到 Schema.org 结构化数据——AI 引擎无法明确识别企业身份、产品和服务")
    return score, "；".join(notes)


def _diag_meta(soup: BeautifulSoup) -> tuple[int, str]:
    score = 0
    notes = []
    title = soup.title.get_text(strip=True) if soup.title else ""
    desc = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        desc = meta_desc.get("content", "").strip()
    if title:
        if 20 <= len(title) <= 60:
            score += 8
            notes.append(f"Title 长度合适（{len(title)} 字符）")
        else:
            score += 4
            notes.append(f"Title 长度 {len(title)} 字符（建议 20-60 字符，含关键词）")
    else:
        notes.append("缺少 <title>——每页必须有标题")
    if desc:
        if 80 <= len(desc) <= 200:
            score += 7
            notes.append(f"Meta Description 长度合适（{len(desc)} 字符）")
        else:
            score += 3
            notes.append(f"Meta Description {len(desc)} 字符（建议 80-200 字符，含关键词与行动号召）")
    else:
        notes.append("缺少 Meta Description——AI 摘要常直接引用它")
    return score, "；".join(notes)


def _diag_structure(soup: BeautifulSoup) -> tuple[int, str]:
    score = 0
    notes = []
    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")
    if len(h1s) == 1:
        score += 7
        notes.append("H1 数量合适（1 个，主题明确）")
    elif len(h1s) == 0:
        notes.append("缺少 H1 标题——AI 不知道页面主题")
    else:
        score += 3
        notes.append(f"H1 有 {len(h1s)} 个（建议只留 1 个主标题）")
    h_count = len(h2s) + len(h3s)
    if h_count >= 6:
        score += 8
        notes.append(f"小标题层级良好（H2×{len(h2s)} + H3×{len(h3s)}）")
    elif h_count >= 3:
        score += 5
        notes.append(f"小标题层级一般（H2×{len(h2s)} + H3×{len(h3s)}，建议 ≥6 个）")
    else:
        notes.append(f"小标题太少（H2×{len(h2s)} + H3×{len(h3s)}）——长文需分段并加小标题")
    if score < 5:
        score += 5 if h1s else 0
    return min(score, 20), "；".join(notes)


def _diag_depth(soup: BeautifulSoup) -> tuple[int, str]:
    text = soup.get_text(" ", strip=True)
    words = len(re.sub(r"\s+", "", text))
    p_count = len(soup.find_all("p"))
    if words >= 1500:
        score = 15
        note = f"正文内容丰富（约 {words} 字）"
    elif words >= 800:
        score = 10
        note = f"正文中等（约 {words} 字，建议 ≥1500 字）"
    elif words >= 300:
        score = 5
        note = f"正文偏少（约 {words} 字）——AI 引用需要足够信息量"
    else:
        score = 2
        note = f"正文极少（约 {words} 字）——几乎是空页"
    return score, f"{note}；段落 {p_count} 个"


def _diag_brand(soup: BeautifulSoup, url: str) -> tuple[int, str]:
    domain = urlparse(url).netloc.replace("www.", "")
    text = soup.get_text(" ", strip=True)
    brand_hint = domain.split(".")[0]
    count = text.count(brand_hint) if brand_hint else 0
    title = soup.title.get_text(strip=True) if soup.title else ""
    if count >= 5:
        return 10, f"品牌/域名出现 {count} 次——AI 能明确识别主体"
    if count >= 2:
        return 6, f"品牌/域名出现 {count} 次（建议 ≥5 次，标题和首段最好带上）"
    if brand_hint and brand_hint in title:
        return 5, f"品牌名只在 Title 出现——正文需自然提及（企业名/产品名）"
    return 2, "页面几乎不出现品牌名/域名——AI 不知道这是谁的内容"


def _diag_faq(soup: BeautifulSoup, types: list[str]) -> tuple[int, str]:
    score = 0
    notes = []
    if "FAQPage" in [t.upper() for t in types]:
        score += 7
        notes.append("含 FAQPage Schema——AI 可直接引用问答")
    questions = [
        tag.get_text(strip=True)
        for tag in soup.find_all(["h2", "h3", "h4"])
        if re.search(r"[？?]$", tag.get_text(strip=True))
    ]
    if len(questions) >= 3:
        score += 3
        notes.append(f"检测到 {len(questions)} 个问句式小标题（FAQ 内容模式）")
    elif not types and not questions:
        notes.append("无 FAQ 结构——建议加 FAQ 板块（AI 摘要最常引用问答）")
    return score, "；".join(notes) if notes else "无 FAQ 相关内容"


async def _fetch(url: str) -> tuple[str | None, str]:
    """抓取页面 HTML。返回 (html, 错误信息)"""
    try:
        async with httpx.AsyncClient(
            timeout=12, follow_redirects=True, trust_env=False, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None, f"页面返回 HTTP {r.status_code}（可能被反爬或不存在）"
            if len(r.text) < 200:
                return None, "页面内容过少（可能是验证码页或空页）"
            return r.text, ""
    except Exception as e:  # noqa: BLE001
        return None, f"抓取失败：{e}"


class DiagnoseIn(BaseModel):
    url: str


@router.post("")
async def diagnose(payload: DiagnoseIn):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    html, fetch_err = await _fetch(url)
    if fetch_err:
        return ok(
            {
                "url": url,
                "fetchable": False,
                "error": fetch_err,
                "score": 0,
                "checks": [],
                "suggestions": [f"页面无法访问：{fetch_err}。请确认官网可正常访问（AI 爬虫才能抓取）。"],
            }
        )

    soup = BeautifulSoup(html, "html.parser")
    types = _parse_schema(soup)

    checks = []
    total = 0
    for key, fn, weight in [
        ("schema", _diag_schema, _WEIGHT["schema"]),
        ("meta", _diag_meta, _WEIGHT["meta"]),
        ("structure", _diag_structure, _WEIGHT["structure"]),
        ("depth", _diag_depth, _WEIGHT["depth"]),
        ("brand", lambda s, u: _diag_brand(s, u), _WEIGHT["brand"]),
        ("faq", lambda s, u: _diag_faq(s, types), _WEIGHT["faq"]),
        ("accessibility", lambda s, u: (10, "页面可正常访问（HTTP 200 + 完整 HTML）"), _WEIGHT["accessibility"]),
    ]:
        if key in ("brand", "accessibility"):
            score, note = fn(soup, url)
        elif key == "faq":
            score, note = fn(soup, types)
        elif key == "schema":
            score, note = fn(types)
        else:
            score, note = fn(soup)
        total += score
        checks.append({"key": key, "score": score, "max": weight, "note": note})

    # 建议：低于 50% 的项 + Top 提示
    suggestions = []
    for c in checks:
        if c["score"] < c["max"] * 0.5:
            suggestions.append(c["note"])
    if len(suggestions) > 3:
        suggestions = suggestions[:3]

    return ok(
        {
            "url": url,
            "fetchable": True,
            "score": min(total, 100),
            "checks": checks,
            "suggestions": suggestions,
            "schema_types": types,
        }
    )
