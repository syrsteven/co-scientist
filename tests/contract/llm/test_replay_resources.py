import json
from pathlib import Path

import pytest

from co_scientist.adapters.llm.replay import ReplayLLMProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CORE_TRACE = REPOSITORY_ROOT / "examples/lens_regeneration_replay/core_trace.json"


# Mutations caught: resolving prompts relative to the caller CWD or accepting a
# checked-in replay trace without validating every declared Core result contract.
def test_checked_in_replay_trace_is_cwd_independent_and_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    provider = ReplayLLMProvider.from_file(CORE_TRACE)

    assert provider.responses


# Mutation caught: treating unused replay records as untyped inert JSON, allowing
# a release resource to claim six-agent coverage while one schema is malformed.
def test_replay_trace_rejects_a_malformed_unused_agent_result(tmp_path: Path) -> None:
    document = json.loads(CORE_TRACE.read_text(encoding="utf-8"))
    meta_review = next(
        item for item in document["responses"] if item["skill_id"] == "meta_review"
    )
    meta_review["response"]["overview"] = ""
    malformed = tmp_path / "malformed-trace.json"
    malformed.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="typed replay response"):
        ReplayLLMProvider.from_file(malformed)
