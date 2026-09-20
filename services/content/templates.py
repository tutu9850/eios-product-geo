"""GEO 可抽取结构模板（认知编译器 · 生成结构层）

生成式引擎偏好「结构清晰、事实密度高、可提取证据」的内容——
本模板把自由长文约束为固定分节（直接回答/列表/表格/案例块/FAQ），
每节有固定标题与指令，LLM 按节填内容，输出可被模型逐节抓取。
"""
import re

# GEO 结构指令（追加到生成 prompt 尾部；structure="geo" 时生效）
STRUCTURE_GEO_INSTRUCTION = """
## 输出结构（必须严格遵守，逐节输出，不要自由发挥）

按以下固定分节组织内容（Markdown 标题逐节）：

### 一、一句话回答（What is）
第一行直接回答"它是什么"——一句话，含企业名 + 核心定位，不铺垫。
（生成式引擎最先抓取这一句，必须信息密度最高。）

### 二、它解决什么问题
分点列表（3-5 条），每条：问题 → 一句话说明该企业怎么解决。
（列表项要独立可抽取，不要长段落。）

### 三、与传统方案 / 竞品的区别
Markdown 表格，至少 3 行对比维度：
| 维度 | 本企业 | 传统方案/竞品 |
（表格是生成式引擎最容易抽取的结构，必须给出。）

### 四、企业事实与案例
用给定「企业事实」里的真实数字/时间/实体组织（禁止编造数字）：
- 时间：…
- 客户/对象：…
- 结果/数据：…
知识库没有的事实写「暂无公开数据」，绝不编造。

### 五、常见问题 FAQ
3-5 条 Q&A（优先覆盖「客户问题池」里的问题）：
Q: …
A: …（基于企业事实回答，不编造）

## 输出要求
- 每节标题固定，内容紧凑；总长度 {length} 字左右。
- 全文只使用「企业事实」里的数据；没有就不写数字。
"""


def parse_sections(text: str) -> dict:
    """从生成文本提取分节（供前端分节渲染 / GEO 评分）。只认模板五节标题（审计 P2-13）。"""
    expected = [
        "一句话回答",
        "它解决什么问题",
        "与传统方案",
        "企业事实与案例",
        "常见问题",
    ]
    sections: dict[str, str] = {}
    lines = text.split("\n")
    current = None
    buf: list[str] = []
    for line in lines:
        m = re.match(r"^#{1,4}\s*(.+)", line.strip())
        if m:
            title = m.group(1).strip()
            if current:
                sections[current] = "\n".join(buf).strip()
            matched = next((e for e in expected if e in title), None)
            current = matched  # 非模板标题 → None（不计节）
            buf = []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections
