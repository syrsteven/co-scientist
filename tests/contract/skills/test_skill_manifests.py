from pathlib import Path

from co_scientist.skills.loader import load_skill


# Mutation caught: omitting a core skill contract, its pinned version, or its
# Supervisor-safe capability boundary.
def test_all_six_core_skills_are_versioned_and_forbid_task_creation() -> None:
    names = ("generation", "reflection", "ranking", "proximity", "evolution", "meta_review")
    manifests = [load_skill(Path("skills") / name) for name in names]
    assert {manifest.agent_type for manifest in manifests} == set(names)
    assert all(manifest.version == "0.1.0" for manifest in manifests)
    assert all("create_task" not in manifest.allowed_capabilities for manifest in manifests)
