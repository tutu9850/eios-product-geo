"""从 GEO 自己的内容资产里找「这家企业在卖什么」（**纯规则，不调模型**）。

为什么要单独一个模块：之前产品候选完全依赖模型读摘录，模型给什么就是什么（实测把
素材标题、设计风格词都当成产品）。Owner 2026-09-22：「我要能找到产品的算法」。

算法（确定性、可复现、不依赖模型）：

1. **引号里的名字优先**：`畅销产品为「琥珀沙发」`、产品名称「XX」这类句子里，
   引号内容天然是「被命名过的东西」，只要附近有产品/系列/型号/主打这类词就收，
   权重最高（×4）。
2. **按产品尾巴切词**：正文里凡是出现「沙发 / 床 / 柜 / 系列 / 版 / 系统 / 服务 / 课程」
   这类尾巴，就往前吃连续的名字字（最多 6 个）当候选前缀，拼出 `琥珀沙发`、`全案定制`。
   前缀要过**同一套**取词噪声检查（虚词、量词开头、句子碎片）。
3. **计分**：标题里出现过 ×3（用户自己给这份材料定的名，指向性最强），引号内 ×4，
   正文出现次数 +1/次。
4. **过滤**：只在正文出现 1 次的候选必须另有证据（标题命中 / 引号命中）；设计风格词
   （见 ``looks_like_style_word``）一律不算产品。

5. **产品和服务的分界只看尾巴**（Owner 2026-09-22）：以「服务 / 课程」收尾的是**服务**，
   其余是产品。第一版把「服务」也当成产品尾巴，结果「设计服务」被摆进「产品」那一行 ——
   页面上一眼就是错的。这里不猜语义，只认尾巴，两边喂给模型的池子分开。

它**不写库、不调模型、不碰知识库**，只读传入的材料列表；输出按分数排序的候选名，
供 detect 当规则兜底、也当提示词的参考池。
"""
from __future__ import annotations

import re
from typing import Any

from services.company_identity import _STRIP_CHARS, _prefix_is_noise, _word_char

#: 产品/服务尾巴（**长尾巴排前面**，先匹配更具体的）。
_PRODUCT_TAILS = (
    "背景墙", "榻榻米", "护墙板", "床垫", "窗帘", "地板", "瓷砖", "浴室柜", "餐边柜",
    "沙发", "衣柜", "橱柜", "书柜", "酒柜", "吊顶",
    "系列", "套装", "套餐", "型号", "系统", "平台", "软件", "方案",
    "床", "柜", "桌", "椅", "几", "门", "窗", "灯", "版",
)
#: 服务/课程尾巴：这些是「能干的一件活儿」，不是摆在店里的一件货。切词口径与产品相同，
#: 只是归行不同 —— 以这些收尾的名字进「服务」那一行。
_SERVICE_TAILS = ("服务", "课程")
#: 切词用的全部尾巴（产品 + 服务）；产品/服务怎么分见 ``is_service_name``。
_ALL_TAILS = _PRODUCT_TAILS + _SERVICE_TAILS
#: 前缀里出现这些词 = 不是在命名一个产品（「以上系统」「相关服务」）。
_PRODUCT_PREFIX_NOISE = (
    "以上", "以下", "这些", "那些", "其他", "相关", "各种", "多项", "所有", "部分",
    "主要", "全部", "每个", "一个", "这个", "那个", "什么", "任何",
)
#: 引号里的名字要算产品，**紧挨着**必须有这些「命名动作」词之一。
#: 不能只按「附近出现过品牌/服务」判定 —— 那会把「品牌溢价」「横空出世」这类
#: 被引号括起来的普通短语也收进来（实测过）。
_PRODUCT_CONTEXT_WORDS = ("产品", "系列", "型号", "名称", "主打", "畅销", "推出", "叫做", "叫")
#: 设计风格/调性词不是产品（「意式极简」「奶油风」）——只在没有产品尾巴时命中。
_STYLE_WORDS = ("极简", "轻奢", "法式", "中式", "简约", "中古", "奶油风", "侘寂", "北欧", "日式", "美式", "意式")
#: 以这些收尾说明它是一个「东西」（「奶油风沙发」是产品），不是光秃秃的风格词。
_PRODUCT_LIKE_TAILS = _ALL_TAILS + ("包", "机", "仪", "锅", "壶", "垫")

#: 「命名动作词 + 最多 6 个字的修饰 + 引号名」——只有这种紧邻结构才算命名。
_QUOTE_RE = re.compile(
    r"(?:产品|系列|型号|名称|主打|畅销|推出|叫做|叫)[^。！？，,\n]{0,6}[「『“\"]([^」』”\"]{2,12})[」』”\"]"
)
#: 引号名里出现这些字符 = 是句子/说明，不是名字。
_QUOTE_NAME_OK = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·\-+ ]+$")
_ALL_TAILS_DESC = tuple(sorted(_ALL_TAILS, key=len, reverse=True))


