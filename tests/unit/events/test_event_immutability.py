import pytest

from co_scientist.events.models import DomainEvent, NewEvent


@pytest.mark.parametrize(
    ("event_class", "event_kwargs"),
    [
        (
            DomainEvent,
            {
                "sequence": 1,
                "run_id": "r-1",
                "event_type": "Example",
            },
        ),
        (NewEvent, {"event_type": "Example"}),
    ],
)
def test_event_payload_is_deeply_immutable_and_json_serializable(
    event_class: type[DomainEvent] | type[NewEvent], event_kwargs: dict[str, object]
) -> None:
    event = event_class(
        **event_kwargs,
        payload={"nested": {"items": ["original"]}},
    )

    with pytest.raises(TypeError):
        event.payload["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["nested"]["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["nested"]["items"][0] = "changed"

    assert event.model_dump(mode="json")["payload"] == {
        "nested": {"items": ["original"]}
    }
