"""Transactional credits, accounts and provider expenditure. Never stores API keys."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException

from .store import _database_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 trial_claimed INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ledger (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, bucket TEXT NOT NULL,
 delta INTEGER NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
 id TEXT PRIMARY KEY, account_id TEXT, job_id TEXT, step TEXT, mode TEXT NOT NULL,
 model TEXT NOT NULL, credits INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, call_id TEXT NOT NULL, mode TEXT NOT NULL, model TEXT NOT NULL,
 reserved INTEGER NOT NULL, cost INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
 usage TEXT, elapsed REAL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, pack TEXT NOT NULL, credits INTEGER NOT NULL,
 price_id TEXT NOT NULL, live INTEGER NOT NULL, session_id TEXT UNIQUE, fulfilled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS payment_events (id TEXT PRIMARY KEY, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, until REAL NOT NULL);
"""


def usd_micro(value: str) -> int:
    return int(Decimal(value) * 1_000_000)


def config() -> dict:
    hosted = bool(os.getenv("DEEPSEEK_API_KEY"))
    return {
        "hosted_available": hosted and usd_micro(os.getenv("CASTLE_PAID_BUDGET_USD", "0")) > 0,
        "trial_available": hosted and usd_micro(os.getenv("CASTLE_FREE_BUDGET_USD", "0")) > 0,
        "trial_credits": 5,
        "prices": {"report": 2, "tribunal": 1, "answer": 1, "rebuttal": 1, "summary": 1, "extraction": 2},
        "payment_mode": os.getenv("CASTLE_PAYMENT_MODE", "disabled"),
        "packs": [{"id": "dossier", "name": "完整案卷包", "credits": 30},
                  {"id": "hearing", "name": "追加庭审包", "credits": 15}],
    }


