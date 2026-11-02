"""Two independently callable deterministic engineering modules, no science."""

from .contracts import CallResponse, ModuleResult
from .scheduler import Registry


def measure_text(inputs, calls):
    text = inputs.brief["question"]
    response = calls.execute(
        "measure",
        "deterministic/text-length-v1",
        {"text": text},
        lambda request: CallResponse({"length": len(request["text"])}),
    )
    return ModuleResult({"length": response.output["length"], "engineering_fixture": True})


def double_measurement(inputs, calls):
    length = inputs.previous_result["length"]
    response = calls.execute(
        "double",
        "deterministic/double-v1",
        {"value": length},
        lambda request: CallResponse({"value": request["value"] * 2}),
    )
    return ModuleResult({"doubled_length": response.output["value"], "engineering_fixture": True})


def registry():
    modules = Registry()
    modules.register("fixture.measure.v1", measure_text)
    modules.register("fixture.double.v1", double_measurement)
    return modules


def create_demo(store):
    project = store.create_project("W0 engineering fixture")
    revision = store.revise_brief(
        project,
        {
            "question": "engineering only",
            "background": "",
            "constraints": [],
            "materials": [],
        },
    )
    return store.create_run(
        revision, ["fixture.measure.v1", "fixture.double.v1"], policy_ref="engineering-fixture-v1"
    )