def is_service_name(name: str) -> bool:
    """名字以「服务 / 课程」收尾 = 它是服务，不是产品。

    只看尾巴，不做语义判断 —— 「琥珀沙发服务」这种也确实是在卖服务。
    """
    return str(name or "").strip().endswith(_SERVICE_TAILS)


def looks_like_style_word(name: str) -> bool:
    """「意式极简」「奶油风」这类风格词不该出现在产品那一行。"""
    if name.endswith(_PRODUCT_LIKE_TAILS):
        return False
    return name.endswith("风") or any(w in name for w in _STYLE_WORDS)


#: 以这些字开头 = 在说动作/语气，不是在命名产品（「卖价值」「嗯各部门」）。
_VERB_OR_FILLER_START = set("嗯啊哦呃唉买卖做用是想让把给对从能会要搞弄")


def _score_prefix_noise(prefix: str) -> bool:
    if prefix and prefix[0] in _VERB_OR_FILLER_START:
        return True
    return _prefix_is_noise(prefix) or any(w in prefix for w in _PRODUCT_PREFIX_NOISE)


def _tail_candidates(text: str) -> list[str]:
    """按产品尾巴在正文里切候选（同一次出现只给一个候选：能取最长就不退而取短的）。"""
    out: list[str] = []
    raw = str(text or "")
    for tail in _ALL_TAILS_DESC:
        start = 0
        while True:
            i = raw.find(tail, start)
            if i < 0:
                break
            start = i + len(tail)
            run_start = i
            while run_start > 0 and _word_char(raw[run_start - 1]) and (i - run_start) < 8:
                run_start -= 1
            for take in (6, 4, 2):
                left = max(run_start, i - take)
                prefix = raw[left:i].strip(_STRIP_CHARS)
                if len(prefix) < 2 or _score_prefix_noise(prefix):
                    continue
                name = (prefix + tail).strip(_STRIP_CHARS)
                if 3 <= len(name) <= 16 and name not in out:
                    out.append(name)
                break  # 一次出现只取最长的那个前缀
    return out


def _quoted_candidates(text: str) -> list[str]:
    """引号内 + 附近有产品语境词 → 强候选（「畅销产品为『琥珀沙发』」）。"""
    raw = str(text or "")
    out: list[str] = []
    for m in _QUOTE_RE.finditer(raw):
        name = m.group(1).strip(_STRIP_CHARS)
        if len(name) < 2 or len(name) > 12:
            continue
        if not _QUOTE_NAME_OK.match(name):
            continue
        if any(w in name for w in _PRODUCT_PREFIX_NOISE):
            continue
        if name[0] in _VERB_OR_FILLER_START:
            continue
        if name not in out:
            out.append(name)
    return out


def _ranked_candidates(materials: list[dict[str, Any]]) -> list[str]:
    """从内容资产里按规则切出产品 + 服务候选，按证据强度排序（不做产品/服务分家）。

    证据要求（防「正文里碰巧凑出来的四个字」）：全文出现 ≥2 次，或上过标题，
    或出现在引号里。分数再低于 2.0 的不要 —— 只有一次正文命中的弱证据不够。
    """
    score: dict[str, float] = {}
    evidence: set[str] = set()
    corpus_parts: list[str] = []
    for material in materials or []:
        title = str(material.get("title") or "")
        body = str(material.get("content") or "")[:8000]
        corpus_parts.append(title + "\n" + body)
        from_body = set(_tail_candidates(body))
        from_title = set(_tail_candidates(title))
        quoted = set(_quoted_candidates(body)) | set(_quoted_candidates(title))
        for name in from_body:
            score[name] = score.get(name, 0.0) + 1.0
        for name in from_title:
            score[name] = score.get(name, 0.0) + 3.0
            evidence.add(name)
        for name in quoted:
            score[name] = score.get(name, 0.0) + 4.0
            evidence.add(name)
    corpus = "\n".join(corpus_parts)
    hits = {name: corpus.count(name) for name in score}

    kept = {
        name: value + hits.get(name, 0)
        for name, value in score.items()
        if not looks_like_style_word(name) and (hits.get(name, 0) >= 2 or name in evidence)
    }
    ranked = sorted(kept.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    names = [name for name, _ in ranked]
    # 后缀收敛：同一次取词产生的短后缀不重复上桌（只有长的分不低时才收敛）
    kept_names: list[str] = []
    for name in names:
        if any(
            other != name
            and other.endswith(name)
            and len(other) > len(name)
            and kept.get(other, 0.0) >= kept.get(name, 0.0)
            for other in names
        ):
            continue
        kept_names.append(name)
    return kept_names


def product_candidates_from_materials(materials: list[dict[str, Any]], *, limit: int = 30) -> list[str]:
    """内容资产里的**产品**候选（尾巴不是「服务 / 课程」）。"""
    return [n for n in _ranked_candidates(materials) if not is_service_name(n)][:limit]


def service_candidates_from_materials(materials: list[dict[str, Any]], *, limit: int = 30) -> list[str]:
    """内容资产里的**服务**候选（尾巴是「服务 / 课程」）—— 与产品同一套证据规则。"""
    return [n for n in _ranked_candidates(materials) if is_service_name(n)][:limit]
