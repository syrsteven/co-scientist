"""Explicit live public acquisition acceptance, not part of offline pytest.

Uses human/developer-authored concept queries and real UI; no query generator,
paid model or scientific appraisal. Evidence distinguishes test Ethics/live HTTP.
"""

import argparse
import gzip
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

QUERY = '"amyotrophic lateral sclerosis" AND (nucleoporin OR "nuclear pore")'
EMPTY_QUERY = "EXT_ID:W1L1EngineeringNoSuchRecord20261103 AND SRC:MED"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8785")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--executable")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    adopted = json.loads(Path("evaluation/w0_real_cases/adoption.json").read_text())
    als = next(v for v in adopted["als_input_variants"] if v["id"] == "ALS-GOAL")
    goal = als["inputs"]["goal"]  # Only selected Goal, never review/expected fields.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=args.executable)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(args.url + "/") else route.abort()
            ),
        )
        page = context.new_page()
        page.set_default_timeout(90_000)
        errors, posts = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
        page.goto(args.url)
        page.locator("#new-project").click()
        page.locator("#name").fill("W1-L1 ALS · 测试筛查 + 真实公共文献获取")
        page.locator("#question").fill(goal)
        page.locator("#constraints").fill("保留核孔蛋白磷酸化问题\n不预选具体分子或实验模型")
        page.locator("#background").fill(
            "采用已有ALS-GOAL开发者转述，非原文逐字引用；本次仅检索获取，不执行模型阅读。"
        )
        page.locator("#intended-use").fill("非临床文献检索开发验证")
        page.locator("#brief-form button").click()
        expect(page.locator("#revision-badge")).to_contain_text("草稿版本")
        page.locator("#example-policy").click()
        with page.expect_response(
            lambda r: r.url.endswith("/api/runs") and r.request.method == "POST"
        ) as response:
            page.locator("#create-run").click()
        run_id = response.value.json()["run_id"]
        page.locator("#execute").click()
        expect(page.locator("#run-state")).to_have_text("等待背景调研接入")
        expect(page.locator(".ethics-readable")).to_contain_text("目标筛查：通过")
        expect(page.locator("#literature-mode")).to_contain_text(
            "目标筛查为测试结果，文献获取为真实请求"
        )

        def history():
            return page.request.get(args.url + "/api/literature?run_id=" + run_id).json()

        def perform(button):
            with page.expect_response(
                lambda r: r.url.endswith("/api/literature") and r.request.method == "POST",
                timeout=90_000,
            ) as r:
                button.click()
            assert r.value.status == 200, r.value.text()
            # Wait until showRun/final action cleanup has rendered saved facts.
            expect(page.locator("#literature-search")).to_be_enabled()
            return history()[-1]

        page.locator("#literature-query").fill(QUERY)
        first = perform(page.locator("#literature-search"))
        assert first["result"], first
        search = first["result"]["acquisition"]
        assert search["status"] == "succeeded" and search["items"], search
        first_source = search["items"][0]["source_ref"]
        source_card = page.locator(".source-card").filter(has_text=first_source).first
        abstract = perform(source_card.get_by_role("button", name="获取摘要", exact=True))
        assert abstract["result"]["acquisition"]["access"] == "abstract", abstract
        page.get_by_text("查看已取得摘要", exact=True).click()
        oa = next(
            (
                s["source"]["source_ref"]
                for s in first["result"]["details"]["sources"]
                if s["metadata"].get("isOpenAccess") == "Y"
                and s["source"]["source_ref"].startswith("epmc:MED:")
            ),
            None,
        )
        full = None
        if oa:
            card = page.locator(".source-card").filter(has_text=oa).first
            full = perform(card.get_by_role("button", name="尝试获取开放全文", exact=True))
            assert full["result"]["acquisition"]["access"] == "full_text", full
            page.get_by_text("查看已取得全文文本（图像/补充未获取）", exact=True).click()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(args.evidence / "workspace.png"), full_page=True)
        if search["next_cursor"]:
            next_page = perform(page.get_by_role("button", name="显式检索下一页", exact=True).first)
            assert next_page["request"]["cursor"] == search["next_cursor"]
        page.locator("#literature-query").fill(EMPTY_QUERY)
        empty = perform(page.locator("#literature-search"))
        assert empty["result"]["acquisition"]["reported_total"] == 0
        assert empty["result"]["acquisition"]["scope_complete"] is True
        saved = history()
        count = len(posts)
        page.reload()
        expect(page.locator("#literature-history")).to_contain_text(QUERY)
        assert len(posts) == count
        assert history() == saved
        fixed = page.request.get(args.url + "/api/run?id=" + run_id).json()
        assert fixed["fixed_brief"]["question"] == goal and fixed["science_validated"] is False
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(args.evidence / "after-refresh.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(args.evidence / "mobile.png"), full_page=True)
        attempts = []
        for entry in saved:
            for attempt in entry["attempts"]:
                attempts.append(
                    page.request.get(
                        args.url + "/api/literature/response?attempt_id=" + attempt["id"]
                    ).json()
                )
        (args.evidence / "run-snapshot.json").write_text(
            json.dumps(fixed, ensure_ascii=False, indent=2) + "\n"
        )
        evidence = {
            "run_id": run_id,
            "goal_provenance": als["provenance"],
            "history": saved,
            "attempts": attempts,
        }
        with gzip.open(
            args.evidence / "public-acquisition.json.gz", "wt", encoding="utf-8"
        ) as output:
            json.dump(evidence, output, ensure_ascii=False, indent=2)
        report = {
            "run_id": run_id,
            "goal_screening": "deterministic_development_fixture",
            "literature": "real_public_http",
            "manual_query": QUERY,
            "first_page_count": len(search["items"]),
            "reported_total": search["reported_total"],
            "pagination_complete": search["scope_complete"],
            "abstract_source": first_source,
            "full_text_source": oa,
            "full_text_access": full["result"]["acquisition"]["access"]
            if full
            else "not_available_in_first_page",
            "actions": len(saved),
            "actual_http_sends": len(attempts),
            "refresh_added_posts": len(posts) - count,
            "saved_history_unchanged": True,
            "science_validated": False,
            "model_read": False,
            "page_errors": errors,
        }
        (args.evidence / "browser.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        assert not errors
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
