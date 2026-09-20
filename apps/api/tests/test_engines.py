"""6 引擎适配：温度 / 联网参数按实际模型收口（不打真实厂商）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # eios-geo
API = Path(__file__).resolve().parents[1]  # apps/api
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(API))

from adapters.engines import extract_responses_text, resolve_temperature, resolve_web_cfg


def test_kimi_k_series_temperature_is_1_0():
    assert resolve_temperature("kimi", "kimi-k3") == 1.0
    assert resolve_temperature("kimi", "kimi-k2.5") == 1.0
    assert resolve_temperature("kimi", "Kimi-K3") == 1.0


def test_kimi_legacy_moonshot_keeps_registry_temp():
    # 注册表默认 0.6；K 系列（kimi-k3 等）实测只收 1.0（2026-08-21 修正）
    assert resolve_temperature("kimi", "moonshot-v1-8k") == 0.6


def test_other_engines_keep_registry_temp():
    assert resolve_temperature("deepseek", "deepseek-v4-flash") == 0.2
    assert resolve_temperature("doubao", "doubao-seed-2-1-pro-260628") == 0.3


def test_doubao_seed_web_uses_responses_api():
    cfg = resolve_web_cfg("doubao", "doubao-seed-2-1-pro-260628", True)
    assert cfg is not None
    assert cfg["mode"] == "responses"
    assert cfg["tools"][0]["type"] == "web_search"


def test_doubao_legacy_pro_keeps_chat_tools():
    cfg = resolve_web_cfg("doubao", "doubao-pro-32k", True)
    assert cfg is not None
    assert cfg["mode"] == "tools"


def test_deepseek_web_is_none():
    assert resolve_web_cfg("deepseek", "deepseek-v4-flash", True) is None


def test_web_false_disables_all():
    assert resolve_web_cfg("qwen", "qwen3.7-plus", False) is None


def test_extract_responses_output_text():
    assert extract_responses_text({"output_text": "  北京晴  "}) == "北京晴"


def test_extract_responses_message_parts():
    data = {
        "output": [
            {"type": "web_search_call", "action": {}},
            {"type": "message", "content": [{"type": "output_text", "text": "今天多云"}]},
        ]
    }
    assert extract_responses_text(data) == "今天多云"
