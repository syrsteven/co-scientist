"""Data isolation and citation consistency only; no scientific evaluation run."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist_next.development_cases import (
    ARCHIVE_DIR,
    CASE_IDS,
    DATA_DIR,
    REVIEW_KEYS,
    load_bundle,
    model_payload,
    reviewer_record,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle_copy(tmp_path):
    shutil.copytree(ROOT / ARCHIVE_DIR, tmp_path / ARCHIVE_DIR)
    shutil.copy(ROOT / "docs/design/w0-real-cases-source-integrity.json", tmp_path / "docs/design")
    shutil.copytree(ROOT / DATA_DIR, tmp_path / DATA_DIR)
    return tmp_path


def change_json(root, name, mutate):
    path = root / DATA_DIR / name
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value, ensure_ascii=False))


def check_no_review_keys(value):
    if isinstance(value, dict):
        assert not REVIEW_KEYS.intersection(value)
        for child in value.values():
            check_no_review_keys(child)
    elif isinstance(value, list):
        for child in value:
            check_no_review_keys(child)


@pytest.mark.parametrize("case_id", [*CASE_IDS, "ALS-GOAL", "ALS-BRIEF"])
@pytest.mark.parametrize("mode", ["fixed_materials", "open_retrieval"])
def test_all_exports_have_explicit_visible_inputs_and_no_grading_fields(case_id, mode):
    payload = model_payload(ROOT, case_id, mode)
    check_no_review_keys(payload)
    assert payload["export_only"] is True
    assert payload["retrieval"]["mode"] == mode
    assert payload["evaluation_tier"] == "public_development_not_blind_not_independent_discovery"
    if mode == "open_retrieval":
        assert payload["materials"] == []
    else:
        assert payload["retrieval"]["seed_urls"] == []
        for material in payload["materials"]:
            assert (
                material["representation"] == "developer_paraphrase_of_source_not_full_source_text"
            )
            assert material["source_url"].startswith("https://")
            assert material["locator"] and material["text"]


def test_als_original_goal_reconstruction_and_public_hypothesis_are_distinct():
    goal = model_payload(ROOT, "ALS-GOAL", "fixed_materials")
    brief = model_payload(ROOT, "ALS-BRIEF", "fixed_materials")
    given = model_payload(ROOT, "R01", "fixed_materials")
    assert "磷酸化" in goal["inputs"]["goal"]
    for candidate in (goal, brief):
        assert candidate["materials"] == []
        serialized = json.dumps(candidate, ensure_ascii=False)
        assert (
            "Nup98" not in serialized and "Nup62" not in serialized and "TDP-43" not in serialized
        )
    assert "iPSC" not in json.dumps(goal)
    assert "iPSC" in brief["inputs"]["brief"]
    assert given["task_kind"] == "given_hypothesis_analysis"
    assert "TDP-43" in given["inputs"]["hypothesis_summary_cn"]
    assert "author_model_output" == given["materials"][0]["claim_kind"]
    assert reviewer_record(ROOT, "ALS-GOAL")["mechanism_match_not_required"]
    assert reviewer_record(ROOT, "ALS-BRIEF")["mechanism_match_not_required"]


def test_reviewer_material_has_a_separate_path_and_original_status_is_not_promoted():
    bundle = load_bundle(ROOT)
    review = reviewer_record(ROOT, "R01")
    assert review["expected"] and review["critical_failures"]
    assert review["assessment"] is None and review["evaluation_reviewers"] == []
    assert "provisional" in review["adoption_notes"]["scientific_status"]
    assert bundle["raw"]["R01"]["evaluation_executed"] is False
    assert bundle["raw"]["R01"]["suite_status"] == "proposed_unexecuted"
    review["expected"].append("REVIEW_ONLY_SENTINEL")
    assert "REVIEW_ONLY_SENTINEL" not in json.dumps(model_payload(ROOT, "R01", "fixed_materials"))


def test_raw_archive_mutation_is_rejected_before_export(bundle_copy):
    path = bundle_copy / ARCHIVE_DIR / "W0_MIN_REAL_EVAL_v0.1.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="bytes changed"):
        model_payload(bundle_copy, "R01", "fixed_materials")


def test_adoption_review_sentinel_is_not_exported(bundle_copy):
    change_json(
        bundle_copy,
        "adoption.json",
        lambda data: data["cases"][0]["review_only"].update(
            {
                "expected": ["REVIEW_ONLY_EXPECTED"],
                "critical_failures": ["REVIEW_ONLY_FAILURE"],
                "evaluation_reviewers": ["REVIEW_ONLY_REVIEWER"],
            }
        ),
    )
    payload = json.dumps(model_payload(bundle_copy, "R01", "fixed_materials"))
    assert "REVIEW_ONLY_" not in payload
    change_json(
        bundle_copy,
        "adoption.json",
        lambda data: data["cases"][0]["review_only"].update(
            {
                "scientific_status": "accepted_without_experts",
            }
        ),
    )
    with pytest.raises(ValueError, match="provisional"):
        model_payload(bundle_copy, "R01", "fixed_materials")


def test_nested_grading_field_in_selected_input_is_rejected(bundle_copy):
    change_json(
        bundle_copy,
        "adoption.json",
        lambda data: data["cases"][0].update(
            {
                "input_overrides": {"brief_cn": {"expected": "HIDDEN_LABEL"}},
            }
        ),
    )
    with pytest.raises(ValueError, match="Reviewer-only"):
        model_payload(bundle_copy, "R01", "fixed_materials")


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda records: records.append(records[0]), "Duplicate material"),
        (lambda records: records[0].update(source_id="missing"), None),
        (lambda records: records[-3].update(source_access_obtained="full_text_pdf"), "access"),
    ],
)
def test_invalid_material_or_access_reference_is_rejected(bundle_copy, mutation, message):
    change_json(bundle_copy, "materials.json", mutation)
    with pytest.raises((ValueError, KeyError), match=message):
        model_payload(bundle_copy, "R04", "fixed_materials")


def test_unknown_case_material_and_r01_generation_relabeling_rejected(bundle_copy):
    change_json(
        bundle_copy, "adoption.json", lambda data: data["cases"][0].update(material_ids=["absent"])
    )
    with pytest.raises(ValueError, match="Unknown visible"):
        model_payload(bundle_copy, "R01", "fixed_materials")
    change_json(
        bundle_copy,
        "adoption.json",
        lambda data: data["cases"][0].update(material_ids=[], task_kind="free_generation"),
    )
    with pytest.raises(ValueError, match="not a generation answer key"):
        model_payload(bundle_copy, "R01", "fixed_materials")


def test_r02_is_injected_not_a_paper_failure_and_does_not_use_an_unresolved_alias():
    payload = model_payload(ROOT, "R02", "fixed_materials")
    assert "same fixed DEV-01" not in json.dumps(payload)
    assert "developer_injected" in payload["inputs"]["gap_provenance"]
    assert "TDP-43" in payload["inputs"]["hypothesis"]
    assert (
        "project_M00_policy" in reviewer_record(ROOT, "R02")["adoption_notes"]["route_expectations"]
    )


def test_access_limits_and_related_liver_evidence_are_preserved():
    bundle = load_bundle(ROOT)
    audit = json.loads((ROOT / DATA_DIR / "source_audit.json").read_text())
    for source in ("P-04", "P-05", "P-06"):
        assert bundle["sources"][source]["access_obtained"] == "abstract"
        assert bundle["sources"][source]["limitations"]
    assert "unverified" in " ".join(bundle["sources"]["P-05"]["limitations"])
    relation = next(r for r in audit["relationships"] if r["sources"] == ["P-02", "P-07"])
    assert relation["classification"] == "related_companion_reports_not_independent_replication"
    assert relation["unresolved"] and relation["denominators"]
    assert bundle["raw"]["R06"]["sources"][1]["role"] == "independent_primary_study"
    assert (
        "independence not established"
        in reviewer_record(ROOT, "R06")["adoption_notes"]["adoption_note"]
    )
    assert "independent_primary_study" not in json.dumps(
        model_payload(ROOT, "R06", "fixed_materials")
    )


def test_cli_exports_only_data_without_any_model_credentials():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "co_scientist_next.development_cases",
            "--root",
            str(ROOT),
            "--case",
            "R05",
            "--mode",
            "fixed_materials",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
        },
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    payload = json.loads(result.stdout)
    check_no_review_keys(payload)
    assert payload["case_id"] == "R05" and payload["export_only"]
    assert payload["materials"][0]["claim_kind"] == "reported_observation"
