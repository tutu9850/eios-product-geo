"""Conservative draft warnings; this is not a fact certification or a Fact write."""
import re

# Surface-name screening only; these are not semantic entities or Knowledge facts.
_REGIONS = re.compile("|".join("北京 天津 上海 重庆 河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 海南 四川 贵州 云南 陕西 甘肃 青海 台湾 内蒙古 广西 西藏 宁夏 新疆 香港 澳门 成都 深圳 广州 杭州 南京 武汉 西安 苏州 厦门 青岛 大连".split()))


def source_text(sources: list[dict]) -> str:
    parts = []
    for group in sources:
        for item in group.get("items") or []:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or item.get("fact") or item.get("chunk") or ""))
    return "\n".join(parts)


def check_claims(content: str, sources: list[dict]) -> dict:
    """Flag unsupported numeric tokens and sensitive claims for human review.

    A matching number is only a screening signal: it does not prove the subject,
    predicate, date or promised conditions. The UI must never claim full verification.
    """
    evidence = source_text(sources)
    normalize = lambda value: re.sub(r"[\s,，]", "", value).replace("–", "-").replace("—", "-")
    evidence_numbers = {normalize(m.group()) for m in re.finditer(r"\d+(?:[.,]\d+)*(?:\s*[-–—~至]\s*\d+(?:\.\d+)*)?", evidence)}
    flags = []
    seen = set()
    for line in content.splitlines():
        # List numbering is structure, not a business quantity.
        line = re.sub(r"^[\s#*]*(?:[Qq问]\s*\d+\s*[:：.、]|\d+[.、)）])\s*", "", line)
        for sentence in re.split(r"(?<=[。！？；])", line):
            if not sentence.strip():
                continue
            unsupported = [m.group() for m in re.finditer(r"\d+(?:[.,]\d+)*(?:\s*[-–—~至]\s*\d+(?:\.\d+)*)?", sentence)
                           if normalize(m.group()) not in evidence_numbers]
            sensitive = re.search(r"(?:认证|资质|专利|获奖|客户包括|服务过|合作客户|成功案例|保证|承诺)", sentence)
            regions = [m.group() for m in _REGIONS.finditer(sentence) if m.group() not in evidence]
            reason = "本次资料选段未找到这些数字：" + "、".join(unsupported) if unsupported else ""
            if regions:
                reason += ("；" if reason else "") + "本次资料选段未找到这些地域：" + "、".join(dict.fromkeys(regions))
            if sensitive and normalize(sentence.strip()) not in normalize(evidence):
                reason += ("；" if reason else "") + "涉及客户、资质或承诺，请逐项对照原文核验"
            if re.search(r"(?:旗下|隶属|拥有.{0,20}品牌)", sentence):
                reason += ("；" if reason else "") + "涉及品牌归属，请核对主语和原文，不要把品牌与所属企业混写"
            if reason and sentence.strip() not in seen:
                seen.add(sentence.strip())
                flags.append({"kind": "unsupported_number" if unsupported else "sensitive_claim", "claim": sentence.strip()[:400], "reason": reason})
    return {"status": "review_required" if flags else "no_flags", "flags": flags[:30],
            "notice": "这是有限的文字筛查，未提示也不代表全文正确；发布前仍需人工核对原文。"}
