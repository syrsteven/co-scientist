"""Explicit development-reading UI acceptance on previously acquired materials.

NO real model or public search is executed by this script. Requires an existing
passed Run with L1 material and a server using --development-reading.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8786")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--executable")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.executable)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(args.url + "/") else route.abort()
            ),
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        errors, posts = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        page.goto(args.url + "/#run=" + args.run_id)
        expect(page.locator("#background-mode")).to_contain_text("开发阅读替身")

        def get(path):
            return page.request.get(args.url + path).json()

        original = get("/api/run?id=" + args.run_id)
        literature = get("/api/literature?run_id=" + args.run_id)
        immutable_hash = hashlib.sha256(json.dumps(literature, sort_keys=True).encode()).hexdigest()
        assert (
            get("/api/background?run_id=" + args.run_id)["current_model_config"]["execution_mode"]
            == "development_fixture"
        )

        def scope(seed=""):
            page.locator("#background-scope").select_option(seed)
            expect(page.locator("#background-scope")).to_have_value(seed)
            # Async onchange updates filtered view/packet options.
            expect(page.locator("#background-run")).to_be_enabled()

        def save_view(seed=""):
            scope(seed)
            page.locator("#view-start").fill("0")
            page.locator("#view-end").fill("600")
            page.locator("#view-reason").fill(
                "Explicit engineering excerpt; unseen text/figures are not read"
            )
            with page.expect_response(
                lambda r: r.url.endswith("/api/material-views") and r.request.method == "POST"
            ) as response:
                page.locator("#save-view").click()
            assert response.value.status == 201, response.value.text()
            view = response.value.json()
            expect(
                page.locator('#background-view option[value="' + view["id"] + '"]')
            ).to_have_count(1)
            page.locator("#background-operation").select_option("P04")
            page.locator("#background-view").select_option(view["id"])
            return view

        def op(operation, *, scenario="ready"):
            page.locator("#background-operation").select_option(operation)
            if operation.startswith("P06") or operation == "P03":
                page.locator("#background-number").fill("1")
            page.locator("#background-fixture").select_option(scenario)
            with page.expect_response(
                lambda r: r.url.endswith("/api/background/execute") and r.request.method == "POST"
            ) as response:
                page.locator("#background-run").click()
            assert response.value.status == 200, response.value.text()
            snapshot = response.value.json()
            record = snapshot["actions"][-1]
            expect(
                page.locator('.background-record[data-request-id="' + record["request_id"] + '"]')
            ).to_be_visible()
            expect(page.locator("#background-run")).to_be_enabled()
            return record, snapshot

        save_view()
        invalid, _ = op("P04", scenario="invalid_output")
        assert invalid["result"]["background_status"] == "invalid_output"
        failed, _ = op("P04", scenario="technical_failure")
        assert failed["task_status"] == "failed" and failed["result"] is None
        reading, _ = op("P04")
        assert reading["result"]["background_status"] == "saved"
        orientation, _ = op("P05")
        assert orientation["result"]["artifact"]["mode"] == "NEUTRAL_ORIENTATION"
        _directed, data = op("P06_DIRECTED")
        directed_seed = data["seeds"][-1]
        opened, data = op("P06_OPEN")
        open_seed = data["seeds"][-1]
        assert set(opened["input"]) == {
            "goal_context",
            "neutral_overview",
            "source_discovery_capabilities",
            "generic_search_constraints",
        }
        assert directed_seed["id"] not in json.dumps(opened["input"])
        scope(directed_seed["id"])
        plan, _ = op("P03")
        assert plan["result"]["artifact"]["executed"] is False
        assert get("/api/literature?run_id=" + args.run_id) == literature
        save_view(directed_seed["id"])
        op("P04")
        seed_packet, _ = op("P05")
        assert seed_packet["seed_id"] == directed_seed["id"]
        more, _ = op("P07", scenario="retrieve_more")
        assert more["result"]["artifact"]["decision"] == "retrieve_more"
        save_view(open_seed["id"])
        op("P04")
        op("P05")
        ready, data = op("P07")
        assert ready["result"]["artifact"]["decision"] == "ready"
        attempt_count = sum(len(a["attempts"]) for a in data["actions"])
        stopped, data = op("P07")
        assert stopped["result"]["background_status"] == "no_progress"
        assert sum(len(a["attempts"]) for a in data["actions"]) == attempt_count
        assert (
            data["real_adapter_attempts_recorded"] == 0 and data["generation_implemented"] is False
        )
        expect(page.locator("#background-seeds")).to_contain_text("retrieve_more")
        expect(page.locator("#background-seeds")).to_contain_text("ready")
        page.locator("#background-panel").scroll_into_view_if_needed()
        page.screenshot(path=str(args.evidence / "workspace.png"))
        page.locator("#background-seeds").screenshot(path=str(args.evidence / "seeds.png"))
        page.locator(
            '.background-record[data-request-id="' + reading["request_id"] + '"]'
        ).screenshot(path=str(args.evidence / "saved-reading.png"))
        before = len(posts)
        saved = get("/api/background?run_id=" + args.run_id)
        page.reload()
        expect(page.locator("#background-seeds")).to_contain_text("ready")
        assert len(posts) == before and get("/api/background?run_id=" + args.run_id) == saved
        assert (
            hashlib.sha256(
                json.dumps(get("/api/literature?run_id=" + args.run_id), sort_keys=True).encode()
            ).hexdigest()
            == immutable_hash
        )
        assert get("/api/run?id=" + args.run_id)["fixed_brief"] == original["fixed_brief"]
        page.locator("#background-seeds").screenshot(path=str(args.evidence / "after-refresh.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.locator("#background-seeds").screenshot(path=str(args.evidence / "mobile-seeds.png"))
        report = {
            "run_id": args.run_id,
            "material_origin": "previously saved W1-L1 real public acquisition; not fetched again",
            "model_execution": "development_fixture",
            "real_vendor_calls_executed": False,
            "model_reading_performance_reviewed": False,
            "science_validated": False,
            "actions": len(data["actions"]),
            "fixture_model_attempts": attempt_count,
            "saved_readings": data["reading_count_saved"],
            "query_plan_executed": False,
            "public_searches_added": 0,
            "open_input_keys": sorted(opened["input"]),
            "directed_seed": directed_seed["id"],
            "open_seed": open_seed["id"],
            "directed_readiness": "retrieve_more",
            "open_readiness": "ready",
            "unchanged_readiness_recheck": "no_progress_without_send",
            "refresh_added_posts": len(posts) - before,
            "raw_materials_unchanged": True,
            "fixed_brief_unchanged": True,
            "page_errors": errors,
        }
        (args.evidence / "browser.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        attempts = [
            get("/api/background/attempt?attempt_id=" + attempt["id"])
            for action in saved["actions"]
            for attempt in action["attempts"]
        ]
        with gzip.open(
            args.evidence / "development-execution.json.gz", "wt", encoding="utf8"
        ) as output:
            json.dump(
                {
                    "notice": "DEVELOPMENT MODEL FIXTURES ONLY. Actual material from saved W1-L1 acquisition; no real model calls.",
                    "snapshot": saved,
                    "model_attempts": attempts,
                },
                output,
                ensure_ascii=False,
                indent=2,
            )
        assert not errors
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
