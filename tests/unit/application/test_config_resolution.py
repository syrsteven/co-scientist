import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from co_scientist.application.config import resolve_run_config
from tests.core_preview_support import write_core_preview_inputs


def test_resolved_replay_config_freezes_canonical_non_secret_manifest(tmp_path: Path) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    environment["OPENAI_API_KEY"] = "never-persist-this-secret"

    resolved = resolve_run_config(
        goal_file=goal_file,
        profile_file=profile_file,
        provider="replay",
        environment=environment,
    )

    encoded = json.dumps(resolved.model_dump(mode="json")["manifest"], sort_keys=True)
    assert resolved.manifest["execution_contract_version"] == 3
    assert resolved.manifest["goal"] == resolved.goal.model_dump(mode="json")
    assert resolved.manifest["profile"] == resolved.profile.model_dump(mode="json")
    assert resolved.manifest["admission_policies"]["admission-v1"]
    assert len(resolved.manifest["anchor_sets"][0]["members"]) == 2
    assert {item["kind"] for item in resolved.manifest["replay_resources"]} == {
        "llm_responses",
        "pubmed_search",
        "pubmed_summary",
    }
    assert all(item["sha256"].startswith("sha256:") for item in resolved.manifest["replay_resources"])
    assert resolved.manifest_hash.startswith("sha256:")
    assert resolved.provider_id == "replay"
    assert "never-persist-this-secret" not in encoded
    assert "OPENAI_API_KEY" not in encoded
    with pytest.raises(TypeError):
        resolved.manifest["goal"]["title"] = "mutated"  # type: ignore[index]


def test_checked_in_core_preview_profile_matches_the_production_schema(tmp_path: Path) -> None:
    _, _, environment = write_core_preview_inputs(tmp_path)

    resolved = resolve_run_config(
        goal_file=Path("examples/lens_regeneration_goal.yaml"),
        profile_file=Path("configs/profiles/core_preview.yaml"),
        provider="replay",
        environment=environment,
    )

    assert resolved.profile.profile_id == "core_preview"
    assert resolved.profile.stop.minimum_matches == 6


@pytest.mark.parametrize(
    "kind", ["missing", "invalid_yaml", "invalid_schema", "non_object"]
)
def test_goal_and_profile_files_fail_closed(tmp_path: Path, kind: str) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    if kind == "missing":
        goal_file.unlink()
    elif kind == "invalid_yaml":
        profile_file.write_text("providers: [", encoding="utf-8")
    elif kind == "non_object":
        profile_file.write_text("[]\n", encoding="utf-8")
    else:
        goal = yaml.safe_load(goal_file.read_text(encoding="utf-8"))
        goal["unexpected"] = True
        goal_file.write_text(yaml.safe_dump(goal), encoding="utf-8")

    with pytest.raises((FileNotFoundError, TypeError, ValueError, ValidationError)):
        resolve_run_config(
            goal_file=goal_file,
            profile_file=profile_file,
            provider="replay",
            environment=environment,
        )


def test_unsupported_provider_and_missing_provider_resources_fail_before_execution(
    tmp_path: Path,
) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    with pytest.raises(ValueError, match="provider"):
        resolve_run_config(
            goal_file=goal_file,
            profile_file=profile_file,
            provider=cast(Any, "fake"),
            environment=environment,
        )

    with pytest.raises(ValueError, match="CO_SCIENTIST_REPLAY_RESPONSES"):
        resolve_run_config(
            goal_file=goal_file,
            profile_file=profile_file,
            provider="replay",
            environment={},
        )

    with pytest.raises(ValueError, match="OPENAI_API_KEY|CO_SCIENTIST_OPENAI_MODEL"):
        resolve_run_config(
            goal_file=goal_file,
            profile_file=profile_file,
            provider="openai",
            environment={},
        )


def test_malformed_replay_records_fail_during_resolution(tmp_path: Path) -> None:
    goal_file, profile_file, environment = write_core_preview_inputs(tmp_path)
    replay_file = Path(environment["CO_SCIENTIST_REPLAY_RESPONSES"])
    replay = json.loads(replay_file.read_text(encoding="utf-8"))
    replay["responses"][0]["inputs"] = []
    replay_file.write_text(json.dumps(replay), encoding="utf-8")

    with pytest.raises(ValueError, match="REPLAY_RESPONSES is malformed"):
        resolve_run_config(
            goal_file=goal_file,
            profile_file=profile_file,
            provider="replay",
            environment=environment,
        )
