"""W0-T3 repository-local data export only: no evaluation, model or retrieval calls.

The original public casebook is reviewer material. Export explicit allowlists,
never a raw case or the complete casebook. This is not a security boundary against
an editor putting an answer inside an allowed text field or model pretraining.
"""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

ARCHIVE_DIR = Path("docs/design/w0-real-cases-proposed-v0.1")
DATA_DIR = Path("evaluation/w0_real_cases")
REVIEW_KEYS = frozenset(
    {
        "expected",
        "critical_failures",
        "evaluation_reviewers",
        "assessment",
        "candidate_answer",
        "review_only",
        "source_fact_is_gold",
        "scientific_gold_status",
        "evaluation_executed",
    }
)
CASE_IDS = ("R01", "R02", "R03", "R04", "R05", "R06")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def indexed(records, label):
    result = {record["id"]: record for record in records}
    if len(result) != len(records):
        raise ValueError(f"Duplicate {label} identity")
    return result


def reject_review_fields(value):
    if isinstance(value, dict):
        if REVIEW_KEYS.intersection(value):
            raise ValueError("Reviewer-only field in model input")
        for item in value.values():
            reject_review_fields(item)
    elif isinstance(value, list):
        for item in value:
            reject_review_fields(item)


def load_bundle(root: Path):
    """Validate original file integrity and adopted source/selection references."""
    root = Path(root)
    manifest = read_json(root / "docs/design/w0-real-cases-source-integrity.json")
    if manifest["status"] != "proposed":
        raise ValueError("Original case package must remain Proposed")
    actual_files = {p.name for p in (root / ARCHIVE_DIR).iterdir() if p.is_file()}
    if actual_files != set(manifest["files"]):
        raise ValueError("Original case package file set differs")
    for name, digest in manifest["files"].items():
        # Manifest paths must stay within the original package.
        if Path(name).name != name:
            raise ValueError("Unexpected original package path")
        if hashlib.sha256((root / ARCHIVE_DIR / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Original case package bytes changed")
    raw = indexed(
        [
            json.loads(line)
            for line in (root / ARCHIVE_DIR / "W0_MIN_REAL_EVAL_v0.1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ],
        "raw case",
    )
    adoption = read_json(root / DATA_DIR / "adoption.json")
    audit = read_json(root / DATA_DIR / "source_audit.json")
    materials = indexed(read_json(root / DATA_DIR / "materials.json"), "material")
    sources = indexed(audit["sources"], "source")
    cases = indexed(adoption["cases"], "adopted case")
    variants = indexed(adoption["als_input_variants"], "ALS input variant")
    if (
        set(raw) != set(CASE_IDS)
        or set(cases) != set(CASE_IDS)
        or adoption["raw_case_ids"] != list(CASE_IDS)
    ):
        raise ValueError("Adoption must retain exactly the six supplied evaluation cases")
    if adoption["status"] != "proposed" or audit["status"] != "proposed":
        raise ValueError("Adoption and audit are Proposed, not scientific acceptance")
    for material in materials.values():
        source = sources[material["source_id"]]
        if material["source_access_obtained"] != source["access_obtained"]:
            raise ValueError("Material overstates or mismatches checked source access")
        if material["representation"] != "developer_paraphrase_of_source_not_full_source_text":
            raise ValueError("This first-use pack contains paraphrases, not full papers")
        if not material["locator"] or not material["text"]:
            raise ValueError("Material text and specific source location required")
    for case in cases.values():
        original = raw[case["raw_case_id"]]
        if original["id"] != case["id"]:
            raise ValueError("Adoption changes the original case identity")
        keys = case["visible_input_keys"]
        if len(set(keys)) != len(keys) or not set(keys) <= original["input"].keys():
            raise ValueError("Invalid input selection")
        if not set(case.get("input_overrides", {})) <= set(keys):
            raise ValueError("Unselected input override")
    if set(variants) != {"ALS-GOAL", "ALS-BRIEF"}:
        raise ValueError("Only two explicit variants of the existing ALS case are supported")
    if cases["R01"]["task_kind"] != "given_hypothesis_analysis":
        raise ValueError("R01 is given-hypothesis analysis, not a generation answer key")
    for item in [*cases.values(), *variants.values()]:
        if item["review_only"]["scientific_status"] != "provisional_requires_expert_review":
            raise ValueError("Scientific expectations remain provisional pending expert review")
        if len(set(item["material_ids"])) != len(item["material_ids"]):
            raise ValueError("Duplicate visible material reference")
        for material_id in item["material_ids"]:
            if material_id not in materials:
                raise ValueError("Unknown visible material reference")
    for relationship in audit["relationships"]:
        if not set(relationship["sources"]) <= sources.keys():
            raise ValueError("Unknown relationship source reference")
    return {
        "raw": raw,
        "cases": cases,
        "variants": variants,
        "sources": sources,
        "materials": materials,
    }


def model_payload(root: Path, case_id: str, mode: str):
    """Return the complete proposed visible task payload, never reviewer labels.

    fixed_materials exposes only curated paraphrases. open_retrieval exposes no
    evidence text; seed URLs are starting points, not claims of executed retrieval.
    Neither mode calls a model or scores a response.
    """
    if mode not in ("fixed_materials", "open_retrieval"):
        raise ValueError("Choose fixed_materials or open_retrieval explicitly")
    bundle = load_bundle(root)
    if case_id in bundle["cases"]:
        case = bundle["cases"][case_id]
        raw = bundle["raw"][case_id]
        inputs = {key: deepcopy(raw["input"][key]) for key in case["visible_input_keys"]}
        inputs.update(deepcopy(case.get("input_overrides", {})))
        task = case.get("task_override", raw["task"])
        provenance = {"kind": case["input_provenance"]}
    else:
        case = bundle["variants"][case_id]
        inputs = deepcopy(case["inputs"])
        task = case["task"]
        provenance = {key: case["provenance"][key] for key in ("kind", "source_id", "locator")}
    visible = []
    seeds = []
    for material_id in case["material_ids"]:
        material = bundle["materials"][material_id]
        source = bundle["sources"][material["source_id"]]
        if source["url"] not in seeds:
            seeds.append(source["url"])
        visible.append(
            {
                "id": material_id,
                "source_id": source["id"],
                "source_url": source["url"],
                "locator": material["locator"],
                "text": material["text"],
                "claim_kind": material["claim_kind"],
                "representation": material["representation"],
                "source_access_obtained": source["access_obtained"],
            }
        )
    payload = {
        "case_id": case_id,
        "task_kind": case["task_kind"],
        "task": task,
        "inputs": inputs,
        "input_provenance": provenance,
        "materials": visible if mode == "fixed_materials" else [],
        "retrieval": {"mode": mode, "seed_urls": seeds if mode == "open_retrieval" else []},
        "evaluation_tier": "public_development_not_blind_not_independent_discovery",
        "export_only": True,
    }
    reject_review_fields(payload)
    return payload


def reviewer_record(root: Path, case_id: str):
    """Separate local review path; must never be passed to the tested model."""
    bundle = load_bundle(root)
    if case_id in bundle["cases"]:
        raw = bundle["raw"][case_id]
        return deepcopy(
            {
                "expected": raw["expected"],
                "critical_failures": raw["critical_failures"],
                "evaluation_reviewers": raw["evaluation_reviewers"],
                "assessment": raw["assessment"],
                "adoption_notes": bundle["cases"][case_id]["review_only"],
            }
        )
    return deepcopy(bundle["variants"][case_id]["review_only"])


def main():
    parser = argparse.ArgumentParser(
        description="W0-T3 proposed model-visible data export; no model calls"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository checkout with the public case data",
    )
    parser.add_argument("--case", required=True, choices=[*CASE_IDS, "ALS-GOAL", "ALS-BRIEF"])
    parser.add_argument("--mode", required=True, choices=["fixed_materials", "open_retrieval"])
    args = parser.parse_args()
    print(json.dumps(model_payload(args.root, args.case, args.mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
