import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Annotated
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .commerce import Commerce, config


router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=10, max_length=128)


class Purchase(BaseModel):
    pack: str


@router.get("/billing/config")
async def billing_config():
    return config()


@router.post("/account/register")
async def register(body: Credentials, request: Request):
    commerce = Commerce()
    commerce.rate("register:"+(request.client.host if request.client else "unknown"), 5, 3600)
    return await asyncio.to_thread(commerce.register, body.username, body.password)


@router.post("/account/login")
async def login(body: Credentials, request: Request):
    commerce = Commerce()
    commerce.rate("login:"+(request.client.host if request.client else "unknown"), 10, 300)
    commerce.rate("login-user:"+body.username.lower(), 15, 300)
    return await asyncio.to_thread(commerce.login, body.username, body.password)


@router.get("/account")
async def account(authorization: Annotated[str | None, Header()] = None):
    commerce = Commerce()
    account_id = commerce.authenticate(authorization)
    return commerce.account(account_id) | {"usage": commerce.usage_summary(account_id)}


@router.post("/account/logout")
async def logout(authorization: Annotated[str | None, Header()] = None):
    Commerce().logout(authorization)
    return {"ok": True}


@router.post("/account/trial")
async def trial(authorization: Annotated[str | None, Header()] = None):
    commerce = Commerce()
    return commerce.claim_trial(commerce.authenticate(authorization))


def stripe_post(fields, order_id):
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_") or os.getenv("CASTLE_PAYMENT_MODE") != "test":
        raise HTTPException(503, "测试收银台尚未配置；真实收款未启用")
    request = URLRequest("https://api.stripe.com/v1/checkout/sessions", data=urlencode(fields).encode(),
                         headers={"Authorization": "Bearer "+key, "Idempotency-Key": order_id})
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read())
    except Exception:
        raise HTTPException(502, "测试收银台暂不可用，请稍后再试")


@router.post("/billing/checkout")
async def checkout(body: Purchase, authorization: Annotated[str | None, Header()] = None):
    commerce = Commerce()
    account_id = commerce.authenticate(authorization)
    commerce.rate("checkout:"+account_id, 5, 300)
    pack = next((p for p in config()["packs"] if p["id"] == body.pack), None)
    if not pack:
        raise HTTPException(422, "未知案卷包")
    price = os.getenv("STRIPE_PRICE_"+body.pack.upper(), "")
    if config()["payment_mode"] != "test" or not price.startswith("price_"):
        raise HTTPException(503, "购买尚未开放")
    origin = os.getenv("CASTLE_PUBLIC_URL", "http://localhost:5173").rstrip("/")
    order_id = uuid4().hex
    with commerce.transaction() as db:
        db.execute("INSERT INTO orders(id,account_id,pack,credits,price_id,live) VALUES (?,?,?,?,?,0)", (order_id, account_id, body.pack, pack["credits"], price))
    session = await asyncio.to_thread(stripe_post, {
        "mode": "payment", "line_items[0][price]": price, "line_items[0][quantity]": 1,
        "client_reference_id": order_id, "metadata[castle_order]": order_id,
        "success_url": origin+"/?checkout=success", "cancel_url": origin+"/?checkout=cancelled",
    }, order_id)
    if session.get("livemode") or not str(session.get("url", "")).startswith("https://checkout.stripe.com/"):
        raise HTTPException(502, "收银台模式不匹配")
    with commerce.transaction() as db:
        db.execute("UPDATE orders SET session_id=? WHERE id=?", (session["id"], order_id))
    return {"url": session["url"], "test_only": True}


def verify_event(raw: bytes, signature: str, secret: str):
    try:
        parts = [item.split("=", 1) for item in signature.split(",")]
        stamp = next(v for k, v in parts if k == "t")
        signatures = [v for k, v in parts if k == "v1"]
        expected = hmac.new(secret.encode(), stamp.encode()+b"."+raw, hashlib.sha256).hexdigest()
        if abs(time.time()-int(stamp)) > 300 or not any(hmac.compare_digest(expected, item) for item in signatures):
            raise ValueError()
        return json.loads(raw)
    except (ValueError, StopIteration, TypeError):
        raise HTTPException(400, "无效的支付事件签名")


def fulfill_event(commerce, event):
    if event.get("livemode") is not False:
        raise HTTPException(400, "真实收款未启用")
    if event.get("type") not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return
    session = event["data"]["object"]
    if session.get("payment_status") != "paid" or session.get("mode") != "payment":
        return
    with commerce.transaction() as db:
        if db.execute("SELECT 1 FROM payment_events WHERE id=?", (event["id"],)).fetchone():
            return
        order = db.execute("SELECT * FROM orders WHERE id=?", (session.get("metadata", {}).get("castle_order", ""),)).fetchone()
        if not order or order["session_id"] != session.get("id") or order["live"] or session.get("livemode") is not False:
            raise HTTPException(409, "订单尚未匹配，请重试回调")
        if not order["fulfilled"]:
            db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", ("order-"+order["id"], order["account_id"], "sandbox", order["credits"], "测试付款（不可调用真实 AI）", time.time()))
            db.execute("UPDATE orders SET fulfilled=1 WHERE id=?", (order["id"],))
        db.execute("INSERT INTO payment_events VALUES (?,?)", (event["id"], time.time()))


@router.post("/billing/webhook")
async def webhook(request: Request, stripe_signature: Annotated[str, Header()] = ""):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret or config()["payment_mode"] != "test":
        raise HTTPException(503, "支付回调尚未启用")
    raw = await request.body()
    if len(raw) > 100_000:
        raise HTTPException(413, "事件过大")
    event = verify_event(raw, stripe_signature, secret)
    fulfill_event(Commerce(), event)
    return {"received": True}
