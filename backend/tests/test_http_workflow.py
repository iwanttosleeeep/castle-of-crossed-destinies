"""Exercise real ASGI routing/headers/bodies without external servers or API spend."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import main
from backend.app.jobs import tasks


async def request(method, path, body=None, headers=None):
    wire = json.dumps(body).encode() if body is not None else b""
    request_headers = {"content-type":"application/json", **(headers or {})}
    scope = {"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},
             "http_version":"1.1","scheme":"http","method":method,"path":path,
             "raw_path":path.encode(),"root_path":"","query_string":b"",
             "headers":[(k.lower().encode(),v.encode()) for k,v in request_headers.items()],
             "client":("127.0.0.1",12345),"server":("testserver",80)}
    sent = False
    done = asyncio.Event()
    messages = []
    async def receive():
        nonlocal sent
        if not sent:
            sent=True
            return {"type":"http.request","body":wire,"more_body":False}
        await done.wait()
        return {"type":"http.disconnect"}
    async def send(message):
        messages.append(message)
        if message["type"]=="http.response.body" and not message.get("more_body"):
            done.set()
    await main.app(scope,receive,send)
    start=next(m for m in messages if m["type"]=="http.response.start")
    raw=b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
    return start["status"],json.loads(raw),dict(start["headers"])


class HTTPWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old_store=main.store
        self.env=patch.dict(os.environ,{"CASTLE_DB_PATH":str(Path(self.temp.name)/"http.db"),"CASTLE_FREE_BUDGET_USD":"1","CASTLE_PAID_BUDGET_USD":"0","DEEPSEEK_API_KEY":"synthetic-server-key","CASTLE_PAYMENT_MODE":"disabled"})
        self.env.start()
        self.lifespan=main.lifespan(main.app)
        await self.lifespan.__aenter__()

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None,None,None)
        main.store=self.old_store
        self.env.stop();self.temp.cleanup()

    async def test_account_trial_reports_poll_repeat_and_delete(self):
        status,registered,_=await request("POST","/account/register",{"username":"http_reader","password":"synthetic-test-password"})
        self.assertEqual(status,200)
        account_headers={"Authorization":"Bearer "+registered["token"]}
        status,account,_=await request("POST","/account/trial",headers=account_headers)
        self.assertEqual(status,200);self.assertEqual(account["balances"]["trial"],5)
        status,case,_=await request("POST","/cases",{"systems":["bazi","ziwei"]})
        self.assertEqual(status,200)
        case_headers={"X-Case-Token":case["resume_token"]}
        for s in case["systems"]:
            status,_,_=await request("PUT",f"/cases/{case['case_id']}/facts/{s}",{"facts":[{"id":s+".1","label":"配置","value":"合成测试资料"}]},case_headers)
            self.assertEqual(status,200)
        status,_,_=await request("POST",f"/cases/{case['case_id']}/reports",headers=case_headers)
        self.assertEqual(status,401)  # An operator Key is NOT an anonymous fallback.
        response={"choices":[{"message":{"content":"## 测试证词\n基于合成资料的中文测试正文。"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":40}}
        paid_headers={**case_headers,**account_headers,"X-Payment-Mode":"trial"}
        with patch("backend.app.deepseek.post_json",return_value=response) as provider:
            status,job,_=await request("POST",f"/cases/{case['case_id']}/reports",{"systems":["bazi","ziwei"]},paid_headers)
            self.assertEqual(status,202)
            await asyncio.gather(*list(tasks))
            status,restored,headers=await request("GET",f"/cases/{case['case_id']}",headers=case_headers)
            self.assertEqual(headers[b"cache-control"],b"no-store")
            self.assertEqual(restored["jobs"][0]["state"],"completed")
            self.assertEqual(len(restored["reports"]),2)
            status,duplicate,_=await request("POST",f"/cases/{case['case_id']}/reports",{"systems":["bazi","ziwei"]},paid_headers)
            self.assertEqual(duplicate["id"],job["id"])
            self.assertEqual(provider.call_count,3)
            self.assertTrue(all(c.args[1]=="synthetic-server-key" for c in provider.call_args_list))
        _,account,_=await request("GET","/account",headers=account_headers)
        self.assertEqual(account["balances"]["trial"],0)
        status,_,_=await request("DELETE",f"/cases/{case['case_id']}",headers={"X-Case-Token":"wrong"})
        self.assertEqual(status,404)
        status,_,_=await request("DELETE",f"/cases/{case['case_id']}",headers=case_headers)
        self.assertEqual(status,200)
        with main.Commerce().transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM calls WHERE result IS NOT NULL").fetchone()[0],0)

    async def test_defaults_do_not_offer_checkout_or_allow_unfunded_hosted_calls(self):
        status,config,_=await request("GET","/billing/config")
        self.assertFalse(config["hosted_available"])
        status,_,_=await request("POST","/billing/checkout",{"pack":"dossier"})
        self.assertEqual(status,401)
        status,_,_=await request("POST","/billing/webhook",{"type":"checkout.session.completed"})
        self.assertEqual(status,503)


if __name__ == "__main__":
    unittest.main()
