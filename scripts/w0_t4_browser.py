"""Explicit real-browser development acceptance against a running W0-T4 page.

Creates engineering test records through the visible UI, not embedded V5 cases.
Needs Playwright + Chromium; no model keys and no external page requests.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8784")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--executable", help="Optional existing Chromium headless-shell binary")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    original = "核孔蛋白磷酸化是否可能参与 ALS？请保留未知机制。"
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
        errors, posts = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
        page.goto(args.url)
        expect(page.locator("#mode")).to_contain_text("开发测试模式")
        page.locator("#new-project").click()
        page.locator("#name").fill("W0-T4 页面工程验收（开发测试）")
        page.locator("#question").fill(original)
        page.locator("#constraints").fill("不预选特定分子或模型\n保留原始问题")
        page.locator("#preferences").fill("优先可检验性")
        page.locator("#background").fill("仅用于页面与持久化工程验收，不是科研结果。")
        page.locator("#intended-use").fill("非临床概念研究")
        page.locator("#brief-form button").click()
        expect(page.locator("#revision-badge")).to_contain_text("草稿版本")

        def create(scenario, expected_status, *, policy=True):
            if policy:
                page.locator("#example-policy").click()
            else:
                page.locator("#policy-text").fill("")
            page.locator("#scenario").select_option(scenario)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/runs") and response.request.method == "POST"
                )
            ) as response:
                page.locator("#create-run").click()
            run_id = response.value.json()["run_id"]
            expect(page.locator("#execute")).to_be_enabled()
            page.locator("#execute").click()
            expect(page.locator("#run-state")).to_have_text(expected_status)
            saved = page.request.get(args.url + "/api/run?id=" + run_id).json()
            assert all(t["module"] in ("goal.prepare.v1", "goal.screen.v1") for t in saved["tasks"])
            assert saved["science_validated"] is False
            return run_id, saved

        pass_id, saved = create("pass", "等待背景调研接入")
        assert saved["run"]["status"] == "awaiting_background"
        assert saved["results"][-1]["output"]["ethics"]["decision"] == "pass"
        expect(page.locator("#run-detail")).to_contain_text("原始问题中的条件始终有效")
        page.screenshot(path=str(args.evidence / "w0-t4-workspace.png"), full_page=True)
        before_posts = len(posts)
        before_usage = saved["usage"]
        page.reload()
        expect(page.locator("#run-state")).to_have_text("等待背景调研接入")
        assert len(posts) == before_posts
        assert page.request.get(args.url + "/api/run?id=" + pass_id).json()["usage"] == before_usage
        page.locator("#question").fill("编辑后的新草稿：不覆盖原 Run")
        page.locator("#brief-form button").click()
        expect(page.locator("#notice")).to_contain_text("既有 Run 输入保持不变")
        page.reload()
        expect(page.locator("#question")).to_have_value("编辑后的新草稿：不覆盖原 Run")
        expect(page.locator("#run-detail")).to_contain_text(original)
        assert (
            page.request.get(args.url + "/api/run?id=" + pass_id).json()["fixed_brief"]["question"]
            == original
        )
        page.screenshot(path=str(args.evidence / "w0-t4-fixed-run-after-edit.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(args.evidence / "w0-t4-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1100})
        scenarios = {}
        for scenario, title in (
            ("reject", "目标筛查 reject，已停止"),
            ("clarification", "待澄清关键歧义"),
            ("risk_information", "风险信息待补充（非伦理结论）"),
            ("invalid_output", "模型输出无效"),
            ("technical_failure", "技术执行失败"),
        ):
            run_id, result = create(scenario, title)
            scenarios[scenario] = {
                "run_id": run_id,
                "state": result["run"]["status"],
                "tasks": len(result["tasks"]),
            }
        missing_id, result = create("pass", "缺少显式政策", policy=False)
        assert "ethics" not in result["results"][-1]["output"]
        scenarios["missing_policy"] = {"run_id": missing_id, "state": result["run"]["status"]}
        assert not errors, errors
        report = {
            "development_test": True,
            "science_validated": False,
            "pass_run": pass_id,
            "refresh_posts_added": 0,
            "usage_unchanged_after_refresh": True,
            "fixed_run_unchanged_after_edit": True,
            "mobile_no_horizontal_overflow": True,
            "scenario_results": scenarios,
            "page_errors": errors,
        }
        (args.evidence / "w0-t4-browser.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
