"""Read-only syntax hints for persisted responses, never validation or repair."""

import json
from typing import Any


def json_syntax_diagnostic(raw: bytes, provider: str) -> dict[str, Any] | None:
    if provider not in {"deepseek", "qwen", "replay"}:
        return None
    channel = "raw"
    try:
        envelope = json.loads(raw)
        if provider != "replay":
            channel = "message.content"
            choices = envelope.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                return {"code": "unavailable", "summary": "无法确定唯一结果通道，请核对原文。"}
            message = choices[0]["message"]
            if choices[0].get("finish_reason") == "tool_calls":
                channel = "tool.arguments"
                calls = message.get("tool_calls")
                if not isinstance(calls, list) or len(calls) != 1:
                    return {"code": "unavailable", "summary": "工具结果缺失或不唯一，请核对原文。"}
                content = calls[0]["function"]["arguments"]
            else:
                content = message.get("content")
            if not isinstance(content, str):
                return {"code": "unavailable", "summary": "结果通道不是 JSON 文本字符串。"}
            json.loads(content)
        return {"code": "syntax_valid", "channel": channel,
            "summary": "JSON 可解析；这不代表字段、重复键、内容绑定或科学评审已通过。"}
    except json.JSONDecodeError as error:
        return {"code": "invalid_json", "channel": channel,
            "position": error.pos, "line": error.lineno, "column": error.colno,
            "summary": f"{channel} 的 JSON 语法错误：{error.msg}；"
                       f"第 {error.lineno} 行、第 {error.colno} 列，字符位置 {error.pos}（从 0 计）。未修补原文。"}
    except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        return {"code": "unavailable", "summary": "响应结构无法提供语法提示，请核对原文。"}
