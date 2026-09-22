from co_scientist.application.model_catalog import model_catalog


def test_public_catalog_is_dated_and_not_an_availability_or_cost_claim() -> None:
    catalog = model_catalog()
    models = catalog["models"]
    assert {m["provider"] for m in models} == {"openai", "deepseek", "qwen", "gemini", "claude"}
    assert len(models) == len({(m["provider"], m["id"]) for m in models}) == 19
    for model in models:
        assert model["verified_at"] == "2026-09-17"
        assert model["source"].startswith("https://")
        assert model["currency"] == ("CNY" if model["provider"] == "qwen" else "USD")
        assert "未验证" in model["availability"]
        assert all(rate["input"] > 0 and rate["output"] > 0 for rate in model["rates"])
    flash = next(m for m in models if m["id"] == "deepseek-flash")
    assert flash["rates"][0]["input"] == .15
    assert flash["rates"][1]["input"] == .30
    assert next(m for m in models if m["id"] == "claude-fable-5-1")["selectable"] is False
    models[0]["rates"][0]["input"] = 999
    assert model_catalog()["models"][0]["rates"][0]["input"] != 999
