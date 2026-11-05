"""Offline user annotations are separate, bound records, never model inputs."""

import json

import pytest

from co_scientist_next.store import Store
from co_scientist_next.workspace_records import WorkspaceRecords


def setup(tmp_path):
    s = Store(tmp_path / "notes.sqlite")
    p = s.create_project("OFFLINE arbitrary new question")
    b = s.revise_brief(p, {"question": "How does salinity affect root ion transport?"})
    r = s.create_run(b, ["OFFLINE"], policy_ref="OFFLINE")
    return s, r


def test_notes_are_persisted_version_bound_and_exported_separately(tmp_path):
    s, r = setup(tmp_path)
    with s:
        records = WorkspaceRecords(s)
        target = records.targets(r)[0]
        original = s.run(r)
        note = records.save(
            r,
            {
                "target_kind": "run",
                "target_ref": r,
                "target_sha256": target["sha256"],
                "category": "retrieval",
                "observations": {
                    "relevance": "OFFLINE source unrelated",
                    "omissions": "Not scientific coverage",
                },
                "note": "Human opinion only",
            },
        )
        assert s.run(r) == original
        assert records.list(r)[0]["id"] == note["id"]
        export = records.export(r)
        assert export["human_annotations"][0]["note"] == "Human opinion only"
        assert export["run"]["revision_id"] == original["revision_id"]
        assert export["science_validated"] is False
    with Store(tmp_path / "notes.sqlite") as s:
        assert WorkspaceRecords(s).list(r)[0]["target_sha256"] == target["sha256"]


def test_cross_run_and_changed_content_cannot_reuse_note_binding(tmp_path):
    s, r = setup(tmp_path)
    with s:
        x = WorkspaceRecords(s)
        with pytest.raises(ValueError):
            x.save(
                r,
                {
                    "target_kind": "candidate",
                    "target_ref": "missing",
                    "category": "note",
                    "note": "x",
                },
            )
        with pytest.raises(ValueError):
            x.save(
                r,
                {
                    "target_kind": "run",
                    "target_ref": r,
                    "target_sha256": "wrong",
                    "category": "note",
                    "note": "x",
                },
            )
        assert not x.list(r)


def test_annotations_do_not_change_frozen_model_inputs(tmp_path):
    import runpy
    from pathlib import Path

    from co_scientist_next.generation import GenerationService

    h = runpy.run_path(str(Path(__file__).with_name("test_generation.py")))
    with Store(tmp_path / "isolation.sqlite") as s:
        run, _, request = h["prepared"](s)
        g = GenerationService(s)
        before = json.dumps(g.ready_input(run, request), sort_keys=True)
        x = WorkspaceRecords(s)
        target = x.targets(run)[0]
        x.save(
            run,
            {
                "target_kind": "run",
                "target_ref": run,
                "target_sha256": target["sha256"],
                "category": "generation",
                "observations": {
                    "expected_answer": "HUMAN PRIVATE REVIEW MUST NOT ENTER MODEL INPUT"
                },
                "note": "Independent human evaluation",
            },
        )
        assert json.dumps(g.ready_input(run, request), sort_keys=True) == before
