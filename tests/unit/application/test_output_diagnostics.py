import json

import pytest

from co_scientist.application.output_diagnostics import json_syntax_diagnostic


@pytest.mark.parametrize("tool", [False, True])
def test_syntax_location_refers_to_inner_text_without_repair(tool):
    content = '{"unresolved_disagreements":["synthetic"}'
    message = {"content": content}
    if tool:
        message = {"tool_calls": [{"function": {"arguments": content}}]}
    raw = json.dumps({"choices": [{"finish_reason": "tool_calls" if tool else "stop",
                                   "message": message}]}).encode()
    result = json_syntax_diagnostic(raw, "deepseek")
    assert result["code"] == "invalid_json" and result["position"] == len(content) - 1
    assert result["channel"] == ("tool.arguments" if tool else "message.content")
    assert "未修补" in result["summary"]


def test_outer_syntax_and_success_never_claim_schema_validation():
    assert json_syntax_diagnostic(b'{"bad":[', "deepseek")["channel"] == "raw"
    result = json_syntax_diagnostic(b'{"not_a_result":true}', "replay")
    assert result["code"] == "syntax_valid" and "不代表" in result["summary"]
    assert json_syntax_diagnostic(b"<xml/>", "pubmed:summary") is None


@pytest.mark.parametrize("document", [[], {}, {"choices": [None]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": []}}]},
])
def test_unknown_envelope_only_returns_a_hint(document):
    assert json_syntax_diagnostic(json.dumps(document).encode(), "deepseek")["code"] == "unavailable"
