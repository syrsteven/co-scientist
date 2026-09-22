"""Dated public reference prices, never an accounting or availability authority."""

from copy import deepcopy
from typing import Any

CATALOG_DATE = "2026-09-17"
SOURCES = {
    "openai": "https://developers.openai.com/api/docs/pricing",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "qwen": "https://help.aliyun.com/zh/model-studio/model-pricing",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "claude": "https://platform.claude.com/docs/en/about-claude/pricing",
}


def _model(provider: str, model: str, name: str, rates: list[tuple[str, float, float, float | None]],
           *, note: str = "", selectable: bool = True) -> dict[str, Any]:
    return {
        "provider": provider, "id": model, "name": name, "selectable": selectable,
        "currency": "CNY" if provider == "qwen" else "USD", "unit": "1M tokens",
        "source": SOURCES[provider], "verified_at": CATALOG_DATE, "note": note,
        "rates": [{"condition": condition, "input": inp, "output": out, "cached_input": cache}
                  for condition, inp, out, cache in rates],
        "availability": "官方公开目录；账户权限与本项目实测兼容性未验证",
    }


_MODELS = [
    _model("openai", "gpt-6-astra", "GPT-6 Astra", [
        ("Standard · short context", 10, 50, 1), ("Standard · long context", 20, 75, 2)],
        note="显式缓存写入另计12.5/25；长上下文边界以官方模型说明为准。"),
    _model("openai", "gpt-5.6-sol", "GPT-5.6 Sol", [
        ("Standard · short context", 4, 20, .4), ("Standard · long context", 8, 30, .8)],
        note="当前优惠至少至2026-11-21；显式缓存写入另计5/10。"),
    _model("openai", "gpt-5.6-terra", "GPT-5.6 Terra", [
        ("Standard · short context", 2, 12, .2), ("Standard · long context", 4, 18, .4)],
        note="显式缓存写入另计2.5/5；不包含Fast/Batch和地区附加费。"),
    _model("openai", "gpt-5.6-luna", "GPT-5.6 Luna", [
        ("Standard · short context", .2, 1.2, .02), ("Standard · long context", .4, 1.8, .04)],
        note="显式缓存写入另计0.25/0.5。"),
    _model("openai", "gpt-5.5", "GPT-5.5", [
        ("Standard · <272K context", 5, 30, .5), ("Standard · long context", 10, 45, 1)]),
    _model("deepseek", "deepseek-flash", "DeepSeek V4.1 Flash", [
        ("谷时 Off-peak", .15, .6, .003), ("峰时 Peak", .3, 1.2, .006)],
        note="工作日UTC01–04、06–10为峰时，其余为谷时。旧v4-flash别名已指向此新模型，不能用于锁定旧版本。"),
    _model("deepseek", "deepseek-v4-pro", "DeepSeek V4 Pro 0813", [
        ("谷时 Off-peak", .66, 1.98, .022), ("峰时 Peak", 1.32, 3.96, .044)],
        note="官方确认9月14日后继续提供服务，后续变动另行通知；峰时规则同Flash。"),
    _model("qwen", "qwen3.8-max", "Qwen3.8 Max", [("北京 · ≤1M输入 · 标价", 12, 36, None)],
        note="当前adapter固定北京endpoint、非思考模式。人民币报价；缓存优惠以官方页为准。"),
    _model("qwen", "qwen3.7-plus", "Qwen3.7 Plus", [
        ("北京 · ≤256K输入 · 标价", 2, 8, None), ("北京 · >256K至1M · 标价", 6, 24, None)],
        note="官方另列限时8折（未给终止日期），不将临时折扣当长期预算。该请求全部token按对应输入长度档计费。"),
    _model("qwen", "qwen3.8-flash", "Qwen3.8 Flash", [("北京 · ≤1M输入 · 标价", .8, 2.7, None)]),
    _model("qwen", "qwen3.7-flash", "Qwen3.7 Flash", [
        ("北京 · ≤32K输入", .2, .8, None), ("北京 · >32K至256K", .6, 2.4, None),
        ("北京 · >256K至1M", 1.2, 4.8, None)]),
    _model("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", [
        ("Standard付费 · 至2026-12-31", .75, 3.75, .075),
        ("Standard付费 · 2027-01-01起", 1.5, 7.5, .15)],
        note="输出含thinking tokens；缓存存储与Google Search等工具另计。免费层另有数据使用条款。"),
    _model("gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", [
        ("Standard付费 · 至2026-12-31", .75, 3.75, .075),
        ("Standard付费 · 2027-01-01起", 1.5, 7.5, .15)]),
    _model("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", [
        ("Standard付费 · 文本", .3, 2.5, .03)]),
    _model("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview", [
        ("Standard付费 · 输入≤200K", 2, 12, .2), ("Standard付费 · 输入>200K", 4, 18, .4)],
        note="Preview型号；输出含thinking，缓存存储4.5 USD/1M tokens/hour另计。"),
    _model("claude", "claude-fable-5-1", "Claude Fable 5.1", [
        ("Standard · 全上下文", 10, 50, .25)], selectable=False,
        note="官方为always-on adaptive thinking。当前adapter未验证其必要配置，目录展示但不作为已支持的快捷选择；可自定义试验。缓存写入5分钟12.5、1小时20另计。"),
    _model("claude", "claude-opus-5", "Claude Opus 5", [("Standard · 全上下文", 5, 25, .5)],
        note="缓存写入5分钟6.25、1小时10；地区/工具/Fast费用另计。"),
    _model("claude", "claude-sonnet-5", "Claude Sonnet 5", [("Standard · 全上下文", 2, 10, .2)],
        note="2/10已转为标准价，不再执行原定9月涨价。缓存写入5分钟2.5、1小时4。"),
    _model("claude", "claude-haiku-4-5-20251001", "Claude Haiku 4.5", [
        ("Standard · 全上下文", 1, 5, .1)], note="缓存写入5分钟1.25、1小时2。"),
]


def model_catalog() -> dict[str, Any]:
    return {"verified_at": CATALOG_DATE, "models": deepcopy(_MODELS),
            "disclaimer": "参考报价快照，不是实时询价或账户可用性保证；不改历史成本账本。币种不混加；未列出价格不代表免费。"}
