"""Intelligence 分析引擎 — Prompt 模板（版本化：改 prompt 升 PROMPT_VERSION）"""

PROMPT_VERSION = "1.0"

EXTRACTOR_SYSTEM = """你是 EIOS 统一分析引擎的文本解析器。你的任务：把一条 AI 回答解析成结构化认知 JSON。
铁律：
1. evidence_quote 必须是原文原句（逐字截取，≤500 字），禁止改写、禁止编造。
2. 没有原话依据的 reason / trust / missing 一律不要输出。
3. 只分析"外界（AI）怎么说"，不评判事实真假。
4. 品牌名用回答里出现的原始称谓。
5. **brands 只提取【竞品/相关主体】名单内的品牌**（名单见 prompt 的【监测信息】）；名单为「无」时 brands 输出空数组，只填 self_brand。回答里顺带提到的其他品牌一律不提取。"""

EXTRACTOR_PROMPT = """解析下面这条 AI 回答，输出 JSON（schema_version 1.0）。

【监测信息】
- 问题：{question}
- 引擎：{engine}
- 监测主体（我方）：{subject_company}
- 竞品/相关主体：{competitors}（**brands 只提取此名单内的品牌；名单为「无」时 brands 输出空数组**）

【AI 回答原文】
{raw_text}

【输出 JSON 格式】（严格按此结构，不要多余字段）
{{
  "schema_version": "1.0",
  "evidence_id": "{evidence_id}",
  "source_type": "ai_answer",
  "intent": "recommendation | trust | comparison | awareness | other",
  "brands": [
    {{
      "name": "主体名",
      "recommended": true/false,
      "rank": 1,
      "reasons": [
        {{"factor": "维度词（如医疗/性价比/环境）", "weight": 0.9, "evidence_quote": "原文原句", "confidence": 0.8}}
      ],
      "trust_signals": [
        {{"signal": "信任信号", "evidence_quote": "原文原句"}}
      ],
      "perception_tags": ["认知标签"]
    }}
  ],
  "user_decision_factors": [
    {{"factor": "用户决策因素", "weight": 0.9, "evidence_quote": "原文原句"}}
  ],
  "self_brand": {{
    "name": "{subject_company}",
    "mentioned": true/false,
    "recommended": true/false,
    "perception_tags": [],
    "missing_reason": "若提到我方但没推荐，给原因（原文依据）；没提到则为空",
    "evidence_quote": "原文原句"
  }},
  "summary": "一句话摘要（≤80字）"
}}

只输出 JSON 本体，不要 markdown 代码块，不要任何解释。"""

REASONING_SYSTEM = """你是 EIOS 统一分析引擎的报告推理器。输入：近期 AI 回答的聚合摘要 + 企业知识库 active 事实摘要。
任务：产出周期认知报告 JSON。
铁律：
1. 每条 gap/action 必须带 support_refs（evidence_id）或原话 quote；无证据不写。
2. 禁止编造企业知识库中不存在的能力；知识库没有 → gap_type=capability_missing（建议补齐或放弃）。
3. 禁止无基线定量承诺（如"提升+18%"），只允许定性表述。
4. 差距矩阵以「AI 回答有没有提到」为准：AI 已提 ≥2 次的点不重复推。"""

REASONING_PROMPT = """生成 {company_name} 近 {days} 天认知报告 JSON（schema_version 1.0）。

【AI 回答聚合摘要】
{aggregate}

【企业知识库 active 事实摘要（企业真相，只读）】
{kernel_summary}

【输出 JSON】
{{
  "schema_version": "1.0",
  "source_scope": ["ai_answer"],
  "perception": {{"tags": [{{"tag": "...", "share": 0.7}}]}},
  "why_competitors_win": [
    {{"competitor": "...", "factors": [{{"factor": "...", "score": 0.9, "support_refs": ["ans_..."]}}]}}
  ],
  "capability_gap": {{
    "kernel_has": ["..."],
    "external_perceives": ["..."],
    "gap_summary": "...",
    "support_refs": ["ans_..."]
  }},
  "gap_matrix": [
    {{
      "dimension": "...",
      "gap_type": "capability_missing | capability_hidden | competitor_advantage | market_unknown",
      "competitor_mentions": 0,
      "self_mentions": 0,
      "kernel_has": true/false,
      "verdict": "🔴补 / 🟢已有 / 🟡空白 / 📌缺口",
      "support_refs": ["ans_..."]
    }}
  ],
  "actions": [
    {{
      "priority": 1,
      "task": "文章选题（可直接做标题）",
      "angle": "切入角度",
      "reason": "提升什么信号",
      "support_refs": ["ans_..."],
      "expected_effect": "定性描述"
    }}
  ],
  "knowledge_gaps": [
    {{"dimension": "...", "competitor": "...", "suggestion": "补齐或放弃", "support_refs": ["ans_..."]}}
  ],
  "diagnosis": "段落诊断（与 support_refs 一致）",
  "cognition_portrait": {{
    "summary": "市场认知画像一句话（例：小而精的垂直AI方案商），基于证据归纳，不夸大",
    "strengths": [{{"point": "优势点", "support_refs": ["ans_..."]}}],
    "risks": [{{"point": "风险/弱点", "support_refs": ["ans_..."]}}]
  }},
  "positioning": {{
    "statement": "差异化定位建议一句话（例：不复制大厂生态叙事，占领'懂中国制造现场的小型AI专家'），直接指导内容方向",
    "do": ["可执行的 2-3 条动作"],
    "dont": ["不该做的 1-2 条"],
    "support_refs": ["ans_..."]
  }}
}}

只输出 JSON 本体，不要 markdown 代码块，不要任何解释。"""
