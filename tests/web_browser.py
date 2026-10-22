"""Explicit local-only browser acceptance. Run separately, no online scientific APIs."""

import asyncio
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright


async def main():
    folder = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    url = "http://127.0.0.1:8766"
    environment = {
        k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "DEEPSEEK_API_KEY"}
    }
    server = subprocess.Popen(  # noqa: ASYNC220 -- detached local test server, explicitly reaped
        [
            sys.executable,
            "-m",
            "co_scientist_web",
            "--port",
            "8766",
            "--data-dir",
            str(folder / "data"),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True
            )
            external, errors = [], []

            async def route(request):
                if request.request.url.startswith(url + "/"):
                    await request.continue_()
                else:
                    external.append(request.request.url)
                    await request.abort()

            await context.route("**/*", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            for _ in range(80):
                try:
                    await page.goto(url)
                    break
                except PlaywrightError as error:
                    if "ERR_CONNECTION_REFUSED" not in str(error):
                        raise
                    await asyncio.sleep(0.2)
            await page.locator(".connection").filter(has_text="已连接").wait_for()
            for nav in ["projects", "create", "monitor", "results", "settings"]:
                await page.locator(f"[data-nav='{nav}']").click()
                assert await page.locator(f"[data-page='{nav}']").is_visible()
            await page.locator("#wb-secret-openai").fill("FAKE-BROWSER-OPENAI-SECRET")
            await page.locator("#wb-secret-deepseek").fill("FAKE-BROWSER-DEEPSEEK-SECRET")
            await page.locator("#wb-pubmed-email").fill("test@example.test")
            await page.locator("#wb-settings-save").click()
            await page.locator("#wb-openai-state").filter(has_text="后端内存已配置").wait_for()
            assert await page.locator("#wb-secret-openai").input_value() == ""
            assert "FAKE-BROWSER" not in await page.content()
            assert "FAKE-BROWSER" not in await page.evaluate("JSON.stringify({...localStorage})")
            await page.locator("[data-nav='create']").click()
            await page.locator("#wb-title").fill("Browser synthetic recovery")
            await page.locator("#wb-goal").fill(
                "Distinguish reversible stress responses from persistent synthetic functional impairment."
            )
            await page.locator("#wb-chain").fill("stress\nfunctional recovery")
            await page.locator("#wb-outputs").fill("testable prediction\nfalsifier")
            await page.locator("[data-step='2']").click()
            await page.locator("#wb-run-check").click()
            await page.locator("#wb-preflight-list").filter(has_text="原生预检 PASS").wait_for()
            await page.locator("[data-step='3']").click()
            await page.locator("#backend-create").click()
            await page.locator("#backend-approval").wait_for(state="visible")
            await page.locator("#backend-confirm").check()
            await page.locator("#backend-approve").click()
            await page.wait_for_url("**/?run=**#monitor")
            run = await page.evaluate("new URLSearchParams(location.search).get('run')")
            running_url = page.url
            # Closing the creating tab must not cancel the detached driver.
            await page.close()
            # Restart the HTTP service too. The native driver and OS lock must
            # survive; credentials intentionally do not survive this restart.
            server.terminate()
            await asyncio.to_thread(server.wait, timeout=20)
            server = subprocess.Popen(  # noqa: ASYNC220 -- test-owned replacement local server
                [
                    sys.executable,
                    "-m",
                    "co_scientist_web",
                    "--port",
                    "8766",
                    "--data-dir",
                    str(folder / "data"),
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            for _ in range(80):
                try:
                    await page.goto(running_url)
                    break
                except PlaywrightError as error:
                    if "ERR_CONNECTION_REFUSED" not in str(error):
                        raise
                    await asyncio.sleep(0.2)
            deadline = time.monotonic() + 600
            pending_observed = False
            while time.monotonic() < deadline:
                response = await context.request.get(url + f"/api/v1/runs/{run}/status")
                if response.ok:
                    status = await response.json()
                    if status["state"] == "completed":
                        break
                    assert status.get("job", {}).get("state") != "interrupted_needs_review", status
                    board_response = await context.request.get(
                        url + f"/api/v1/runs/{run}/leaderboard"
                    )
                    if board_response.ok:
                        pending_observed |= bool((await board_response.json())["pending"])
                await asyncio.sleep(1)
            else:
                raise AssertionError("G3 browser run did not complete")
            assert (
                status["final"]["execution_result"] == "COMPLETE"
                and status["final"]["terminal_barrier_complete"]
            )
            assert status["final"]["selection_result"] == "FINAL_WINNER"
            board = await (
                await context.request.get(url + f"/api/v1/runs/{run}/leaderboard")
            ).json()
            assert len(board["ranked"]) == 10 and not board["pending"]
            await page.locator("[data-nav='results']").click()
            await page.locator(".wb-result-row").nth(9).wait_for()
            await page.locator("[data-r-tab='reflection']").click()
            assert "Reflection" in await page.locator("#wb-results-detail").text_content()
            await page.locator("[data-nav='monitor']").click()
            async with page.expect_download() as downloading:
                await page.locator("#backend-export").click()
            download = await downloading.value
            archive_path = folder / "native-trace.zip"
            await download.save_as(archive_path)
            with zipfile.ZipFile(io.BytesIO(archive_path.read_bytes())) as archive:
                assert len(archive.namelist()) == 5
                timeline = json.loads(archive.read("run-timeline.json"))
                assert timeline["evidence_kind"] == "MOCK_ONLY"
            assert not errors, errors
            assert not external, external
            for file in (folder / "data").rglob("*"):
                if file.is_file():
                    assert b"FAKE-BROWSER" not in file.read_bytes(), file
            await page.screenshot(path=str(folder / "monitor-desktop.png"), full_page=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.locator("[data-nav='settings']").click()
            await page.screenshot(path=str(folder / "settings-mobile.png"), full_page=True)
            report = {
                "run_id": run,
                "status": status,
                "candidates": len(board["ranked"]),
                "pending_observed_during_run": pending_observed,
                "external_browser_requests": external,
                "javascript_errors": errors,
                "native_export": str(archive_path),
                "python": sys.version,
                "http_server_restarted_while_native_driver_survived": True,
            }
            (folder / "browser-report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False))
            await browser.close()
    finally:
        server.terminate()
        server.wait(timeout=20)


if __name__ == "__main__":
    asyncio.run(main())
