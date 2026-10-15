"""Opt-in, immutable task contract matrix for Source/Evidence Binding V2 and lineage.

This module freezes identities only. It does not apply lineage or authorize an
offspring task: target persistence and enqueue belong to the next slice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from co_scientist.agents.payloads import (
    ClaimDecompositionProviderOutputV2,
    ClaimDecompositionProviderOutputV3,
    ClaimVerificationProviderOutputV2,
    output_schema_version,
    resolve_output_schema,
)
from co_scientist.domain.budget import BudgetEstimate
from co_scientist.domain.claim_lineage import FrozenLineagePlanV2
from co_scientist.domain.claim_verification import scientific_hash
from co_scientist.domain.task import NewTask
from co_scientist.runtime.external_calls import prompt_hash, request_fingerprint
from co_scientist.runtime.task_payload import WorkerTaskPayload
from co_scientist.skills.loader import core_skill_directory, load_skill

LINEAGE_WORKFLOW_VERSION = "source-evidence-binding-claim-lineage-v2"
LINEAGE_RESOLVER_VERSION = "claim-lineage-resolver-v2"
LineageTaskRole = Literal[
    "root_decomposition", "population_evolution", "offspring_decomposition",
    "claim_verification",
]

_ROLE_SKILLS: Mapping[LineageTaskRole, tuple[str, str, str]] = {
    "root_decomposition": ("claim_decomposition", "0.2.0", "claim-provenance-v2"),
    "population_evolution": (
        "population_evolution", "0.2.0", "population-evolution-lineage-v2"),
    "offspring_decomposition": (
        "claim_decomposition", "0.3.0", "claim-provenance-lineage-v3"),
    "claim_verification": (
        "claim_verification", "0.2.0", "claim-verification-result-v2"),
}


def freeze_lineage_workflow_contract() -> dict[str, Any]:
    """Snapshot exact installed skill, output schema, prompt and resolver identities."""

    tasks: dict[str, dict[str, Any]] = {}
    provider_schemas: dict[str, type[BaseModel]] = {
        "root_decomposition": ClaimDecompositionProviderOutputV2,
        "offspring_decomposition": ClaimDecompositionProviderOutputV3,
        "claim_verification": ClaimVerificationProviderOutputV2,
    }
    for role, (skill_id, skill_version, output_contract) in _ROLE_SKILLS.items():
        directory = core_skill_directory(skill_id)
        skill = load_skill(directory, skill_version=skill_version)
        schema_version = output_schema_version(skill.output_schema)
        schema = resolve_output_schema(skill.output_schema, schema_version)
        tasks[role] = {
            "skill_id": skill.id,
            "skill_version": skill.version,
            "output_schema_id": skill.output_schema,
            "output_schema_version": schema_version,
            "output_contract_version": output_contract,
            "prompt_hash": prompt_hash((directory / skill.prompt_path).read_text(
                encoding="utf-8")),
            "schema_hash": scientific_hash(schema.model_json_schema()),
            "provider_schema_hash": scientific_hash(
                provider_schemas[role].model_json_schema()
                if role in provider_schemas else schema.model_json_schema()
            ),
        }
    return {
        "contract_version": LINEAGE_WORKFLOW_VERSION,
        "lineage_contract_version": "claim-lineage-application-v2",
        "resolver_version": LINEAGE_RESOLVER_VERSION,
        "parent_scope_source": (
            "durable-accepted-current-claims-at-selected-parent-content-hashes-v2"
        ),
        "event_schema_versions": {
            "HypothesisClaimCreated": 2,
            "ClaimLineageTargetsFrozenV2": 2,
            "ClaimLineageAppliedV2": 2,
        },
        "task_contracts": tasks,
    }


def validate_lineage_workflow_contract(
    manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Fail closed on missing, altered or stale opt-in profile/manifest identity."""

    profile = manifest.get("profile")
    if not isinstance(profile, Mapping) or profile.get(
        "lineage_workflow_contract") != LINEAGE_WORKFLOW_VERSION:
        raise ValueError("frozen lineage workflow profile selector is missing or invalid")
    expected = freeze_lineage_workflow_contract()
    if (manifest.get("lineage_workflow_contract") != expected
            or manifest.get("lineage_workflow_contract_hash") != scientific_hash(expected)):
        raise ValueError("frozen lineage workflow contract differs from installed contract")
    return expected


def contract_for_task(
    manifest: Mapping[str, Any], role: LineageTaskRole,
) -> Mapping[str, Any]:
    frozen = validate_lineage_workflow_contract(manifest)
    return frozen["task_contracts"][role]


def task_contract_hash(contract: Mapping[str, Any]) -> str:
    return scientific_hash(dict(contract))


