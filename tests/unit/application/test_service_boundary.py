from pathlib import Path
from types import SimpleNamespace

from co_scientist.application.commands import CreateRun
from co_scientist.application.queries import GetRunStatus
from co_scientist.application.service import ApplicationService


class FakeSupervisor:
    def __init__(self) -> None:
        self.received_commands: list[str] = []

    def handle_command(self, command: object) -> SimpleNamespace:
        self.received_commands.append(type(command).__name__)
        return SimpleNamespace(run_id="r-1")


class FakeReadModel:
    def __init__(self) -> None:
        self.received_queries: list[str] = []

    def execute(self, query: object) -> dict[str, str]:
        self.received_queries.append(type(query).__name__)
        return {"run_id": "r-1", "state": "running"}


# Mutation caught: ApplicationService handling creation itself or exposing persistence.
def test_service_sends_commands_to_supervisor_without_exposing_repository() -> None:
    fake_supervisor = FakeSupervisor()
    service = ApplicationService(supervisor=fake_supervisor, read_model=FakeReadModel())

    result = service.execute(
        CreateRun(
            goal_file=Path("goal.yaml"),
            profile_file=Path("core.yaml"),
            provider="fake",
            data_dir=Path(".co-scientist"),
        )
    )

    assert result.run_id == "r-1"
    assert fake_supervisor.received_commands == ["CreateRun"]
    assert not hasattr(service, "database")


# Mutation caught: sending reads through the mutation handler instead of the read-model port.
def test_service_sends_queries_only_to_read_model() -> None:
    fake_supervisor = FakeSupervisor()
    read_model = FakeReadModel()
    service = ApplicationService(supervisor=fake_supervisor, read_model=read_model)

    result = service.query(GetRunStatus(run_id="r-1"))

    assert result == {"run_id": "r-1", "state": "running"}
    assert read_model.received_queries == ["GetRunStatus"]
    assert fake_supervisor.received_commands == []
