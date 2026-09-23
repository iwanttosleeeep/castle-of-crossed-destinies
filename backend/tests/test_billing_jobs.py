import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

from fastapi import HTTPException

from backend.app import main
from backend.app.accounts_api import fulfill_event, verify_event
from backend.app.commerce import Commerce
from backend.app.deepseek import call_text
from backend.app.jobs import Jobs, tasks, shutdown
from backend.app.metering import Payer, payer_context
from backend.app.schemas import CaseCreateRequest, Fact, FactConfirmation, ReportRequest
from backend.app.store import CaseStore


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CASTLE_DB_PATH": str(Path(self.temp.name)/"test.db"), "CASTLE_FREE_BUDGET_USD": "1", "CASTLE_PAID_BUDGET_USD": "1", "DEEPSEEK_API_KEY": "synthetic-host-key"})
        self.env.start()
        self.commerce = Commerce()
        self.login = self.commerce.register("reader", "a-long-test-password")
        self.account = self.login["account"]["id"]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_account_password_session_and_one_time_trial(self):
        self.assertEqual(self.commerce.authenticate("Bearer "+self.login["token"]), self.account)
        with self.commerce.transaction() as db:
            stored = db.execute("SELECT password FROM accounts").fetchone()[0]
        self.assertNotIn("a-long-test-password", stored)
        self.commerce.claim_trial(self.account)
        with self.assertRaises(HTTPException):
            self.commerce.claim_trial(self.account)
        self.commerce.logout("Bearer "+self.login["token"])
        with self.assertRaises(HTTPException):
            self.commerce.authenticate("Bearer "+self.login["token"])

    def test_concurrent_credit_reservations_never_overspend(self):
        self.commerce.claim_trial(self.account)
        def reserve(_):
            try:
                return self.commerce.reserve_call(self.account, None, "report", "trial", "deepseek-flash", 2)
            except HTTPException:
                return None
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(reserve, range(5)))
        self.assertEqual(sum(bool(r) for r in results), 2)
        self.assertEqual(self.commerce.account(self.account)["balances"]["trial"], 1)
        for call in filter(None, results):
            self.commerce.finish_call(call, False)
            self.commerce.finish_call(call, False)
        self.assertEqual(self.commerce.account(self.account)["balances"]["trial"], 5)

    def test_cost_budget_reserves_inflight_and_recovery_keeps_unknown_cost(self):
        with patch.dict(os.environ, {"CASTLE_FREE_BUDGET_USD": "0.01"}):
            self.commerce.claim_trial(self.account)
            call=self.commerce.reserve_call(self.account,"job","report:bazi","trial","deepseek-flash",2)
            self.commerce.reserve_attempt(call,"trial","deepseek-flash",8000)
            with self.assertRaises(HTTPException):
                self.commerce.reserve_attempt(call,"trial","deepseek-flash",8000)
            self.commerce.recover()
            self.assertEqual(self.commerce.account(self.account)["balances"]["trial"],5)
            with self.commerce.transaction() as db:
                row=db.execute("SELECT state,cost FROM attempts").fetchone()
            self.assertEqual(tuple(row),("uncertain",8000))

    def test_zero_budget_and_byok_no_fallback(self):
        old=main.store
        main.store=CaseStore(Path(self.temp.name)/"test.db")
        try:
            with self.assertRaises(HTTPException):
                main.resolve_payer("byok",None,None,None)
            payer,key,model=main.resolve_payer("byok",None,"user-key",None)
            self.assertEqual(key,"user-key")
            self.assertEqual(payer.mode,"byok")
            with patch.dict(os.environ,{"CASTLE_FREE_BUDGET_USD":"0"}):
                with self.assertRaises(HTTPException):
                    self.commerce.claim_trial(self.account)
        finally:
            main.store=old

    def test_signed_payment_idempotency_sandbox_and_live_rejection(self):
        with self.commerce.transaction() as db:
            db.execute("INSERT INTO orders VALUES ('order',?,'dossier',30,'price_test',0,'cs_test',0)",(self.account,))
        event={"id":"evt_a","livemode":False,"type":"checkout.session.completed","data":{"object":{"id":"cs_test","metadata":{"castle_order":"order"},"mode":"payment","livemode":False,"payment_status":"paid"}}}
        raw=json.dumps(event).encode();stamp=str(int(time.time()));secret="test-secret"
        sig=hmac.new(secret.encode(),stamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
        self.assertEqual(verify_event(raw,f"t={stamp},v1={sig}",secret),event)
        with self.assertRaises(HTTPException):
            verify_event(raw+b" ",f"t={stamp},v1={sig}",secret)
        with self.assertRaises(HTTPException):
            verify_event(raw,f"t=0,v1={sig}",secret)
        fulfill_event(self.commerce,event);fulfill_event(self.commerce,event)
        event["id"]="evt_second"
        fulfill_event(self.commerce,event)
        balances=self.commerce.account(self.account)["balances"]
        self.assertEqual(balances["sandbox"],30)
        self.assertEqual(balances["paid"],0)
        with self.assertRaises(HTTPException):
            self.commerce.reserve_call(self.account,None,"report","paid","deepseek-flash",2)
        event["livemode"]=True
        with self.assertRaises(HTTPException):
            fulfill_event(self.commerce,event)


class MeteringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"CASTLE_DB_PATH":str(Path(self.temp.name)/"test.db"),"CASTLE_FREE_BUDGET_USD":"2","DEEPSEEK_API_KEY":"synthetic-key"})
        self.env.start()
        self.commerce=Commerce()
        self.account=self.commerce.register("reader","a-long-test-password")["account"]["id"]
        self.commerce.claim_trial(self.account)
        self.marker=payer_context.set(Payer(self.commerce,"trial",self.account,"job","report:bazi",2))
        self.payload={"model":"deepseek-flash","messages":[{"role":"user","content":"synthetic chart"}],"max_tokens":1000}

    async def asyncTearDown(self):
        payer_context.reset(self.marker)
        self.env.stop();self.temp.cleanup()

    async def test_usage_record_and_durable_result_avoid_repeat_charge(self):
        response={"choices":[{"message":{"content":"中文报告"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":30,"prompt_cache_hit_tokens":50}}
        with patch("backend.app.deepseek.post_json",return_value=response) as provider:
            self.assertEqual(await call_text(self.payload,"private-user-key"),"中文报告")
            self.assertEqual(await call_text(self.payload,"private-user-key"),"中文报告")
        self.assertEqual(provider.call_count,1)
        self.assertEqual(self.commerce.account(self.account)["balances"]["trial"],3)
        with self.commerce.transaction() as db:
            row=db.execute("SELECT * FROM attempts").fetchone()
            all_data=str([dict(r) for r in db.execute("SELECT * FROM calls")])
        self.assertEqual(row["cost"],52)
        self.assertNotIn("private-user-key",all_data)

    async def test_failed_auth_refunds_without_retry_or_host_key_fallback(self):
        with patch("backend.app.deepseek.post_json",side_effect=HTTPError("https://api.deepseek.com",401,"Unauthorized",{},None)) as provider:
            with self.assertRaises(HTTPError):
                await call_text(self.payload,"bad-user-key")
        self.assertEqual(provider.call_count,1)
        self.assertEqual(provider.call_args.args[1],"bad-user-key")
        self.assertEqual(self.commerce.account(self.account)["balances"]["trial"],5)
        with self.commerce.transaction() as db:
            self.assertEqual(db.execute("SELECT cost FROM attempts").fetchone()[0],0)

    async def test_unknown_timeout_cost_kept_and_credits_refunded(self):
        with patch("backend.app.deepseek.post_json",side_effect=URLError("unknown")),patch("backend.app.deepseek.asyncio.sleep",new=AsyncMock()):
            with self.assertRaises(URLError):
                await call_text(self.payload,"test-key")
        self.assertEqual(self.commerce.account(self.account)["balances"]["trial"],5)
        with self.commerce.transaction() as db:
            rows=db.execute("SELECT state,cost FROM attempts").fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r[0]=="uncertain" and r[1]>0 for r in rows))


class DurableJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=main.store
        main.store=CaseStore(Path(self.temp.name)/"test.db")
        self.created=await main.create_case(CaseCreateRequest(systems=["bazi","ziwei","western"]))
        self.case_id=self.created["case_id"];self.token=self.created["resume_token"]
        for s in self.created["systems"]:
            await main.confirm_facts(self.case_id,s,FactConfirmation(facts=[Fact(id=s+".1",label="盘面",value="合成测试数据")]),self.token)
        self.runner=Jobs(Commerce(main.store.path))

    async def asyncTearDown(self):
        await shutdown()
        main.store=self.old
        self.temp.cleanup()

    async def test_partial_results_retry_only_failure_and_dedup(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def chamber(s,*args):
            if s=="bazi":return "八字报告",None
            entered.set();await release.wait();return "","模拟失败"
        with patch("backend.app.jobs.run_guided_chamber",new=chamber):
            job=await main.create_reports(self.case_id,self.token,"test-key",None,ReportRequest(systems=["bazi","ziwei"]))
            await entered.wait()
            partial=await main.restore_case(self.case_id,self.token)
            self.assertEqual(partial["reports"]["bazi"]["text"],"八字报告")
            duplicate=await main.create_reports(self.case_id,self.token,"test-key",None,ReportRequest(systems=["bazi","ziwei"]))
            self.assertEqual(duplicate["id"],job["id"])
            with self.assertRaises(HTTPException):
                await main.confirm_facts(self.case_id,"bazi",FactConfirmation(facts=[Fact(id="bazi.1",label="a",value="b")]),self.token)
            release.set();await asyncio.gather(*list(tasks))
        with patch("backend.app.jobs.run_guided_chamber",new=AsyncMock(return_value=("紫微报告",None))) as chamber,patch("backend.app.jobs.run_guided_tribunal",new=AsyncMock(return_value=("比较",None))):
            await main.retry_job(self.case_id,job["id"],self.token,"test-key")
            await asyncio.gather(*list(tasks))
            self.assertEqual(chamber.await_count,1)
            self.assertEqual(chamber.call_args.args[0],"ziwei")
        self.assertEqual(self.runner.get(job["id"])["state"],"completed")
        with patch("backend.app.jobs.run_guided_chamber",new=AsyncMock(return_value=("西占",None))) as chamber,patch("backend.app.jobs.run_guided_tribunal",new=AsyncMock(return_value=("新的比较",None))):
            await main.create_reports(self.case_id,self.token,"test-key",None)
            await asyncio.gather(*list(tasks))
            self.assertEqual(chamber.await_count,1)
            self.assertEqual(chamber.call_args.args[0],"western")

    async def test_restart_and_revision_prevent_stale_resume_and_delete(self):
        payload=main.authorize(self.case_id,self.token)
        payer=Payer(self.runner.commerce)
        job,_=self.runner.create(payload,"reports",["bazi"],"deepseek-flash",payer)
        self.runner.update(job["id"],"report:bazi",state="running")
        self.runner.recover()
        self.assertEqual(self.runner.get(job["id"])["state"],"interrupted")
        await main.confirm_facts(self.case_id,"bazi",FactConfirmation(facts=[Fact(id="bazi.1",label="new",value="new")]),self.token)
        with self.assertRaises(HTTPException):
            await main.retry_job(self.case_id,job["id"],self.token,"test-key")
        await main.delete_case(self.case_id,self.token)
        with self.assertRaises(HTTPException):
            await main.restore_case(self.case_id,self.token)

    async def test_trial_shape_is_enforced_before_provider(self):
        with self.assertRaises(HTTPException) as denied:
            await main.create_reports(self.case_id,self.token,None,None,ReportRequest(systems=["bazi"]),"trial")
        self.assertEqual(denied.exception.status_code,422)

    async def test_empty_participant_selection_never_defaults_to_all(self):
        with self.assertRaises(HTTPException) as denied:
            await main.create_reports(self.case_id,self.token,"test-key",None,ReportRequest(systems=[]))
        self.assertEqual(denied.exception.status_code,422)

    async def test_insufficient_points_rejected_before_task_creation(self):
        commerce=self.runner.commerce
        account=commerce.register("short_balance","a-long-test-password")["account"]["id"]
        with commerce.transaction() as db:
            db.execute("INSERT INTO ledger VALUES ('grant',?,'paid',2,'synthetic',?)",(account,time.time()))
        with self.assertRaises(HTTPException) as denied:
            self.runner.create(main.authorize(self.case_id,self.token),"reports",["bazi","ziwei"],"deepseek-flash",Payer(commerce,"paid",account))
        self.assertEqual(denied.exception.status_code,402)
        self.assertEqual(self.runner.for_case(self.case_id),[])


if __name__ == "__main__":
    unittest.main()
