import copy
import json
import shutil
from pathlib import Path

import pytest

from co_scientist.application.cockpit_settings import (
    list_saved,
    save_settings,
    settings_catalog,
    validate_settings,
)
from co_scientist.application.config import resolve_run_config

ROOT = Path(__file__).resolve().parents[3]


def draft(provider: str = "deepseek") -> dict:
    template = next(t for t in settings_catalog(ROOT, {})["templates"] if t["id"] == provider)
    return {"name": "研究配置", "goal": template["goal"], "profile": template["profile"],
            "model": "example-model" if provider != "replay" else ""}


def test_catalog_contains_no_secret_values() -> None:
    result = settings_catalog(ROOT, {"OPENAI_API_KEY": "secret-test-value",
                                     "CO_SCIENTIST_OPENAI_MODEL": "example-model"})
    assert "secret-test-value" not in json.dumps(result)
    entry = next(p for p in result["providers"] if p["id"] == "openai")
    assert entry["key_configured"] is True
    assert entry["model"] == "example-model"


@pytest.mark.parametrize("provider", ["openai", "deepseek", "qwen", "gemini", "claude", "replay"])
def test_every_template_validates(provider: str) -> None:
    assert validate_settings(draft(provider))["ok"]


@pytest.mark.parametrize("path,value", [
    (("profile", "evolution", "max_rounds"), -1),
    (("profile", "providers", "deepseek_generation", "max_tokens"), 0),
    (("profile", "budget", "max_matches"), -1),
    (("profile", "tournament", "anchor_count"), 3),
    (("profile", "stop", "require_top_k_stability"), False),
    (("profile", "review_policy", "required_before_admission"), ["full_review"]),
    (("profile", "scientific_context"), False),
    (("model",), "x; touch /tmp/not-allowed"),
    (("api_key",), "not-allowed"),
    (("profile", "budget", "unknown"), 10),
])
def test_invalid_or_unsupported_settings_do_not_write(tmp_path: Path, path: tuple, value) -> None:
    data = draft()
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    result = save_settings(tmp_path, data)
    assert result["ok"] is False
    assert not (tmp_path / ".co-scientist-configs").exists()


def test_dependency_error_and_budget_warning() -> None:
    data = draft()
    data["profile"]["review_policy"]["required_before_admission"] = ["initial_review"]
    assert not validate_settings(data)["ok"]
    data["profile"]["literature_novelty_required"] = False
    data["profile"]["budget"]["max_model_calls"] = 1
    data["profile"]["budget"]["max_usd"] = 5
    result = validate_settings(data)
    assert result["ok"]
    assert any("定价" in w for w in result["warnings"])
    assert any("max_model_calls" in w for w in result["warnings"])


def test_saved_online_files_resolve_with_actual_cli_contract(tmp_path: Path) -> None:
    data = draft()
    original = copy.deepcopy(data)
    result = save_settings(tmp_path, data)
    assert result["ok"] and result["run_started"] is False
    path = tmp_path / result["directory"]
    resolved = resolve_run_config(goal_file=path / "goal.yaml", profile_file=path / "profile.yaml",
                                  provider="deepseek", environment={
                                      "DEEPSEEK_API_KEY": "test-only-key",
                                      "CO_SCIENTIST_DEEPSEEK_MODEL": data["model"],
                                  })
    assert resolved.profile.budget.max_model_calls == 40
    assert resolved.goal.title == data["goal"]["title"]
    assert resolved.manifest["provider_configuration"]["model"] == "example-model"
    assert data == original
    assert "test-only-key" not in json.dumps(result)
    assert list_saved(tmp_path)[0]["draft"]["name"] == "研究配置"
    assert not list(tmp_path.rglob("*.db"))
    second = save_settings(tmp_path, data)
    assert second["directory"] != result["directory"]
    assert (path / "profile.yaml").read_text() == result["files"]["profile.yaml"]


def test_saved_replay_paths_resolve_from_new_directory(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "examples/lens_regeneration_replay",
                    tmp_path / "examples/lens_regeneration_replay")
    result = save_settings(tmp_path, draft("replay"))
    path = tmp_path / result["directory"]
    resolved = resolve_run_config(goal_file=path / "goal.yaml", profile_file=path / "profile.yaml",
                                  provider="replay", environment={})
    assert resolved.provider_id == "replay"
    assert len(resolved.manifest["replay_resources"]) == 3


@pytest.mark.parametrize("protocol", ["deepseek-strict-tool-v1", "deepseek-strict-tool-v2"])
def test_strict_ranking_settings_save_and_dependency_error(tmp_path: Path, protocol: str) -> None:
    data = draft()
    data["profile"]["ranking_output_protocol"] = protocol
    data["profile"]["meta_review"]["contract_version"] = "meta-review-loop-v2"
    result = save_settings(tmp_path, data)
    assert result["ok"] and result["run_started"] is False
    path = tmp_path / result["directory"]
    resolved = resolve_run_config(
        goal_file=path / "goal.yaml", profile_file=path / "profile.yaml",
        provider="deepseek", environment={
            "DEEPSEEK_API_KEY": "test-only-key",
            "CO_SCIENTIST_DEEPSEEK_MODEL": data["model"],
        },
    )
    assert resolved.manifest["ranking_output_contract"]["version"] == protocol
    assert resolved.manifest["feedback_contract"]["version"] == "meta-review-loop-v2"
    assert list_saved(tmp_path)[0]["draft"]["profile"]["meta_review"]["contract_version"] == "meta-review-loop-v2"
    assert list_saved(tmp_path)[0]["draft"]["profile"]["ranking_output_protocol"] == protocol
    assert not list(tmp_path.rglob("*.db"))
    data["profile"]["research_protocol_version"] = None
    invalid = validate_settings(data)
    assert not invalid["ok"]
    assert invalid["errors"][0]["field"] == "profile.ranking_output_protocol"


def test_unlimited_is_null_not_zero() -> None:
    data = draft()
    data["profile"]["meta_review"]["max_rounds"] = 0
    data["profile"]["budget"]["max_model_calls"] = None
    unlimited = validate_settings(data)
    assert unlimited["draft"]["profile"]["budget"]["max_model_calls"] is None
    data["profile"]["budget"]["max_model_calls"] = 0
    assert validate_settings(data)["draft"]["profile"]["budget"]["max_model_calls"] == 0


def test_symlink_save_directory_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "other").mkdir()
    (tmp_path / ".co-scientist-configs").symlink_to(tmp_path / "other", target_is_directory=True)
    with pytest.raises(ValueError):
        save_settings(tmp_path, draft())
