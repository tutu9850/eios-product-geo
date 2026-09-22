import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_website_diagnosis_uses_real_page_checks(monkeypatch):
    from app.api.v1 import diagnose

    html = """<html><head><title>亚宇臻隆科技 GEO 企业服务官方网站</title>
    <meta name="description" content="亚宇臻隆科技提供国产大模型监测、企业知识治理与GEO内容增长服务，帮助企业持续分析品牌认知并改进官网内容。">
    <script type="application/ld+json">{"@type":"Organization"}</script></head>
    <body><h1>亚宇臻隆科技</h1><h2>产品</h2><h2>服务</h2><h2>常见问题？</h2>
    <p>亚宇臻隆科技</p><p>亚宇臻隆科技</p><p>亚宇臻隆科技</p></body></html>"""

    async def fake_fetch(_url: str):
        return html, ""

    monkeypatch.setattr(diagnose, "_fetch", fake_fetch)
    data = asyncio.run(diagnose.diagnose(diagnose.DiagnoseIn(url="example.com")))["data"]

    assert data["fetchable"] is True
    assert data["url"] == "https://example.com"
    assert {row["key"] for row in data["checks"]} == {"schema", "meta", "structure", "depth", "brand", "faq", "accessibility"}
    assert data["score"] > 0

