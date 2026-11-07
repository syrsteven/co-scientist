"""Server-owned versioned policy bundles; client choices never supply policy text."""

from copy import deepcopy

from .background import digest
from .research_policies import POLICIES


def catalog(development_test=False):
    policies = POLICIES
    identifier = "conceptual-nonproduction-v1"
    if development_test:
        from .candidate_review_ops import DEVELOPMENT_DECISIONS, DEVELOPMENT_R0_POLICY
        from .candidate_review_ops import DEVELOPMENT_POLICY as CANDIDATE
        from .goal import DEVELOPMENT_POLICY

        policies = {
            "goal": DEVELOPMENT_POLICY,
            "candidate": CANDIDATE,
            "decision_policy": DEVELOPMENT_DECISIONS,
            "r0": DEVELOPMENT_R0_POLICY,
        }
        identifier = "isolated-offline-fixture-v1"
    return {
        identifier: {
            "id": identifier,
            "version": "1",
            "sha256": digest(policies),
            "policies": deepcopy(policies),
        }
    }


def choices(development_test=False):
    return [
        {k: v for k, v in entry.items() if k != "policies"}
        for entry in catalog(development_test).values()
    ]


def resolve(selection, development_test=False):
    if not isinstance(selection, dict) or set(selection) != {"id", "version", "sha256"}:
        raise ValueError("Select a server-controlled policy ID/version/hash")
    entry = catalog(development_test).get(selection["id"])
    if not entry or any(selection[k] != entry[k] for k in selection):
        raise ValueError("Unknown or changed policy selection")
    return entry["policies"]