class Commerce:
    def __init__(self, path=None):
        self.path = path or _database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript(SCHEMA)
            if "result" not in {r[1] for r in db.execute("PRAGMA table_info(calls)")}:
                db.execute("ALTER TABLE calls ADD COLUMN result TEXT")
                db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db

    def rate(self, key: str, limit: int, seconds=60):
        # Hash IP/username identifiers; this table is pruned on every access.
        key = hashlib.sha256(key.encode()).hexdigest()
        now = time.time()
        with self.transaction() as db:
            db.execute("DELETE FROM rate_limits WHERE until < ?", (now,))
            row = db.execute("SELECT count FROM rate_limits WHERE key=?", (key,)).fetchone()
            if row and row[0] >= limit:
                raise HTTPException(429, "操作过于频繁，请稍后再试")
            db.execute("INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now+seconds))

    @staticmethod
    def password_hash(password: str, salt: str) -> str:
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

    def register(self, username: str, password: str):
        salt = secrets.token_hex(16)
        encoded = salt + ":" + self.password_hash(password, salt)
        try:
            with self.transaction() as db:
                db.execute("INSERT INTO accounts(id,username,password,created) VALUES (?,?,?,?)", (uuid4().hex, username.lower(), encoded, time.time()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名已被使用")
        return self.login(username, password)

    def login(self, username: str, password: str):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username.lower(),)).fetchone()
        salt, expected = row["password"].split(":") if row else ("00" * 16, "00" * 64)
        valid = hmac.compare_digest(self.password_hash(password, salt), expected)
        if not row or not valid:
            raise HTTPException(401, "用户名或密码不正确")
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (self.hash_token(token), row["id"], time.time()+7*86400))
        return {"token": token, "account": self.account(row["id"])}

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, authorization: str | None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "请先登录 Castle 账户，或切换自带 Key")
        with closing(self.connect()) as db:
            row = db.execute("SELECT account_id FROM sessions WHERE token_hash=? AND expires>?", (self.hash_token(authorization[7:]), time.time())).fetchone()
        if not row:
            raise HTTPException(401, "登录已过期，请重新登录")
        return row[0]

    def logout(self, authorization):
        with self.transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (self.hash_token((authorization or "")[7:]),))

    @staticmethod
    def balance(db, account_id, bucket):
        return db.execute("SELECT COALESCE(SUM(delta),0) FROM ledger WHERE account_id=? AND bucket=?", (account_id, bucket)).fetchone()[0]

    def account(self, account_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT id,username,trial_claimed FROM accounts WHERE id=?", (account_id,)).fetchone()
            balances = {bucket: self.balance(db, account_id, bucket) for bucket in ("paid", "trial", "sandbox")}
            history = [dict(r) for r in db.execute("SELECT bucket,delta,reason,created FROM ledger WHERE account_id=? ORDER BY created DESC LIMIT 25", (account_id,))]
        return dict(row) | {"balances": balances, "ledger": history}

    def claim_trial(self, account_id):
        if not config()["trial_available"]:
            raise HTTPException(409, "免费 AI 体验尚未开放；排盘与示范庭审仍可使用")
        with self.transaction() as db:
            self.check_budget(db, "trial", 1)
            changed = db.execute("UPDATE accounts SET trial_claimed=1 WHERE id=? AND trial_claimed=0", (account_id,)).rowcount
            if not changed:
                raise HTTPException(409, "本账户已经领取过体验额度")
            db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (uuid4().hex, account_id, "trial", 5, "两间密室体验", time.time()))
        return self.account(account_id)

    def check_budget(self, db, mode, amount):
        if mode == "byok":
            return
        variable = "CASTLE_FREE_BUDGET_USD" if mode == "trial" else "CASTLE_PAID_BUDGET_USD"
        ceiling = usd_micro(os.getenv(variable, "0"))
        spent = db.execute("SELECT COALESCE(SUM(CASE WHEN state='reserved' THEN reserved ELSE cost END),0) FROM attempts WHERE mode=?", (mode,)).fetchone()[0]
        if spent + amount > ceiling:
            raise HTTPException(402, "本服务的 AI 预算暂不可用，请稍后再试或使用自己的 Key")

    def reserve_call(self, account_id, job_id, step, mode, model, credits):
        call_id = uuid4().hex
        with self.transaction() as db:
            if mode != "byok":
                if not account_id or self.balance(db, account_id, mode) < credits:
                    raise HTTPException(402, "额度不足，请购买案卷包或使用自己的 Key")
                db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (call_id, account_id, mode, -credits, f"预留：{step}", time.time()))
            db.execute("INSERT INTO calls(id,account_id,job_id,step,mode,model,credits,state,created) VALUES (?,?,?,?,?,?,?,?,?)", (call_id, account_id, job_id, step, mode, model, credits, "reserved", time.time()))
        return call_id

    def reserve_attempt(self, call_id, mode, model, upper_cost):
        attempt_id = uuid4().hex
        with self.transaction() as db:
            self.check_budget(db, mode, upper_cost)
            db.execute("INSERT INTO attempts(id,call_id,mode,model,reserved,state,created) VALUES (?,?,?,?,?,'reserved',?)", (attempt_id, call_id, mode, model, upper_cost, time.time()))
        return attempt_id

    def finish_attempt(self, attempt_id, cost, usage, elapsed, uncertain=False):
        with self.transaction() as db:
            db.execute("UPDATE attempts SET state=?,cost=?,usage=?,elapsed=? WHERE id=? AND state='reserved'", ("uncertain" if uncertain else "settled", cost, json.dumps(usage), elapsed, attempt_id))

    def cached_result(self, job_id, step):
        if not job_id:
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT result FROM calls WHERE job_id=? AND step=? AND state='settled' AND result IS NOT NULL ORDER BY created DESC LIMIT 1", (job_id, step)).fetchone()
        return json.loads(row[0]) if row else None

    def finish_call(self, call_id, success, result=None):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM calls WHERE id=? AND state='reserved'", (call_id,)).fetchone()
            if not row:
                return
            if not success and row["mode"] != "byok":
                db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", ("refund-"+call_id, row["account_id"], row["mode"], row["credits"], "未完成，退还预留额度", time.time()))
            db.execute("UPDATE calls SET state=?,result=? WHERE id=?", ("settled" if success else "refunded", json.dumps(result, ensure_ascii=False) if success and result is not None and row["job_id"] else None, call_id))

    def recover(self):
        # Interrupted requests may have incurred upstream charges. Keep their full cost reserve.
        with self.transaction() as db:
            db.execute("UPDATE attempts SET state='uncertain',cost=reserved WHERE state='reserved'")
            rows = db.execute("SELECT id FROM calls WHERE state='reserved'").fetchall()
        for row in rows:
            self.finish_call(row[0], False)

    def usage_summary(self, account_id):
        with closing(self.connect()) as db:
            return [dict(r) for r in db.execute("SELECT a.mode,a.model,COUNT(*) AS attempts,SUM(a.cost) AS estimated_micro_usd,SUM(a.state='uncertain') AS uncertain FROM attempts a JOIN calls c ON c.id=a.call_id WHERE c.account_id=? GROUP BY a.mode,a.model", (account_id,))]