def lineage_task_inputs(
    manifest: Mapping[str, Any], role: LineageTaskRole, inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an exact run contract and output contract into the immutable input hash."""

    contract = contract_for_task(manifest, role)
    if any(key in inputs for key in (
        "lineage_workflow_contract_hash", "lineage_task_contract_hash",
        "claim_decomposition_contract_version", "evolution_output_contract_version",
        "claim_verification_output_protocol", "probe_execution_envelope_hash",
    )):
        raise ValueError("lineage contract identity is Supervisor-authored")
    bound = dict(inputs)
    if role == "offspring_decomposition":
        if "lineage_targets" in bound or "lineage_parent_scope" in bound:
            raise ValueError("offspring lineage targets and parent scope are locally frozen")
        plan_data = bound.get("frozen_lineage_plan")
        event_id = bound.get("lineage_targets_frozen_event_id")
        if not isinstance(plan_data, Mapping) or not isinstance(event_id, str) or not event_id:
            raise ValueError("offspring task requires a frozen target plan and event identity")
        plan = FrozenLineagePlanV2.model_validate(plan_data)
        if (bound.get("hypothesis_id") != plan.child_hypothesis_id
                or bound.get("content_hash") != plan.child_hypothesis_content_hash):
            raise ValueError("offspring task differs from frozen child identity")
        bound["lineage_targets"] = [target.model_dump(mode="json")
                                    for target in plan.targets]
        bound["lineage_parent_scope"] = [ref.model_dump(mode="json")
                                         for ref in plan.lineage_parent_scope]
    bound["lineage_workflow_contract_hash"] = manifest["lineage_workflow_contract_hash"]
    bound["lineage_task_contract_hash"] = task_contract_hash(contract)
    if manifest.get("probe_execution_envelope") is not None:
        bound["probe_execution_envelope_hash"] = manifest["probe_execution_envelope_hash"]
    if role in {"root_decomposition", "offspring_decomposition"}:
        bound["claim_decomposition_contract_version"] = contract[
            "output_contract_version"]
    elif role == "population_evolution":
        bound["evolution_output_contract_version"] = contract["output_contract_version"]
    elif role == "claim_verification":
        bound["claim_verification_output_protocol"] = contract["output_contract_version"]
    return bound


def prepare_lineage_task(
    manifest: Mapping[str, Any], *, role: LineageTaskRole, run_id: str,
    task_id: str, intent_type: str, inputs: Mapping[str, Any],
    research_plan_version: int, budget_estimate: BudgetEstimate,
) -> NewTask:
    """Construct only; the Supervisor alone may persist or enqueue this task."""

    contract = contract_for_task(manifest, role)
    supplied = lineage_task_inputs(manifest, role, inputs)
    provider = manifest.get("provider_configuration")
    if not isinstance(provider, Mapping) or not all(isinstance(provider.get(key), str)
                                                   and provider[key] for key in ("provider", "model")):
        raise ValueError("lineage task has no frozen provider identity")
    payload = WorkerTaskPayload(
        skill_id=contract["skill_id"], skill_version=contract["skill_version"],
        output_schema_id=contract["output_schema_id"],
        output_schema_version=contract["output_schema_version"],
        research_plan_version=research_plan_version,
        provider_id=provider["provider"], model_or_tool=provider["model"],
        inputs=supplied, input_snapshot_hash=request_fingerprint(supplied),
        prompt_hash=contract["prompt_hash"], budget_estimate=budget_estimate,
    )
    return NewTask(task_id=task_id, run_id=run_id, idempotency_key=task_id,
                   intent_type=intent_type, payload=payload.model_dump(mode="json"))


def validate_lineage_task_identity(
    manifest: Mapping[str, Any], task: WorkerTaskPayload,
    *, durable_targets_verified: bool = False,
) -> None:
    """Reject a task whose schema/prompt no longer matches its immutable run."""

    profile = manifest.get("profile")
    selected = profile.get("lineage_workflow_contract") if isinstance(profile, Mapping) else None
    if selected is None:
        if ("lineage_workflow_contract" in manifest
                or "lineage_workflow_contract_hash" in manifest):
            raise ValueError("frozen lineage workflow manifest has no profile selector")
        if (any(key in task.inputs for key in (
            "lineage_workflow_contract_hash", "lineage_task_contract_hash",
            "evolution_output_contract_version",
        )) or task.output_schema_id in {
            "PopulationEvolutionResultV2", "ClaimDecompositionResultV3",
        }):
            raise ValueError("lineage task cannot run under a V1/default profile")
        return
    validate_lineage_workflow_contract(manifest)
    if task.skill_id == "claim_decomposition":
        role: LineageTaskRole = (
            "offspring_decomposition"
            if task.output_schema_id == "ClaimDecompositionResultV3"
            else "root_decomposition"
        )
    elif task.skill_id == "population_evolution":
        role = "population_evolution"
    elif task.skill_id == "claim_verification":
        role = "claim_verification"
    else:
        return
    if role == "offspring_decomposition" and not durable_targets_verified:
        raise ValueError("offspring V3 dispatch disabled until targets are durably persisted")
    contract = contract_for_task(manifest, role)
    expected = {
        "skill_id": contract["skill_id"],
        "skill_version": contract["skill_version"],
        "output_schema_id": contract["output_schema_id"],
        "output_schema_version": contract["output_schema_version"],
        "prompt_hash": contract["prompt_hash"],
    }
    if any(getattr(task, name) != value for name, value in expected.items()):
        raise ValueError("task identity differs from frozen lineage workflow contract")
    if (task.inputs.get("lineage_workflow_contract_hash") !=
            manifest["lineage_workflow_contract_hash"]
            or task.inputs.get("lineage_task_contract_hash") != task_contract_hash(contract)):
        raise ValueError("task input differs from frozen lineage workflow contract")
    if manifest.get("probe_execution_envelope") is not None:
        if task.inputs.get("probe_execution_envelope_hash") != manifest.get(
            "probe_execution_envelope_hash"
        ):
            raise ValueError("task input differs from frozen probe execution envelope")
    elif "probe_execution_envelope_hash" in task.inputs:
        raise ValueError("probe envelope task identity requires a frozen probe manifest")
    field = {"root_decomposition": "claim_decomposition_contract_version",
             "offspring_decomposition": "claim_decomposition_contract_version",
             "population_evolution": "evolution_output_contract_version",
             "claim_verification": "claim_verification_output_protocol"}[role]
    if task.inputs.get(field) != contract["output_contract_version"]:
        raise ValueError("task output contract differs from frozen lineage workflow")
