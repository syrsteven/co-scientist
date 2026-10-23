"""Loopback-only explicit UI recovery/stop acceptance; separate from pytest."""

import asyncio
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from playwright.async_api import Error, async_playwright

from co_scientist_web.store import Store


async def main():
    folder = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    data = folder / "data"
    url = "http://127.0.0.1:8767"
    environment = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "DEEPSEEK_API_KEY"}}
    server = await asyncio.create_subprocess_exec(sys.executable, "-m", "co_scientist_web",
        "--data-dir", str(data), "--port", "8767", env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(accept_downloads=True)
            async def route(request):
                assert request.request.url.startswith(url + "/"), request.request.url
                await request.continue_()
            await context.route("**/*", route)
            page = await context.new_page()
            errors, writes = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: writes.append(r.url) if r.method == "POST" else None)
            for _ in range(80):
                try:
                    await page.goto(url)
                    break
                except Error as error:
                    if "CONNECTION_REFUSED" not in str(error):
                        raise
                    await asyncio.sleep(.2)
            csrf = (await (await context.request.get(url + "/api/v1/session")).json())["csrf_token"]
            headers = {"Origin": url, "X-CSRF-Token": csrf}
            goal = {"title": "Recovery boundary fixture",
                    "goal": "Distinguish reversible synthetic stress from persistent impairment.",
                    "required_causal_chain": ["stress", "recovery"], "required_outputs": ["prediction"]}
            pf = await context.request.post(url + "/api/v1/config/preflight", headers=headers,
                                            data={"goal": goal})
            assert pf.ok, await pf.text()
            run = (await (await context.request.post(url + "/api/v1/runs", headers=headers,
                data={"preflight_id": (await pf.json())["preflight_id"]})).json())["id"]
            assert (await context.request.post(url + f"/api/v1/runs/{run}/stop", headers=headers)).status == 409
            assert (await context.request.post(url + f"/api/v1/runs/{run}/authorize", headers=headers,
                                               data={"confirm": True, "accept_usd": "60"})).ok
            root = Store(data).run_root(run)
            # Native checkpoint created with the actual CoreRunner + MockTransport.
            # Lost Web metadata simulates restart after a known committed boundary.
            child = await asyncio.create_subprocess_exec(sys.executable, "-c",
                "import asyncio,socket,sys; from pathlib import Path; "
                "from co_scientist.release.service import RunService; "
                "asyncio.run(RunService(environment={}).execute(Path(sys.argv[1]), steps=1))", str(root),
                env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert await child.wait() == 0
            Store(data).job(run, pid=99999999, state="running")
            await page.goto(url + f"/?run={run}#monitor")
            await page.locator("#board-refresh-label").filter(has_text="interrupted_needs_review").wait_for()
            before = await (await context.request.get(url + f"/api/v1/runs/{run}/events")).json()
            writes.clear()
            await page.locator("#backend-reconnect").click()
            await page.reload()
            await page.locator("#board-refresh-label").filter(has_text="interrupted_needs_review").wait_for()
            assert not writes, writes
            assert await (await context.request.get(url + f"/api/v1/runs/{run}/events")).json() == before
            page.once("dialog", lambda dialog: dialog.dismiss())
            await page.locator("#backend-resume").click()
            assert not writes
            page.once("dialog", lambda dialog: dialog.accept())
            await page.locator("#backend-resume").click()
            await page.locator("#backend-resume:disabled").wait_for()
            page.once("dialog", lambda dialog: dialog.accept())
            await page.locator("#backend-stop").click()
            for _ in range(180):
                status = await (await context.request.get(url + f"/api/v1/runs/{run}/status")).json()
                if status["state"] == "completed_partial":
                    break
                await asyncio.sleep(.5)
            else:
                raise AssertionError("UI stop did not reach native PARTIAL")
            assert status["final"]["winner_id"] is None and status["job"]["state"] == "terminal"
            frozen = await (await context.request.get(url + f"/api/v1/runs/{run}/events")).json()
            assert (await context.request.post(url + f"/api/v1/runs/{run}/resume", headers=headers)).ok
            assert await (await context.request.get(url + f"/api/v1/runs/{run}/events")).json() == frozen
            async with page.expect_download() as downloading:
                await page.locator("#backend-export").click()
            await (await downloading.value).save_as(folder / "partial-trace.zip")
            with zipfile.ZipFile(folder / "partial-trace.zip") as archive:
                assert len(archive.namelist()) == 5
            assert not errors, errors
            report = {"run_id": run, "state": status["state"], "readonly_reconnect_writes": 0,
                      "partial_winner": status["final"]["winner_id"], "errors": errors,
                      "terminal_resume_additional_events": 0, "scientific_network_dispatches": 0}
            (folder / "browser-report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
            await browser.close()
    finally:
        server.terminate()
        await server.wait()


if __name__ == "__main__":
    asyncio.run(main())
