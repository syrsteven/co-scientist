from co_scientist.domain.review import ReviewPolicy, ReviewStage
from co_scientist.supervisor.followups import derive_followup_intents


def test_generation_result_yields_supervisor_owned_initial_review_intent() -> None:
    intents = derive_followup_intents(
        event_type="HypothesisContentCreated",
        payload={"hypothesis_id": "h-1"},
        review_policy=ReviewPolicy(
            profile_id="minimal",
            required_before_admission=(ReviewStage.INITIAL,),
        ),
    )

    assert [intent.intent_type for intent in intents] == ["run_initial_review"]
    assert all(intent.created_by == "supervisor" for intent in intents)


def test_policy_adds_only_its_required_pre_admission_review_stages() -> None:
    intents = derive_followup_intents(
        event_type="HypothesisContentCreated",
        payload={"hypothesis_id": "h-1"},
        review_policy=ReviewPolicy(
            profile_id="paper_faithful",
            required_before_admission=(ReviewStage.FULL,),
        ),
    )

    assert [(intent.intent_type, intent.target_id) for intent in intents] == [
        ("run_initial_review", "h-1"),
        ("run_full_review", "h-1"),
    ]


def test_agent_recommendation_event_cannot_create_followup_work() -> None:
    intents = derive_followup_intents(
        event_type="AgentRecommendedActions",
        payload={"hypothesis_id": "h-1", "recommended_actions": ["run_deep_verification"]},
        review_policy=ReviewPolicy(profile_id="minimal"),
    )

    assert intents == ()
