"""Durable task/step state; credentials live only in the executing coroutine.

Run one API worker. A restart marks tasks interrupted; the visitor supplies their
credentials again to resume, retaining every successful step.
"""
import asyncio
import hashlib
import json
import time
from dataclasses import replace
from uuid import uuid4

from fastapi import HTTPException

from .commerce import Commerce
from .guided_reports import run_guided_chamber, run_guided_tribunal, ROOT
from .guided_debate import guided_answer, guided_rebuttal, guided_summary
from .metering import Payer, payer_context, GenerationStopped
from .providers import SYSTEMS
from .schemas import Fact


ACTIVE = {"queued", "running", "stopping"}
tasks: set[asyncio.Task] = set()


class Jobs:
    def __init__(self, commerce: Commerce):
        self.commerce = commerce
        with commerce.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_case_job_v2 ON jobs(case_id) WHERE state IN ('queued','running','stopping')")
            db.execute("DROP INDEX IF EXISTS one_active_case_job")

    def recover(self):
        with self.commerce.transaction() as db:
            for row in db.execute("SELECT * FROM jobs WHERE state IN ('queued','running','stopping')").fetchall():
                job = json.loads(row["payload"])
                stopped = job["state"] == "stopping"
                job["state"] = "cancelled" if stopped else "interrupted"
                for step in job["steps"].values():
                    if stopped and step["state"] != "completed":
                        step.update(state="cancelled", error=None)
                    elif step["state"] == "running":
                        step.update(state="failed", error="服务器已重启，请继续未完成部分")
                self._save(db, job)

    @staticmethod
    def _save(db, job):
        job["updated"] = time.time()
        db.execute("UPDATE jobs SET state=?,payload=? WHERE id=?", (job["state"], json.dumps(job, ensure_ascii=False), job["id"]))

    def get(self, job_id):
        with self.commerce.transaction() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        return json.loads(row[0])

    def for_case(self, case_id):
        with self.commerce.transaction() as db:
            rows = db.execute("SELECT payload FROM jobs WHERE case_id=? ORDER BY created DESC LIMIT 20", (case_id,)).fetchall()
        return [self.public(json.loads(row[0])) for row in rows]

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if k not in {"account_id", "fingerprint"}}

    def create(self, payload, kind, systems, model, payer, question=""):
        revision = payload.get("facts_revision", 0)
        skill_root = ROOT / "skills" / "guided-chamber-reading"
        skill_hash = hashlib.sha256((skill_root / "SKILL.md").read_bytes() + (skill_root / "references/personas.json").read_bytes()).hexdigest()
        signature = json.dumps([kind, systems, model, revision, question, skill_hash, payer.mode, payer.account_id])
        fingerprint = hashlib.sha256(signature.encode()).hexdigest()
        with self.commerce.transaction() as db:
            current = json.loads(db.execute("SELECT payload FROM cases WHERE id=?", (payload["case_id"],)).fetchone()[0])
            if current.get("facts_revision", 0) != revision:
                raise HTTPException(409, "事实已更新，请刷新后再试")
            rows = db.execute("SELECT payload FROM jobs WHERE case_id=? ORDER BY created DESC", (payload["case_id"],)).fetchall()
            for row in rows:
                old = json.loads(row[0])
                if old["state"] in ACTIVE:
                    if old["fingerprint"] == fingerprint:
                        return old, False
                    raise HTTPException(409, "本案已有任务执行中，请等它完成")
                if old["fingerprint"] == fingerprint:
                    # Return even failed jobs; resumption must be explicit.
                    return old, False
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','stopping')").fetchone()[0] >= 24:
                raise HTTPException(429, "城堡正在处理较多任务，请稍后再来")
            job_id = uuid4().hex
            phases = ["report"] if kind == "reports" else ["answer", "rebuttal"]
            steps = {f"{phase}:{system}": {"state": "queued", "text": "", "error": None} for phase in phases for system in systems}
            if kind == "debate" or len(systems) > 1:
                steps["tribunal" if kind == "reports" else "summary"] = {"state": "queued", "text": "", "error": None}
            job = {"id": job_id, "case_id": payload["case_id"], "kind": kind, "state": "queued", "systems": systems,
                   "model": model, "mode": payer.mode, "account_id": payer.account_id, "facts_revision": revision,
                   "question": question, "fingerprint": fingerprint, "skill_hash": skill_hash, "steps": steps, "created": time.time()}
            if kind == "reports":
                for row in rows:
                    prior = json.loads(row[0])
                    if prior["kind"] == "reports" and prior["facts_revision"] == revision and prior["model"] == model and prior.get("skill_hash") == skill_hash:
                        for name, saved in prior["steps"].items():
                            if name.startswith("report:") and name in steps and saved["state"] == "completed" and steps[name]["state"] != "completed":
                                steps[name] = dict(saved)
            self.check_credits(db, job)
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)", (job_id, payload["case_id"], "queued", json.dumps(job), time.time()))
        return job, True

    def resume(self, job_id, payer):
        with self.commerce.transaction() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "任务不存在")
            job = json.loads(row[0])
            if job["account_id"] != payer.account_id or job["mode"] != payer.mode:
                raise HTTPException(403, "继续任务时请使用原账户与付费方式")
            if job["state"] in ACTIVE or job["state"] == "completed":
                return job, False
            case = json.loads(db.execute("SELECT payload FROM cases WHERE id=?", (job["case_id"],)).fetchone()[0])
            if case.get("facts_revision", 0) != job["facts_revision"]:
                raise HTTPException(409, "事实已经修改，请基于新版本生成报告")
            if db.execute("SELECT 1 FROM jobs WHERE case_id=? AND state IN ('queued','running','stopping')", (job["case_id"],)).fetchone():
                raise HTTPException(409, "本案已有其他任务执行中")
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','stopping')").fetchone()[0] >= 24:
                raise HTTPException(429, "城堡正在处理较多任务，请稍后再来")
            job["state"] = "queued"
            for step in job["steps"].values():
                if step["state"] != "completed":
                    step.update(state="queued", error=None)
            self.check_credits(db, job)
            self._save(db, job)
        return job, True

    def request_stop(self, job_id):
        # No task.cancel(): a thread-backed provider request cannot be recalled.
        with self.commerce.transaction() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "任务不存在")
            job = json.loads(row[0])
            if job["state"] in ACTIVE:
                job["state"] = "stopping"
                self._save(db, job)
        return job

    def check_credits(self, db, job):
        if job["mode"] == "byok":
            return
        required = 0
        for name, step in job["steps"].items():
            cached = db.execute("SELECT 1 FROM calls WHERE job_id=? AND step=? AND state='settled' AND result IS NOT NULL", (job["id"], name)).fetchone()
            if step["state"] != "completed" and not cached:
                required += 2 if name.startswith("report:") else 1
        available = self.commerce.balance(db, job["account_id"], job["mode"])
        if available < required:
            raise HTTPException(402, f"本轮还需 {required} 点，当前可用 {available} 点。请减少参与密室、购买额度或使用自己的 Key。")

    def update(self, job_id, step_id=None, **values):
        with self.commerce.transaction() as db:
            job = json.loads(db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
            if step_id:
                job["steps"][step_id].update(values)
            else:
                job.update(values)
            self._save(db, job)
            row = db.execute("SELECT payload FROM cases WHERE id=?", (job["case_id"],)).fetchone()
            if row:
                case = json.loads(row[0])
                if case.get("facts_revision", 0) == job["facts_revision"]:
                    self.publish(case, job)
                    db.execute("UPDATE cases SET payload=? WHERE id=?", (json.dumps(case, ensure_ascii=False), job["case_id"]))
        return job

    @staticmethod
    def publish(case, job):
        if job["kind"] == "reports":
            for system in job["systems"]:
                step = job["steps"]["report:"+system]
                if step["state"] == "completed":
                    case["reports"][system] = {"system_id": system, "display_name": SYSTEMS[system], "text": step["text"], "facts_revision": job["facts_revision"], "job_id": job["id"]}
            step = job["steps"].get("tribunal", {})
            if step.get("state") == "completed":
                case["tribunal"] = {"summary": step["text"], "disclaimer": "跨体系叙述比较，不代表科学准确率。", "job_id": job["id"]}
        else:
            hearing = {"id": job["id"], "question": job["question"], "facts_revision": job["facts_revision"], "state": job["state"], "guided_summary": job["steps"]["summary"]["text"],
                       "guided_answers": [], "guided_rebuttals": []}
            for phase, field in [("answer", "guided_answers"), ("rebuttal", "guided_rebuttals")]:
                hearing[field] = [{"system_id": s, "text": job["steps"][f"{phase}:{s}"]["text"]} for s in job["systems"] if job["steps"][f"{phase}:{s}"]["state"] == "completed"]
            case["debates"] = [h for h in case["debates"] if h["id"] != job["id"]] + [hearing]
        case["status"] = "generating" if job["state"] in ACTIVE else ("reports_ready" if job["kind"] == "reports" else "hearing_complete")

    def launch(self, job, payload, key, payer):
        task = asyncio.create_task(self.run(job, payload, key, payer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def run(self, job, payload, key, payer):
        job_id = job["id"]
        def should_stop():
            return self.get(job_id)["state"] == "stopping"

        if not should_stop():
            self.update(job_id, state="running")
        facts = {s: [Fact.model_validate(f) for f in payload["confirmed_facts"][s]] for s in job["systems"]}

        async def step(name, fn, *args):
            if self.get(job_id)["steps"][name]["state"] == "completed":
                return
            if should_stop():
                self.update(job_id, name, state="cancelled", error=None)
                return
            self.update(job_id, name, state="running", error=None)
            token = payer_context.set(replace(payer, job_id=job_id, step=name, credits=2 if name.startswith("report:") else 1, should_stop=should_stop))
            try:
                text, warning = await fn(*args)
                if warning or not text:
                    self.update(job_id, name, state="failed", error=warning or "未返回正文")
                else:
                    self.update(job_id, name, state="completed", text=text, error=None)
            except GenerationStopped:
                self.update(job_id, name, state="cancelled", error=None)
            except Exception as exc:
                # Never persist provider exception strings (they can include credentials or body).
                error = exc.detail if isinstance(exc, HTTPException) else "生成未完成，请继续此步骤"
                self.update(job_id, name, state="failed", error=error)
            finally:
                payer_context.reset(token)

        try:
            if job["kind"] == "reports":
                await asyncio.gather(*(step("report:"+s, run_guided_chamber, s, SYSTEMS[s], facts[s], key, job["model"]) for s in job["systems"]))
                current = self.get(job_id)
                if all(current["steps"]["report:"+s]["state"] == "completed" for s in job["systems"]) and "tribunal" in current["steps"]:
                    reports = {s: current["steps"]["report:"+s]["text"] for s in job["systems"]}
                    await step("tribunal", run_guided_tribunal, reports, key, job["model"])
            else:
                await asyncio.gather(*(step("answer:"+s, guided_answer, s, facts[s], job["question"], key, job["model"]) for s in job["systems"]))
                current = self.get(job_id)
                if all(current["steps"]["answer:"+s]["state"] == "completed" for s in job["systems"]):
                    answers = [{"system_id": s, "text": current["steps"]["answer:"+s]["text"]} for s in job["systems"]]
                    await asyncio.gather(*(step("rebuttal:"+s, guided_rebuttal, s, facts[s], job["question"], current["steps"]["answer:"+s]["text"], answers, key, job["model"]) for s in job["systems"]))
                    current = self.get(job_id)
                    if all(current["steps"]["rebuttal:"+s]["state"] == "completed" for s in job["systems"]):
                        rebuttals = [{"system_id": s, "text": current["steps"]["rebuttal:"+s]["text"]} for s in job["systems"]]
                        await step("summary", guided_summary, job["question"], answers, rebuttals, key, job["model"])
            current = self.get(job_id)
            if all(s["state"] == "completed" for s in current["steps"].values()):
                self.update(job_id, state="completed")
            elif should_stop():
                for name, saved in current["steps"].items():
                    if saved["state"] != "completed":
                        self.update(job_id, name, state="cancelled", error=None)
                self.update(job_id, state="cancelled")
            else:
                self.update(job_id, state="partial")
        except asyncio.CancelledError:
            # Keep a stop request durable for startup recovery.
            if not should_stop():
                self.update(job_id, state="interrupted")
            raise
        except Exception:
            self.update(job_id, state="interrupted")


async def shutdown():
    for task in list(tasks):
        task.cancel()
    if tasks:
        await asyncio.gather(*list(tasks), return_exceptions=True)
