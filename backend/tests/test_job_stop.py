"""Cooperative stop tests: no real provider traffic or visitor data."""
import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import URLError

from fastapi import HTTPException

from backend.app import main
from backend.app.commerce import Commerce
from backend.app.jobs import Jobs, shutdown, tasks
from backend.app.metering import Payer
from backend.app.schemas import CaseCreateRequest, Fact, FactConfirmation
from backend.app.store import CaseStore
from backend.tests.test_http_workflow import request


RESPONSE = {"choices": [{"message": {"content": "合成测试证词"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30}}


class StopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = main.store
        self.env = patch.dict(os.environ, {"CASTLE_DB_PATH": str(Path(self.temp.name)/"stop.db"),
                                         "CASTLE_PAID_BUDGET_USD": "1"})
        self.env.start()
        main.store = CaseStore()
        created = await main.create_case(CaseCreateRequest(systems=["bazi", "ziwei"]))
        self.case_id, self.token = created["case_id"], created["resume_token"]
        for system in created["systems"]:
            await main.confirm_facts(self.case_id, system, FactConfirmation(facts=[
                Fact(id=system+".1", label="盘面", value="仅供测试")]), self.token)
        self.commerce = Commerce()
        self.runner = Jobs(self.commerce)
        self.account = self.commerce.register("stop_reader", "synthetic-test-password")["account"]["id"]
        with self.commerce.transaction() as db:
            db.execute("INSERT INTO ledger VALUES ('test-grant',?,'paid',20,'synthetic',?)", (self.account, time.time()))
        self.payer = Payer(self.commerce, "paid", self.account)

    async def asyncTearDown(self):
        await shutdown()
        main.store = self.old
        self.env.stop()
        self.temp.cleanup()

    def create(self, kind="reports"):
        payload = main.authorize(self.case_id, self.token)
        job, _ = self.runner.create(payload, kind, ["bazi", "ziwei"], "deepseek-flash", self.payer, "测试问题" if kind == "debate" else "")
        return job, payload

    async def test_stop_before_launch_authorization_and_restart(self):
        job, payload = self.create()
        route = f"/cases/{self.case_id}/jobs/{job['id']}/stop"
        status, _, _ = await request("POST", route, headers={"X-Case-Token": "wrong"})
        self.assertEqual(status, 404)
        other = await main.create_case(CaseCreateRequest(systems=["bazi"]))
        status, _, _ = await request("POST", f"/cases/{other['case_id']}/jobs/{job['id']}/stop", headers={"X-Case-Token": other["resume_token"]})
        self.assertEqual(status, 404)
        status, stopped, _ = await request("POST", route, headers={"X-Case-Token": self.token})
        self.assertEqual(status, 202)
        self.assertEqual(stopped["state"], "stopping")
        with patch("backend.app.deepseek.post_json") as provider:
            await self.runner.run(job, payload, "synthetic-key", self.payer)
            provider.assert_not_called()
        self.assertEqual(self.runner.get(job["id"])["state"], "cancelled")
        self.assertEqual(self.commerce.account(self.account)["balances"]["paid"], 20)
        resumed, _ = self.runner.resume(job["id"], self.payer)
        self.runner.request_stop(resumed["id"])
        self.runner.recover()
        recovered = self.runner.get(job["id"])
        self.assertEqual(recovered["state"], "cancelled")
        self.assertTrue(all(s["state"] == "cancelled" for s in recovered["steps"].values()))

    async def test_inflight_settles_queued_refunds_and_resume_only_unfinished(self):
        job, payload = self.create()
        entered, release = threading.Event(), threading.Event()
        def provider(*_):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test gate")
            return RESPONSE
        with patch("backend.app.deepseek.provider_slots", asyncio.Semaphore(1)), patch("backend.app.deepseek.post_json", side_effect=provider) as upstream:
            self.runner.launch(job, payload, "synthetic-key", self.payer)
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                stopped = await main.stop_job(self.case_id, job["id"], self.token)
                self.assertEqual(stopped["state"], "stopping")
                for operation in [main.delete_case(self.case_id, self.token), main.confirm_facts(self.case_id, "bazi", FactConfirmation(facts=[Fact(id="x", label="x", value="x")]), self.token)]:
                    with self.assertRaises(HTTPException) as denied:
                        await operation
                    self.assertEqual(denied.exception.status_code, 409)
                # Repeated stops are idempotent; retry cannot race the settling request.
                self.runner.request_stop(job["id"])
                _, launch = self.runner.resume(job["id"], self.payer)
                self.assertFalse(launch)
            finally:
                release.set()
                await asyncio.gather(*list(tasks))
            self.assertEqual(upstream.call_count, 1)
        saved = self.runner.get(job["id"])
        self.assertEqual(saved["state"], "cancelled")
        self.assertEqual(saved["steps"]["report:bazi"]["state"], "completed")
        self.assertEqual(saved["steps"]["report:ziwei"]["state"], "cancelled")
        self.assertEqual(saved["steps"]["tribunal"]["state"], "cancelled")
        self.assertEqual(self.commerce.account(self.account)["balances"]["paid"], 18)
        self.assertEqual(len(main.authorize(self.case_id, self.token)["reports"]), 1)
        with patch("backend.app.deepseek.post_json", return_value=RESPONSE) as upstream:
            resumed, launch = self.runner.resume(job["id"], self.payer)
            self.assertTrue(launch)
            await self.runner.run(resumed, payload, "synthetic-key", self.payer)
            self.assertEqual(upstream.call_count, 2)  # ziwei + tribunal, not bazi
        self.assertEqual(self.commerce.account(self.account)["balances"]["paid"], 15)
        with self.commerce.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM calls WHERE state='reserved'").fetchone()[0], 0)

    async def test_stop_blocks_automatic_provider_retry(self):
        job, payload = self.create()
        def provider(*_):
            self.runner.request_stop(job["id"])
            raise URLError("synthetic uncertain failure")
        with patch("backend.app.deepseek.provider_slots", asyncio.Semaphore(1)), patch("backend.app.deepseek.post_json", side_effect=provider) as upstream:
            await self.runner.run(job, payload, "synthetic-key", self.payer)
            self.assertEqual(upstream.call_count, 1)
        self.assertEqual(self.runner.get(job["id"])["state"], "cancelled")
        self.assertEqual(self.commerce.account(self.account)["balances"]["paid"], 20)
        with self.commerce.transaction() as db:
            rows = db.execute("SELECT state,cost FROM attempts").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "uncertain")
        self.assertGreater(rows[0]["cost"], 0)

    async def test_stop_after_answers_does_not_start_rebuttal_or_summary(self):
        job, payload = self.create("debate")
        entered, release = asyncio.Event(), asyncio.Event()
        async def answer(system, *_):
            if system == "ziwei":
                entered.set()
                await release.wait()
            return "合成独立回答", None
        with patch("backend.app.jobs.guided_answer", new=answer), patch("backend.app.jobs.guided_rebuttal", new=AsyncMock()) as rebuttal, patch("backend.app.jobs.guided_summary", new=AsyncMock()) as summary:
            self.runner.launch(job, payload, "synthetic-key", self.payer)
            await entered.wait()
            self.runner.request_stop(job["id"])
            release.set()
            await asyncio.gather(*list(tasks))
            rebuttal.assert_not_called()
            summary.assert_not_called()
        hearing = main.authorize(self.case_id, self.token)["debates"][0]
        self.assertEqual(len(hearing["guided_answers"]), 2)
        self.assertEqual(hearing["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
