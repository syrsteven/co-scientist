"""Pure, versioned Batch 2 prerequisite contracts. No execution or state writes.

Provider proposals are not durable authority. Only a validated, task-bound
Supervisor application can produce committed facts consumed by a projection.
These contracts do not activate any production operation in Batch 2-A.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from co_scientist.domain.research_protocol import protocol_hash
from co_scientist.events.models import DomainEvent

Text = Annotated[str, StringConstraints(strict=True, min_length=1, strip_whitespace=True)]
Sha = Annotated[str, StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]
EthicsVerdict = Literal["PASS", "REJECT", "TECHNICAL_UNKNOWN"]
Operation = Literal[
    "DIRECTIVE_ETHICS", "ROOT_QUERY_PLAN", "ROOT_RETRIEVAL", "ROOT_SOURCE_REVIEW",
    "ROOT_GROUNDING_FREEZE", "ROOT_GENERATION", "CANDIDATE_ETHICS", "SAFE_REDESIGN",
    "REFLECTION", "RANKING", "EVOLUTION", "FINAL",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskBindingV1(ContractModel):
    """Exact frozen task authority, copied/checked locally, not an Ethics verdict."""

    version: Literal["ideation-task-binding-v1"] = "ideation-task-binding-v1"
    run_id: Text
    directive_id: Text
    directive_version: int = Field(ge=1, strict=True)
    directive_hash: Sha
    profile_hash: Sha
    creation_epoch: Text
    boundary_version: Literal["ideation-core-boundary-v2"] = "ideation-core-boundary-v2"
    readiness_version: Literal["ideation-core-readiness-v2"] = "ideation-core-readiness-v2"
    task_id: Text
    attempt: int = Field(ge=1, strict=True)
    skill_id: Text
    skill_version: Text
    schema_id: Text
    schema_version: Literal[1]
    prompt_hash: Sha
    input_hash: Sha
    provider: Text
    model: Text
    api: Text
    thinking_mode: Text
    capability_id: Text
    phase: Literal["QUERY_PLAN_V1", "SOURCE_REVIEW_V1"] | None = None
    root_slot_id: Literal["root-slot-0", "root-slot-1", "root-slot-2", "root-slot-3"] | None = None
    slot_id: Text | None = None
    hypothesis_id: Text | None = None
    content_hash: Sha | None = None
    plan_hash: Sha | None = None
    source_set_hash: Sha | None = None
    generation_input_hash: Sha | None = None
    redesign_of: Text | None = None
    redesign_count: int = Field(default=0, ge=0, le=1, strict=True)
    scientific_parent_ids: tuple[Text, ...] = ()
    retrieval_policy: Literal["pubmed-root-grounding-v1"] = "pubmed-root-grounding-v1"
    transport_policy: Literal["baseline-slot-http-response-isolation-v1"] = (
        "baseline-slot-http-response-isolation-v1"
    )

    @model_validator(mode="after")
    def validate_identity(self) -> TaskBindingV1:
        if (self.hypothesis_id is None) != (self.content_hash is None):
            raise ValueError("candidate binding requires both ID and content hash")
        if len(set(self.scientific_parent_ids)) != len(self.scientific_parent_ids):
            raise ValueError("duplicate scientific parent identity")
        if bool(self.redesign_count) != bool(self.redesign_of):
            raise ValueError("redesign count and redesign_of must agree")
        if self.hypothesis_id in self.scientific_parent_ids:
            raise ValueError("self-parent binding")
        return self


class RetrievalRequestBindingV2(ContractModel):
    """Exact frozen task authority, copied/checked locally, not an Ethics verdict."""

    version: Literal["retrieval-request-binding-v2"] = "retrieval-request-binding-v2"
    run_id: Text
    directive_id: Text
    directive_version: int = Field(ge=1, strict=True)
    directive_hash: Sha
    profile_hash: Sha
    creation_epoch: Text
    boundary_version: Literal["ideation-core-boundary-v2"] = "ideation-core-boundary-v2"
    readiness_version: Literal["ideation-core-readiness-v2"] = "ideation-core-readiness-v2"
    task_id: Text
    attempt: int = Field(ge=1, strict=True)
    skill_id: Text
    skill_version: Text
    schema_id: Text
    schema_version: Literal[2]
    prompt_hash: Sha
    input_hash: Sha
    provider: Text
    model: Text
    api: Text
    thinking_mode: Text
    capability_id: Text
    phase: Literal["QUERY_PLAN_V1", "SOURCE_REVIEW_V1"] | None = None
    root_slot_id: Literal["root-slot-0", "root-slot-1", "root-slot-2", "root-slot-3"] | None = None
    slot_id: Text | None = None
    hypothesis_id: Text | None = None
    content_hash: Sha | None = None
    plan_hash: Sha | None = None
    source_set_hash: Sha | None = None
    generation_input_hash: Sha | None = None
    redesign_of: Text | None = None
    redesign_count: int = Field(default=0, ge=0, le=1, strict=True)
    scientific_parent_ids: tuple[Text, ...] = ()
    retrieval_policy: Literal["pubmed-root-grounding-v1"] = "pubmed-root-grounding-v1"
    transport_policy: Literal["baseline-slot-http-response-isolation-v1"] = (
        "baseline-slot-http-response-isolation-v1"
    )

    @model_validator(mode="after")
    def validate_identity(self) -> RetrievalRequestBindingV2:
        if (self.hypothesis_id is None) != (self.content_hash is None):
            raise ValueError("candidate binding requires both ID and content hash")
        if len(set(self.scientific_parent_ids)) != len(self.scientific_parent_ids):
            raise ValueError("duplicate scientific parent identity")
        if bool(self.redesign_count) != bool(self.redesign_of):
            raise ValueError("redesign count and redesign_of must agree")
        if self.hypothesis_id in self.scientific_parent_ids:
            raise ValueError("self-parent binding")
        return self

    @model_validator(mode="after")
    def request_only(self) -> RetrievalRequestBindingV2:
        if (self.schema_id != "RootRetrievalResultV2" or self.skill_id != "root_retrieval"
                or self.root_slot_id is None or self.plan_hash is None
                or self.source_set_hash is not None or self.generation_input_hash is not None
                or self.hypothesis_id is not None or self.phase is not None):
            raise ValueError("retrieval request cannot bind future completed source scope")
        return self


def validate_binding(expected: ContractModel, supplied: ContractModel) -> None:
    mismatches = [key for key, value in expected.model_dump().items()
                  if supplied.model_dump().get(key) != value]
    if mismatches:
        raise ValueError("prerequisite task binding mismatch: " + ",".join(mismatches))


class BoundResultV1(ContractModel):
    schema_version: Literal[1]
    research_plan_version: int = Field(ge=1, strict=True)
    binding: TaskBindingV1
    expected_skill: ClassVar[str]
    expected_phase: ClassVar[str | None] = None

    @model_validator(mode="after")
    def validate_result_identity(self) -> BoundResultV1:
        if (self.binding.schema_id != type(self).__name__
                or self.binding.skill_id != self.expected_skill
                or self.binding.phase != self.expected_phase
                or self.research_plan_version != self.binding.directive_version):
            raise ValueError("result schema/skill/phase/directive binding mismatch")
        return self


class DirectiveEthicsResultV1(BoundResultV1):
    expected_skill = "directive_ethics"
    verdict: EthicsVerdict
    reason: Text

    @model_validator(mode="after")
    def directive_only(self) -> DirectiveEthicsResultV1:
        if (self.binding.hypothesis_id is not None or self.binding.root_slot_id is not None
                or self.binding.slot_id is not None or self.binding.redesign_of is not None):
            raise ValueError("Directive Ethics is not candidate or slot Ethics")
        return self


class CandidateEthicsResultV1(BoundResultV1):
    expected_skill = "candidate_ethics"
    verdict: EthicsVerdict
    reason: Text

    @model_validator(mode="after")
    def candidate_only(self) -> CandidateEthicsResultV1:
        if self.binding.hypothesis_id is None or self.binding.slot_id is None:
            raise ValueError("Candidate Ethics requires exact content and original slot")
        return self


class RootQueryPlanResultV1(BoundResultV1):
    expected_skill = "root_literature_review"
    expected_phase = "QUERY_PLAN_V1"
    phase: Literal["QUERY_PLAN_V1"] = "QUERY_PLAN_V1"
    queries: tuple[Text, ...] = Field(min_length=1, max_length=3)
    rationale: Text

    @model_validator(mode="after")
    def query_scope(self) -> RootQueryPlanResultV1:
        if self.binding.root_slot_id is None:
            raise ValueError("query plan requires a root slot")
        canonical = [" ".join(q.split()) for q in self.queries]
        if len(set(canonical)) != len(canonical):
            raise ValueError("duplicate canonical query")
        if self.binding.skill_version in {"0.2.0", "0.3.0", "0.4.0"}:
            from co_scientist.domain.pubmed_query_planning import validate_queries

            validate_queries(self.queries, revision="pubmed-query-planning-v3"
                             if self.binding.skill_version in {"0.3.0", "0.4.0"} else "pubmed-query-planning-v2")
        return self


class SourceRecordV1(ContractModel):
    """Locally validated actual source snapshot; never a model citation claim."""

    source_id: Text
    snapshot_id: Text
    title: Text
    exact_text: Annotated[str, StringConstraints(strict=True, min_length=1)]
    content_hash: Sha
    raw_artifact_id: Text
    raw_hash: Sha
    content_level: Literal["METADATA_ONLY", "ABSTRACT"]

    @model_validator(mode="after")
    def source_integrity(self) -> SourceRecordV1:
        if text_hash(self.exact_text) != self.content_hash:
            raise ValueError("source content hash mismatch")
        return self


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_set_hash(sources: Sequence[SourceRecordV1]) -> str:
    return protocol_hash([source.model_dump(mode="json") for source in sources])


class GroundingOutcomeV1(ContractModel):
    state: Literal["SUCCESS_NONEMPTY", "SEARCHED_EMPTY", "PARTIAL", "GROUNDING_UNAVAILABLE"]
    prescribed_queries: int = Field(ge=1, le=3, strict=True)
    completed_queries: int = Field(ge=0, le=3, strict=True)
    total_returned: int = Field(ge=0, strict=True)
    usable_source_ids: tuple[Text, ...]
    omissions: tuple[Text, ...] = ()
    scope: Literal["BOUNDED_PUBMED_SCOPE"] = "BOUNDED_PUBMED_SCOPE"

    @model_validator(mode="after")
    def honest_outcome(self) -> GroundingOutcomeV1:
        if (self.completed_queries > self.prescribed_queries
                or len(set(self.usable_source_ids)) != len(self.usable_source_ids)
                or len(self.usable_source_ids) > min(30, self.total_returned)):
            raise ValueError("invalid grounding counts/source identities")
        complete = self.completed_queries == self.prescribed_queries
        if self.state == "SEARCHED_EMPTY" and (
            not complete or self.total_returned or self.usable_source_ids or self.omissions
        ):
            raise ValueError("SEARCHED_EMPTY requires successful actual zero-result scope")
        if self.state == "SUCCESS_NONEMPTY" and (
            not complete or not self.usable_source_ids or self.omissions
        ):
            raise ValueError("SUCCESS_NONEMPTY requires complete usable source scope")
        if self.state == "PARTIAL" and not self.omissions:
            raise ValueError("PARTIAL must document missing/failed work")
        if self.state == "GROUNDING_UNAVAILABLE" and self.usable_source_ids:
            raise ValueError("unavailable grounding cannot carry a usable subset")
        return self

    @property
    def generation_permitted(self) -> bool:
        return self.state in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"} or (
            self.state == "PARTIAL" and bool(self.usable_source_ids)
        )


class RootRetrievalResultV1(BoundResultV1):
    expected_skill = "root_retrieval"
    origin: Literal["RETRIEVER_RESPONSE"]
    request_key: Sha
    completed_result_id: Sha
    external_call_id: Text
    raw_artifact_id: Text
    raw_hash: Sha
    completed_at: Text
    returned_source_ids: tuple[Text, ...]
    sources: tuple[SourceRecordV1, ...] = Field(max_length=30)
    outcome: GroundingOutcomeV1
    reused_from_external_call_id: Text | None = None

    @model_validator(mode="after")
    def actual_source_scope(self) -> RootRetrievalResultV1:
        ids = tuple(s.source_id for s in self.sources)
        if (self.binding.root_slot_id is None or self.binding.plan_hash is None
                or self.binding.source_set_hash != source_set_hash(self.sources)
                or self.outcome.total_returned != len(self.returned_source_ids)
                or self.outcome.usable_source_ids != ids
                or any(i not in self.returned_source_ids for i in ids)):
            raise ValueError("retrieval/source/outcome binding mismatch")
        record = self.model_dump(mode="json", exclude={"completed_result_id", "binding",
                                                       "reused_from_external_call_id"})
        if protocol_hash(record) != self.completed_result_id:
            raise ValueError("completed retrieval result hash mismatch")
        if self.reused_from_external_call_id is not None and (
            self.reused_from_external_call_id != self.external_call_id
            or self.outcome.state not in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"}
        ):
            raise ValueError("only completed identity-valid retrieval may be reused")
        return self


def canonical_request_key(*, query: str, content_mode: Literal["metadata", "abstracts"],
                          limit: int = 20) -> str:
    if not query.strip() or not 1 <= limit <= 20:
        raise ValueError("invalid bounded root request")
    return protocol_hash({"version": "pubmed-root-request-key-v1", "backend": "pubmed",
        "backend_version": "pubmed-root-grounding-v1", "query": " ".join(query.split()),
        "content_mode": content_mode, "limit": limit, "pages": 1,
        "scope": "BOUNDED_PUBMED_SCOPE"})


class RootRetrievalResultV2(ContractModel):
    """Request identity is immutable; completed source scope is a separate fact.

    V1 is deliberately not migrated, coerced or selected as a fallback.
    """

    schema_version: Literal[2]
    research_plan_version: int = Field(ge=1, strict=True)
    binding: RetrievalRequestBindingV2
    origin: Literal["RETRIEVER_RESPONSE"]
    request_key: Sha
    completed_result_id: Sha
    external_call_id: Text
    raw_artifact_id: Text
    raw_hash: Sha
    completed_at: Text
    returned_source_ids: tuple[Text, ...]
    sources: tuple[SourceRecordV1, ...] = Field(max_length=30)
    source_set_hash: Sha
    outcome: GroundingOutcomeV1
    reused_from_external_call_id: Text | None = None

    @model_validator(mode="after")
    def completed_scope(self) -> RootRetrievalResultV2:
        ids = tuple(s.source_id for s in self.sources)
        if (self.research_plan_version != self.binding.directive_version
                or self.source_set_hash != source_set_hash(self.sources)
                or len(set(ids)) != len(ids)
                or self.outcome.total_returned != len(self.returned_source_ids)
                or self.outcome.usable_source_ids != ids
                or any(i not in self.returned_source_ids for i in ids)):
            raise ValueError("retrieval completed source-scope identity mismatch")
        record = self.model_dump(mode="json", exclude={"completed_result_id", "binding",
                                                       "reused_from_external_call_id"})
        if protocol_hash(record) != self.completed_result_id:
            raise ValueError("completed retrieval result hash mismatch")
        if self.reused_from_external_call_id is not None and (
            self.reused_from_external_call_id != self.external_call_id
            or self.outcome.state not in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"}
        ):
            raise ValueError("only completed identity-valid retrieval may be reused")
        return self


def canonical_artifact_hash(value: object) -> str:
    """Accept the two recorded ArtifactRef encodings, never arbitrary prefixes."""
    if not isinstance(value, str):
        raise TypeError("invalid ArtifactRef SHA-256")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid ArtifactRef SHA-256")
    return "sha256:" + digest


class RootLiteratureReviewResultV1(BoundResultV1):
    expected_skill = "root_literature_review"
    expected_phase = "SOURCE_REVIEW_V1"
    phase: Literal["SOURCE_REVIEW_V1"] = "SOURCE_REVIEW_V1"
    reviewed_source_ids: tuple[Text, ...]
    scoped_empty: bool
    review: Text

    @model_validator(mode="after")
    def source_scope(self) -> RootLiteratureReviewResultV1:
        if (self.binding.root_slot_id is None or self.binding.source_set_hash is None
                or self.binding.plan_hash is None
                or self.scoped_empty != (not self.reviewed_source_ids)
                or len(set(self.reviewed_source_ids)) != len(self.reviewed_source_ids)):
            raise ValueError("source review requires exact scoped sources or explicit empty review")
        return self


class CandidateProposalV1(ContractModel):
    hypothesis_id: Text
    content_id: Text
    title: Text
    hypothesis: Text
    mechanism: tuple[Text, ...] = Field(min_length=1)
    assumptions: tuple[Text, ...] = ()
    predictions: tuple[Text, ...] = Field(min_length=1)
    falsifiers: tuple[Text, ...] = Field(min_length=1)


class GroundedGenerationResultV1(BoundResultV1):
    expected_skill = "generation"
    candidate: CandidateProposalV1

    @model_validator(mode="after")
    def grounded_slot(self) -> GroundedGenerationResultV1:
        if (self.binding.slot_id is None or self.binding.generation_input_hash is None
                or self.binding.source_set_hash is None
                or self.binding.hypothesis_id is not None
                or self.candidate.hypothesis_id == self.binding.redesign_of):
            raise ValueError("Generation requires frozen input/slot and fresh proposal identity")
        return self


class BaselineReflectionResultV1(BoundResultV1):
    expected_skill = "reflection"
    critiques: tuple[Text, ...] = Field(min_length=1)
    plausibility: Text
    prior_research: Text
    testability: Text
    originality: Text
    unjustified_complexity: Text

    @model_validator(mode="after")
    def content_scope(self) -> BaselineReflectionResultV1:
        if self.binding.hypothesis_id is None:
            raise ValueError("Reflection requires exact candidate content")
        return self


class BaselineRankingResultV1(BoundResultV1):
    """Science preference only; all participant/rating identity is frozen input."""

    expected_skill = "ranking"
    decision: Literal["decisive", "inconclusive", "invalid", "needs_more_evidence", "tie", "abstain", "cannot_judge"]
    winner_slot: Literal[1, 2] | None = None
    dimension_reasons: dict[Text, Text]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def decisive_winner(self) -> BaselineRankingResultV1:
        if (self.decision == "decisive") != (self.winner_slot is not None):
            raise ValueError("only a decisive comparison may name a winner")
        return self


class BaselineEvolutionResultV1(BoundResultV1):
    """Minimal offspring proposal, without mandatory new bridge or claim audit."""

    expected_skill = "population_evolution"
    operator: Literal["crossover", "mutation"]
    candidate: CandidateProposalV1
    rationale: Text
    parent_contributions: tuple[Text, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def parentage(self) -> BaselineEvolutionResultV1:
        count = 2 if self.operator == "crossover" else 1
        if (len(self.binding.scientific_parent_ids) != count
                or len(self.parent_contributions) != count
                or self.candidate.hypothesis_id in self.binding.scientific_parent_ids
                or self.candidate.hypothesis_id == self.binding.redesign_of):
            raise ValueError("offspring requires fresh identity and distinct frozen scientific parents")
        return self


EVOLUTION_OUTPUT_REVISION = "evolution-per-parent-output-v1"
EVOLUTION_OUTPUT_INSTRUCTION = (
    "parent_contributions is a per-SCIENTIFIC-PARENT array, not a list of ideas or feedback sources. "
    "Mutation requires exactly ONE entry for its ONE frozen scientific parent. "
    "Crossover requires exactly TWO entries in the order of its TWO distinct frozen scientific parents. "
    "Identify the corresponding frozen parent in each entry. Combine ALL contributions from that parent "
    "and ALL critique-driven changes for that parent into the SAME entry; preserve their content. "
    "Reflection critiques are feedback on a parent, never another scientific parent or another entry. "
    "Do not invent parents, substitute identities, omit substantive contributions or change scientific inputs."
)


def evolution_output_contract() -> dict[str, str]:
    """Opt-in provider clarification, not a new local result or scientific policy."""
    return {"version": EVOLUTION_OUTPUT_REVISION, "instruction": EVOLUTION_OUTPUT_INSTRUCTION,
            "instruction_hash": protocol_hash(EVOLUTION_OUTPUT_INSTRUCTION)}


class RootSlotV1(ContractModel):
    version: Literal["ideation-root-slot-v1"] = "ideation-root-slot-v1"
    run_id: Text
    directive_id: Text
    directive_hash: Sha
    slot_id: Literal["root-slot-0", "root-slot-1", "root-slot-2", "root-slot-3"]
    query_plan_task_id: Text
    source_review_task_id: Text
    generation_input_id: Text


class SafeRedesignV1(ContractModel):
    version: Literal["ideation-safe-redesign-v1"] = "ideation-safe-redesign-v1"
    slot_id: Text
    redesign_of: Text
    redesign_of_content_hash: Sha
    new_hypothesis_id: Text
    new_content_hash: Sha
    scientific_parent_ids: tuple[Text, ...]
    original_scientific_parent_ids: tuple[Text, ...]
    source_ethics_result_id: Text
    source_ethics_verdict: Literal["REJECT"]
    redesign_count: Literal[1]

    @model_validator(mode="after")
    def same_scientific_slot(self) -> SafeRedesignV1:
        if (self.scientific_parent_ids != self.original_scientific_parent_ids
                or self.new_hypothesis_id == self.redesign_of
                or self.new_content_hash == self.redesign_of_content_hash):
            raise ValueError("redesign must keep scientific parents and create fresh content")
        return self


class OrderedCritiqueV1(ContractModel):
    review_id: Text
    stage: Text
    source_result_id: Text
    event_id: Text
    event_sequence: int = Field(ge=1, strict=True)
    hypothesis_id: Text
    content_hash: Sha
    critique: Text
    optional_audit: bool = False


def ordered_critiques(values: Sequence[OrderedCritiqueV1], *, hypothesis_id: str,
                     content_hash: str) -> tuple[OrderedCritiqueV1, ...]:
    filtered = [v for v in values if v.hypothesis_id == hypothesis_id
                and v.content_hash == content_hash and not v.optional_audit]
    if len({(v.event_id, v.review_id) for v in filtered}) != len(filtered):
        raise ValueError("duplicate critique event/review identity")
    return tuple(sorted(filtered, key=lambda v: (v.event_sequence, v.event_id, v.review_id)))


class ProviderCapabilityV1(ContractModel):
    adapter: Literal["native-json"] = "native-json"
    provider: Text
    model: Text
    api: Text
    thinking_mode: Text
    capability_id: Text
    status: Literal["CAPABILITY_UNVERIFIED", "OFFLINE_FAKE_ONLY"] = "CAPABILITY_UNVERIFIED"

    @model_validator(mode="after")
    def fake_is_not_live_capability(self) -> ProviderCapabilityV1:
        if self.status == "OFFLINE_FAKE_ONLY" and self.provider != "fake":
            raise ValueError("fake capability cannot approve a real provider")
        return self


class PrerequisitePolicyV1(ContractModel):
    version: Literal["ideation-prerequisites-v1"] = "ideation-prerequisites-v1"
    boundary_version: Literal["ideation-core-boundary-v2"] = "ideation-core-boundary-v2"
    readiness_version: Literal["ideation-core-readiness-v2"] = "ideation-core-readiness-v2"
    activation: Literal["CONTRACTS_ONLY_B2_A"] = "CONTRACTS_ONLY_B2_A"
    generation_params_version: Literal["baseline-generation-params-v1"] = (
        "baseline-generation-params-v1"
    )
    root_slots: Literal[4] = 4
    generation_temperature: float = Field(default=1.6, strict=True)
    simplicity_instruction: Literal["Prefer the simplest mechanistically explicit, testable hypothesis."] = (
        "Prefer the simplest mechanistically explicit, testable hypothesis."
    )
    min_queries: Literal[1] = 1
    max_queries: Literal[3] = 3
    max_pmids_per_query: Literal[20] = 20
    max_selected_sources: Literal[30] = 30
    pages_per_query: Literal[1] = 1
    request_timeout_seconds: Literal[30] = 30
    hidden_retries: Literal[0] = 0
    safe_redesign_max: Literal[1] = 1
    generation_input_max_bytes: int = Field(default=65536, ge=1, strict=True)
    generation_input_max_tokens: int = Field(default=16384, ge=1, strict=True)
    capability: ProviderCapabilityV1
    live_capabilities: tuple[ProviderCapabilityV1, ...] = Field(default=(), max_length=0)

    @model_validator(mode="after")
    def exact_generation_temperature(self) -> PrerequisitePolicyV1:
        if self.generation_temperature != 1.6:
            raise ValueError("Generation temperature must equal 1.6")
        return self


class PrerequisiteExecutionPolicyV2(ContractModel):
    """Explicit functional offline revision; no production capability is asserted."""

    version: Literal["ideation-prerequisites-v2"] = "ideation-prerequisites-v2"
    activation: Literal["OFFLINE_FUNCTIONAL_B2"] = "OFFLINE_FUNCTIONAL_B2"
    boundary_version: Literal["ideation-core-boundary-v2"] = "ideation-core-boundary-v2"
    readiness_version: Literal["ideation-operation-readiness-v3"] = "ideation-operation-readiness-v3"
    retrieval_contract: Literal["RootRetrievalResultV2@2"] = "RootRetrievalResultV2@2"
    completion_contract: Literal["retrieval-completion-fact-v2"] = "retrieval-completion-fact-v2"
    request_binding: Literal["retrieval-request-binding-v2"] = "retrieval-request-binding-v2"
    policy: PrerequisitePolicyV1


class PrerequisiteFactV1(ContractModel):
    """Additive event payload; task/result authority checked at projection boundary."""

    version: Literal["ideation-prerequisite-fact-v1"] = "ideation-prerequisite-fact-v1"
    binding: TaskBindingV1
    source_result_id: Text
    external_call_id: Text
    raw_artifact_id: Text
    raw_hash: Sha
    result: dict[str, Any]


class RetrievalCompletionFactV2(ContractModel):
    version: Literal["retrieval-completion-fact-v2"] = "retrieval-completion-fact-v2"
    binding: RetrievalRequestBindingV2
    source_result_id: Text
    external_call_id: Text
    raw_artifact_id: Text
    raw_hash: Sha
    result: dict[str, Any]


class RetrievalReuseV2(ContractModel):
    """A new slot's request binding, not a fabricated fresh external result."""

    version: Literal["root-retrieval-reuse-v2"] = "root-retrieval-reuse-v2"
    request_binding: RetrievalRequestBindingV2
    original_source_result_id: Text
    original_completed_result_id: Sha
    result: RootRetrievalResultV2

    @model_validator(mode="after")
    def exact_reuse(self) -> RetrievalReuseV2:
        validate_binding(self.request_binding, self.result.binding)
        if (self.result.completed_result_id != self.original_completed_result_id
                or self.result.reused_from_external_call_id != self.result.external_call_id
                or self.result.outcome.state not in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"}):
            raise ValueError("reuse requires exact successful original completion identity")
        return self


def bind_completed_retrieval(original: RootRetrievalResultV2, *,
    request_binding: RetrievalRequestBindingV2, source_result_id: str,
    request_key: str) -> RetrievalReuseV2:
    if (original.request_key != request_key
            or original.outcome.state not in {"SUCCESS_NONEMPTY", "SEARCHED_EMPTY"}
            or any(getattr(original.binding, k) != getattr(request_binding, k)
                   for k in ("run_id", "directive_id", "directive_hash", "directive_version",
                             "profile_hash", "creation_epoch"))):
        raise ValueError("completed-result cache identity/scope mismatch")
    cloned = original.model_dump(mode="json")
    cloned.update(binding=request_binding.model_dump(mode="json"),
                  reused_from_external_call_id=original.external_call_id)
    return RetrievalReuseV2(request_binding=request_binding,
        original_source_result_id=source_result_id,
        original_completed_result_id=original.completed_result_id,
        result=RootRetrievalResultV2.model_validate(cloned))


def validate_fact_result(fact: PrerequisiteFactV1 | RetrievalCompletionFactV2,
                         schema: str) -> BoundResultV1 | RootRetrievalResultV2:
    """Shape/binding validation shared by event validation and durable replay.

    This does not make source_result_id authoritative or prove raw existence.
    No HTTP raw is substituted for the domain-result artifact.
    """
    if fact.binding.schema_id != schema:
        raise ValueError("event/result schema mismatch")
    result = RESULT_MODELS[schema].model_validate(fact.result)
    validate_binding(fact.binding, result.binding)
    if isinstance(result, RootRetrievalResultV1 | RootRetrievalResultV2) and any(
        getattr(fact, name) != getattr(result, name)
        for name in ("external_call_id", "raw_artifact_id", "raw_hash")
    ):
        raise ValueError("retrieval raw provenance mismatch")
    return result


def source_review_retrieval(inputs: Mapping[str, Any], binding: TaskBindingV1
                           ) -> RootRetrievalResultV1 | RootRetrievalResultV2:
    """Resolve visible sources only from the exact local frozen task snapshot.

    B2-C must build model_input.retrieval_result from an applied durable retrieval,
    never from review output. B2-A defines/validates this input boundary only.
    """
    model_input = inputs.get("model_input")
    if not isinstance(model_input, Mapping) or "retrieval_result" not in model_input:
        raise ValueError("source review missing frozen retrieval result")
    supplied = model_input["retrieval_result"]
    if not isinstance(supplied, Mapping):
        raise TypeError("missing frozen retrieval schema identity")
    request = supplied.get("binding", {})
    if not isinstance(request, Mapping):
        raise TypeError("missing frozen retrieval request identity")
    identity = (request.get("schema_id"), supplied.get("schema_version"))
    if identity == ("RootRetrievalResultV1", 1):
        retrieval: RootRetrievalResultV1 | RootRetrievalResultV2 = (
            RootRetrievalResultV1.model_validate(supplied))
    elif identity == ("RootRetrievalResultV2", 2):
        retrieval = RootRetrievalResultV2.model_validate(supplied)
    else:
        raise ValueError("unsupported frozen retrieval schema/version; no fallback")
    for name in ("run_id", "directive_id", "directive_version", "directive_hash",
                 "profile_hash", "creation_epoch", "root_slot_id", "plan_hash"):
        if getattr(binding, name) != getattr(retrieval.binding, name):
            raise ValueError("source review retrieval binding mismatch: " + name)
    if not retrieval.outcome.generation_permitted:
        raise ValueError("source review unavailable retrieval scope")
    if len({s.source_id for s in retrieval.sources}) != len(retrieval.sources):
        raise ValueError("source review duplicate frozen source identity")
    # Recompute from exact validated bytes, never trust a model inventory hash.
    if binding.source_set_hash != source_set_hash(retrieval.sources):
        raise ValueError("source review frozen source-set identity mismatch")
    return retrieval


def validate_source_review(result: RootLiteratureReviewResultV1,
                           inputs: Mapping[str, Any]) -> None:
    binding = validate_prerequisite_inputs(inputs)
    validate_binding(binding, result.binding)
    if not isinstance(binding, TaskBindingV1):
        raise TypeError("source review task selected a retrieval-only binding")
    retrieval = source_review_retrieval(inputs, binding)
    visible = {source.source_id for source in retrieval.sources}
    reviewed = set(result.reviewed_source_ids)
    if reviewed - visible:
        raise ValueError("source review references unavailable sources: "
                         + ",".join(sorted(reviewed - visible)))
    if visible - reviewed:
        # A partial proposal is preservable as raw/result, but not a completed fact.
        raise ValueError("source review incomplete coverage; missing_source_ids="
                         + ",".join(sorted(visible - reviewed)))
    if result.scoped_empty != (retrieval.outcome.state == "SEARCHED_EMPTY"):
        raise ValueError("source review empty scope is not actual successful zero retrieval")


RESULT_MODELS: Mapping[str, type[BoundResultV1 | RootRetrievalResultV2]] = {
    m.__name__: m for m in (BaselineRankingResultV1, BaselineEvolutionResultV1,
        DirectiveEthicsResultV1, RootQueryPlanResultV1,
        RootRetrievalResultV1, RootLiteratureReviewResultV1, GroundedGenerationResultV1,
        CandidateEthicsResultV1, BaselineReflectionResultV1, RootRetrievalResultV2)
}
EVENT_RESULTS: Mapping[str, str] = {
    "BaselineRankingRecordedV1": "BaselineRankingResultV1",
    "BaselineEvolutionRecordedV1": "BaselineEvolutionResultV1",
    "DirectiveEthicsRecordedV1": "DirectiveEthicsResultV1",
    "RootReviewPlannedV1": "RootQueryPlanResultV1",
    "RootRetrievalOutcomeRecordedV1": "RootRetrievalResultV1",
    "RootSourceReviewRecordedV1": "RootLiteratureReviewResultV1",
    "CandidateEthicsRecordedV1": "CandidateEthicsResultV1",
    "GroundedGenerationRecordedV1": "GroundedGenerationResultV1",
    "BaselineReflectionRecordedV1": "BaselineReflectionResultV1",
}
EVENT_RESULTS_V2: Mapping[str, str] = {
    "RootRetrievalOutcomeRecordedV2": "RootRetrievalResultV2",
}


def validate_prerequisite_inputs(inputs: Mapping[str, Any]
                                ) -> TaskBindingV1 | RetrievalRequestBindingV2:
    """Bind exact frozen operation input without trusting a provider proposal.

    The outer task snapshot also includes this binding; input_hash covers only
    model_input to avoid a self-referential hash. Execution wiring is deferred.
    """
    supplied = inputs.get("ideation_task_binding")
    if not isinstance(supplied, Mapping):
        raise TypeError("missing explicit prerequisite binding")
    if supplied.get("version") == "ideation-task-binding-v1":
        binding: TaskBindingV1 | RetrievalRequestBindingV2 = TaskBindingV1.model_validate(supplied)
    elif supplied.get("version") == "retrieval-request-binding-v2":
        binding = RetrievalRequestBindingV2.model_validate(supplied)
    else:
        raise ValueError("unsupported prerequisite binding version; no fallback")
    model_input = inputs.get("model_input")
    if not isinstance(model_input, Mapping) or not model_input:
        raise ValueError("missing frozen prerequisite model input")
    if protocol_hash(dict(model_input)) != binding.input_hash:
        raise ValueError("prerequisite model input hash mismatch")
    if "evolution_output_contract" in inputs:
        if (binding.schema_id != "BaselineEvolutionResultV1"
                or inputs["evolution_output_contract"] != evolution_output_contract()):
            raise ValueError("unknown or mismatched opt-in Evolution output contract")
        operator = model_input.get("operator")
        count = {"mutation": 1, "crossover": 2}.get(operator) if isinstance(operator, str) else None
        parents = model_input.get("parents", [])
        if (count is None or len(binding.scientific_parent_ids) != count
                or tuple(p.get("hypothesis_id") for p in parents) != binding.scientific_parent_ids):
            raise ValueError("Evolution operator/scientific parent input identity mismatch")
    if binding.schema_id == "RootLiteratureReviewResultV1":
        if not isinstance(binding, TaskBindingV1):
            raise ValueError("source review requires an explicit source-review binding")
        source_review_retrieval(inputs, binding)
    return binding


class RootGroundingFrozenV1(ContractModel):
    version: Literal["root-grounding-frozen-v1"] = "root-grounding-frozen-v1"
    binding: TaskBindingV1
    source_retrieval_result_id: Text
    source_review_result_id: Text
    generation_input_id: Text
    sources: tuple[SourceRecordV1, ...] = Field(max_length=30)
    outcome: GroundingOutcomeV1
    exact_model_input: str = Field(min_length=1, strict=True)
    exact_model_input_hash: Sha

    @model_validator(mode="after")
    def exact_source_input(self) -> RootGroundingFrozenV1:
        if (self.binding.root_slot_id is None
                or self.binding.source_set_hash != source_set_hash(self.sources)
                or tuple(s.source_id for s in self.sources) != self.outcome.usable_source_ids
                or len({s.source_id for s in self.sources}) != len(self.sources)
                or text_hash(self.exact_model_input) != self.exact_model_input_hash
                or self.binding.generation_input_hash != self.exact_model_input_hash):
            raise ValueError("frozen grounding source/input identity mismatch")
        return self


class IdeationSlotResolvedV1(ContractModel):
    version: Literal["ideation-slot-resolved-v1"] = "ideation-slot-resolved-v1"
    binding: TaskBindingV1
    source_event_ids: tuple[Text, ...] = Field(min_length=1)
    reason: Text
    technical_incomplete: bool

    @model_validator(mode="after")
    def bound_slot(self) -> IdeationSlotResolvedV1:
        if self.binding.slot_id is None or len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("slot resolution requires unique source facts and slot identity")
        return self


class IdeationSlotResolvedV2(ContractModel):
    version: Literal["ideation-slot-resolved-v2"] = "ideation-slot-resolved-v2"
    binding: RetrievalRequestBindingV2
    source_event_ids: tuple[Text, ...] = Field(min_length=1)
    reason: Text
    technical_incomplete: bool

    @model_validator(mode="after")
    def bound_slot(self) -> IdeationSlotResolvedV2:
        if self.binding.slot_id is None or len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("slot resolution requires unique source facts and slot identity")
        return self


def validate_prerequisite_fact(event: DomainEvent,
    expected_tasks: Mapping[str, TaskBindingV1 | RetrievalRequestBindingV2], *,
    expected_task_inputs: Mapping[str, Mapping[str, Any]] | None = None,
    durable_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> BoundResultV1 | RootRetrievalResultV2:
    """Only exact task/result-bound committed facts are projection authority.

    The caller must load task inputs and AgentResult envelopes from the durable
    store, not from event/provider self-report. Missing records fail closed.
    Application wiring/loading remains B2-B/C work; this pure validator does
    not query a DB, dispatch, or manufacture authority/usage/cost.
    """
    if event.event_type in EVENT_RESULTS and event.schema_version == 1:
        fact: PrerequisiteFactV1 | RetrievalCompletionFactV2 = (
            PrerequisiteFactV1.model_validate(event.payload))
        schema = EVENT_RESULTS[event.event_type]
    elif event.event_type in EVENT_RESULTS_V2 and event.schema_version == 2:
        fact = RetrievalCompletionFactV2.model_validate(event.payload)
        schema = EVENT_RESULTS_V2[event.event_type]
    else:
        raise ValueError("unknown prerequisite event/version")
    expected = expected_tasks.get(fact.binding.task_id)
    if expected is None or event.run_id != fact.binding.run_id:
        raise ValueError("missing durable prerequisite task authority")
    validate_binding(expected, fact.binding)
    result = validate_fact_result(fact, schema)
    durable = (durable_results or {}).get(fact.source_result_id)
    if durable is None:
        raise ValueError("missing durable result authority")
    fields = {"result_id": fact.source_result_id, "run_id": expected.run_id,
        "task_id": expected.task_id, "attempt": expected.attempt,
        "external_call_id": fact.external_call_id, "skill_id": expected.skill_id,
        "skill_version": expected.skill_version, "output_schema_id": schema,
        "output_schema_version": expected.schema_version, "provider": expected.provider,
        "model_or_tool": expected.model, "prompt_hash": expected.prompt_hash,
        "research_plan_version": expected.directive_version}
    if any(durable.get(key) != value for key, value in fields.items()):
        raise ValueError("durable result authority identity mismatch")
    # Envelope completion is independent of GroundingOutcome.PARTIAL: a
    # completed retrieval may honestly contain a usable subset and omissions.
    # Incomplete envelopes remain diagnostic data, never completed fact authority.
    if durable.get("status") != "completed":
        raise ValueError("durable result authority requires completed envelope")
    raw_ref = durable.get("raw_artifact_ref")
    if (not isinstance(raw_ref, Mapping) or raw_ref.get("path") != fact.raw_artifact_id
            or canonical_artifact_hash(raw_ref.get("sha256")) != fact.raw_hash):
        raise ValueError("durable result authority raw provenance mismatch")
    durable_payload = RESULT_MODELS[schema].model_validate(durable.get("payload"))
    if durable_payload != result:
        raise ValueError("durable result authority payload mismatch")
    inputs = (expected_task_inputs or {}).get(expected.task_id)
    if inputs is None:
        raise ValueError("missing durable prerequisite task input authority")
    validate_binding(expected, validate_prerequisite_inputs(inputs))
    if durable.get("input_snapshot_hash") != protocol_hash(dict(inputs)).removeprefix("sha256:"):
        raise ValueError("durable result authority input snapshot mismatch")
    if isinstance(result, RootLiteratureReviewResultV1):
        validate_source_review(result, inputs)
    return result


class OperationReadinessV2(ContractModel):
    version: Literal["ideation-core-readiness-v2"] = "ideation-core-readiness-v2"
    operation: Operation
    state: Literal["READY", "NOT_READY"]
    missing: tuple[Text, ...]
    source_sequences: tuple[int, ...]
    identity_hash: Sha
    production_dispatch_enabled: Literal[False] = False


class OperationReadinessV3(ContractModel):
    version: Literal["ideation-operation-readiness-v3"] = "ideation-operation-readiness-v3"
    operation: Operation
    state: Literal["READY", "NOT_READY"]
    missing: tuple[Text, ...]
    source_sequences: tuple[int, ...]
    identity_hash: Sha
    live_dispatch_enabled: Literal[False] = False


def project_operation_readiness_v3(*, operation: Operation,
    expected: TaskBindingV1 | RetrievalRequestBindingV2, events: Sequence[DomainEvent],
    expected_tasks: Mapping[str, TaskBindingV1 | RetrievalRequestBindingV2],
    expected_task_inputs: Mapping[str, Mapping[str, Any]],
    durable_results: Mapping[str, Mapping[str, Any]],
) -> OperationReadinessV3:
    """Version-bound operation prerequisites, not a global all-stages self-lock."""
    facts = []
    for event in events:
        if event.event_type not in EVENT_RESULTS and event.event_type not in EVENT_RESULTS_V2:
            continue
        result = validate_prerequisite_fact(event, expected_tasks,
            expected_task_inputs=expected_task_inputs, durable_results=durable_results)
        if any(getattr(result.binding, field) != getattr(expected, field) for field in (
            "run_id", "directive_id", "directive_version", "directive_hash", "profile_hash",
            "creation_epoch")):
            raise ValueError("readiness authoritative fact profile/directive/epoch mismatch")
        facts.append((event, result))
    # Reuse does not invent a new AgentResult or raw artifact. Its authority is
    # an already validated, durably completed original result plus a new plan.
    originals = {e.payload["source_result_id"]: r for e, r in facts
                 if isinstance(r, RootRetrievalResultV2)}
    for event in events:
        if event.event_type != "RootRetrievalReusedV2":
            continue
        if event.schema_version != 2:
            raise ValueError("unsupported retrieval reuse version")
        reuse = RetrievalReuseV2.model_validate(event.payload)
        original = originals.get(reuse.original_source_result_id)
        if original is None:
            raise ValueError("reuse missing original durable completion authority")
        plans = [r for _, r in facts if isinstance(r, RootQueryPlanResultV1)
                 and r.binding.root_slot_id == reuse.request_binding.root_slot_id
                 and protocol_hash(r.model_dump(mode="json")) == reuse.request_binding.plan_hash]
        if len(plans) != 1:
            raise ValueError("reuse missing exact new-slot plan authority")
        expected_request = {"queries": list(plans[0].queries), "content_mode": "abstracts",
                            "limit": 20, "max_selected_sources": 30, "timeout_seconds": 30}
        expected_key = protocol_hash([canonical_request_key(query=q, content_mode="abstracts")
                                      for q in plans[0].queries])
        if (protocol_hash(expected_request) != reuse.request_binding.input_hash
                or expected_key != reuse.result.request_key):
            raise ValueError("reuse new request/query identity differs from original completion")
        rebound = bind_completed_retrieval(original, request_binding=reuse.request_binding,
            source_result_id=reuse.original_source_result_id, request_key=reuse.result.request_key)
        if rebound != reuse:
            raise ValueError("reused completed source/raw inventory changed")
        facts.append((event, reuse.result))
    missing = []
    if operation in {"RANKING", "EVOLUTION", "FINAL"}:
        missing.append("WAITING_FOR_BATCH3")
    if operation != "DIRECTIVE_ETHICS" and not any(
        isinstance(r, DirectiveEthicsResultV1) and r.verdict == "PASS" for _, r in facts):
        missing.append("directive_ethics")
    scoped = [(e, r) for e, r in facts if r.binding.root_slot_id == expected.root_slot_id]
    if operation in {"ROOT_RETRIEVAL", "ROOT_SOURCE_REVIEW", "ROOT_GROUNDING_FREEZE",
                     "ROOT_GENERATION", "SAFE_REDESIGN"} and not any(
        isinstance(r, RootQueryPlanResultV1) and protocol_hash(r.model_dump(mode="json"))
        == expected.plan_hash for _, r in scoped):
        missing.append("root_query_plan")
    if operation in {"ROOT_SOURCE_REVIEW", "ROOT_GROUNDING_FREEZE", "ROOT_GENERATION",
                     "SAFE_REDESIGN"} and not any(
        isinstance(r, RootRetrievalResultV2) and r.outcome.generation_permitted
        and r.source_set_hash == expected.source_set_hash for _, r in scoped):
        missing.append("completed_retrieval")
    if operation in {"ROOT_GROUNDING_FREEZE", "ROOT_GENERATION", "SAFE_REDESIGN"} and not any(
        isinstance(r, RootLiteratureReviewResultV1)
        and r.binding.source_set_hash == expected.source_set_hash for _, r in scoped):
        missing.append("source_review")
    if operation in {"ROOT_GENERATION", "SAFE_REDESIGN"}:
        freezes = [RootGroundingFrozenV1.model_validate(e.payload) for e in events
                   if e.event_type == "RootGroundingFrozenV1" and e.schema_version == 1]
        if not any(f.binding.slot_id == expected.slot_id
                   and f.binding.generation_input_hash == expected.generation_input_hash
                   and f.binding.source_set_hash == expected.source_set_hash for f in freezes):
            missing.append("frozen_generation_input")
    if operation == "REFLECTION" and not any(
        isinstance(r, CandidateEthicsResultV1) and r.verdict == "PASS"
        and r.binding.hypothesis_id == expected.hypothesis_id
        and r.binding.content_hash == expected.content_hash for _, r in facts):
        missing.append("candidate_ethics")
    if operation == "SAFE_REDESIGN" and not any(
        isinstance(r, CandidateEthicsResultV1) and r.verdict == "REJECT"
        and r.binding.hypothesis_id == expected.redesign_of
        and r.binding.slot_id == expected.slot_id for _, r in facts):
        missing.append("redesign_rejection")
    return OperationReadinessV3(operation=operation, state="NOT_READY" if missing else "READY",
        missing=tuple(missing), source_sequences=tuple(e.sequence for e, _ in facts),
        identity_hash=protocol_hash({"version": "ideation-operation-readiness-v3",
            "operation": operation, "expected": expected.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e, _ in facts], "missing": missing}))


def project_operation_readiness_v2(*, operation: Operation, expected: TaskBindingV1,
    events: Sequence[DomainEvent], expected_tasks: Mapping[str, TaskBindingV1],
    expected_task_inputs: Mapping[str, Mapping[str, Any]] | None = None,
    durable_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> OperationReadinessV2:
    """B2-A durable contract projection remains fail-closed until B2-B wiring.

Validated facts are reconstructed/audited but cannot turn this contract-only
activation into an executable operation. No flags/fixture PASS are authority.
"""
    sequences = []
    for event in events:
        if event.event_type not in EVENT_RESULTS:
            continue
        result = validate_prerequisite_fact(event, expected_tasks,
            expected_task_inputs=expected_task_inputs, durable_results=durable_results)
        if (result.binding.run_id != expected.run_id
                or result.binding.directive_id != expected.directive_id
                or result.binding.directive_hash != expected.directive_hash
                or result.binding.profile_hash != expected.profile_hash):
            raise ValueError("readiness fact directive/profile mismatch")
        sequences.append(event.sequence)
    missing = ("b2a_production_dispatch_unimplemented",)
    return OperationReadinessV2(operation=operation, state="NOT_READY", missing=missing,
        source_sequences=tuple(sequences), identity_hash=protocol_hash({
            "expected": expected.model_dump(mode="json"), "operation": operation,
            "events": [e.model_dump(mode="json") for e in events], "missing": missing}))
