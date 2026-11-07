"""Read-only scientific projection. Counts never equate views/cards with studies."""

import json

from .background import BackgroundService
from .candidate_review import CandidateReviewService
from .generation import GenerationService
from .goal import GoalSlice
from .literature_runtime import LiteratureService
from .workspace_records import WorkspaceRecords


def workspace(store, run):
    row = store.one("SELECT * FROM research_runs WHERE run_id=?", (run,))
    for k in ("state", "config", "policies", "profiles"):
        row[k] = json.loads(row[k])
    background = BackgroundService(store).snapshot(run)
    literature = LiteratureService(store).history(run)
    generations = GenerationService(store).snapshot(run)
    reviews = CandidateReviewService(store).snapshot(run)
    actions = background["actions"]
    searches = [a for a in literature if a["request"]["kind"] == "search"]
    fetched = [
        a
        for a in literature
        if a["request"]["kind"] == "fetch"
        and (a.get("result") or {}).get("acquisition", {}).get("text")
    ]
    readings = [
        a
        for a in actions
        if a["operation"] == "P04" and (a.get("result") or {}).get("background_status") == "saved"
    ]
    views = BackgroundService(store).views(run)
    viewmap = {v["id"]: v for v in views}
    returned = {
        i["source_ref"]
        for a in searches
        for i in (a.get("result") or {}).get("acquisition", {}).get("items", [])
    }
    read_sources = {viewmap[a["input"]["source_view"]["id"]]["source_ref"] for a in readings}
    events = store.rows("SELECT * FROM research_events WHERE run_id=? ORDER BY id", (run,))
    for e in events:
        e["detail"] = json.loads(e["detail"])
    from .goal_diagnostics import inspect_goal
    return {
        "goal_issue": inspect_goal(store, run),
        "research": row,
        "goal": GoalSlice(store).snapshot(run),
        "background": background,
        "literature": literature,
        "generation": generations,
        "reviews": reviews,
        "events": events,
        "annotations": WorkspaceRecords(store).list(run),
        "annotation_targets": WorkspaceRecords(store).targets(run),
        "counts": {
            "planned_queries": sum(
                len(a["result"]["artifact"]["queries"])
                for a in actions
                if a["operation"] == "P03"
                and (a.get("result") or {}).get("background_status") == "saved"
            ),
            "executed_query_pages": sum(bool(a["attempts"]) for a in searches),
            "returned_records": sum(
                len((a.get("result") or {}).get("acquisition", {}).get("items", []))
                for a in searches
            ),
            "unique_source_identifiers": len(returned),
            "acquired_material_records": len(fetched),
            "material_views": len(views),
            "reading_records": len(readings),
            "read_source_identifiers": len(read_sources),
        },
        "independent_studies": "not adjudicated; identifiers/views/cards are not independence evidence",
        "science_validated": False,
    }


def summary(store, run):
    """Researcher projection, excluding raw sources, model messages and responses."""
    data = workspace(store, run)
    for group in ("background", "generation", "reviews"):
        for action in data[group]["actions"]:
            for key in ("attempts", "input", "messages", "config"):
                action.pop(key, None)
    for action in data["generation"]["actions"]:
        candidate = (action.get("result") or {}).get("candidate")
        if candidate:
            action["result"]["candidate"] = {
                k: candidate[k] for k in ("candidate_id", "title", "scoped_claim")
            }
    for view in data["background"]["views"]:
        view.pop("text", None)
    for action in data["literature"]:
        action.pop("attempts", None)
        if action.get("result"):
            action["result"].get("acquisition", {}).pop("text", None)
    data["research"].pop("policies", None)
    data["research"].pop("profiles", None)
    data["goal"].pop("attempts", None)
    data["goal"].pop("results", None)
    return strip_material_text(data)


def strip_material_text(value):
    if isinstance(value, dict):
        return {
            k: strip_material_text(v)
            for k, v in value.items()
            if k not in ("text", "raw_response", "actual_request", "messages")
        }
    if isinstance(value, list):
        return [strip_material_text(v) for v in value]
    return value
