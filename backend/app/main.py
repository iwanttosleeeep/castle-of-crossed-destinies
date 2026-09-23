import asyncio
import os
import fcntl
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, UploadFile, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .deepseek import extract_facts_only
from .export import export_case_markdown
from .files import extract_bytes, read_upload
from .providers import SYSTEMS
from .schemas import CaseCreateRequest, DebateRequest, ReportRequest, Fact, FactConfirmation
from .store import CaseStore
from .structured import extract_structured_facts
from .calculation import BirthRequest, calculate_case, search_locations
from .commerce import Commerce, config
from .jobs import ACTIVE, Jobs, shutdown
from .metering import Payer, payer_context
from .accounts_api import router as account_router


store: CaseStore | None = None
case_write_lock = asyncio.Lock()
ALLOWED_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store
    store = CaseStore()
    # Durable tasks currently use one process; fail closed rather than interrupt another worker.
    with open(str(store.path)+".worker.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Castle requires one API worker for this database")
        Commerce(store.path).recover()
        Jobs(Commerce(store.path)).recover()
        try:
            yield
        finally:
            await shutdown()


app = FastAPI(title="The Castle of Crossed Destinies", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(account_router)


@app.middleware("http")
async def request_limits(request: Request, call_next):
    from fastapi.responses import JSONResponse
    if request.method in {"POST", "PUT", "DELETE"} or request.url.path == "/locations":
        # X-Forwarded-For is deliberately not trusted here; configure trusted proxies in Uvicorn.
        host = request.client.host if request.client else "unknown"
        try:
            Commerce().rate("request:"+host, 100)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    if request.url.path.startswith(("/account", "/cases", "/billing")):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "confirmed facts + lightweight persona skills", "chambers": list(SYSTEMS)}


@app.post("/cases")
async def create_case(request: CaseCreateRequest):
    selected = validate_systems(request.systems)
    payload, token = get_store().create(selected)
    return public_case(payload) | {"resume_token": token}


@app.get("/locations")
async def locations(q: str = Query(min_length=2, max_length=80)):
    return {"locations": await asyncio.to_thread(search_locations, q), "attribution": "GeoNames · CC BY 4.0"}


@app.post("/cases/calculate")
async def create_calculated_case(request: BirthRequest):
    extractions, metadata = await calculate_case(request)
    payload, token = get_store().create(request.systems)
    payload.update(extractions=extractions, calculation=metadata, status="awaiting_confirmation")
    get_store().save(payload)
    return public_case(payload) | {"resume_token": token}


@app.get("/cases/{case_id}")
async def restore_case(
    case_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
):
    return public_case(authorize(case_id, case_token))


@app.delete("/cases/{case_id}")
async def delete_case(case_id: str, case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None):
    authorize(case_id, case_token)
    commerce = Commerce(get_store().path)
    Jobs(commerce)
    with commerce.transaction() as db:
        if db.execute("SELECT 1 FROM jobs WHERE case_id=? AND state IN ('queued','running','stopping')", (case_id,)).fetchone():
            raise HTTPException(409, "请等待当前任务结束后删除案卷")
        db.execute("UPDATE calls SET result=NULL WHERE job_id IN (SELECT id FROM jobs WHERE case_id=?)", (case_id,))
        db.execute("DELETE FROM jobs WHERE case_id=?", (case_id,))
        db.execute("DELETE FROM cases WHERE id=?", (case_id,))
    return {"deleted": True}


@app.get("/cases/{case_id}/export.md")
async def export_case(
    case_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
):
    markdown = export_case_markdown(authorize(case_id, case_token))
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.md"'},
    )


@app.post("/cases/{case_id}/sources/{system_id}")
async def upload_source(
    case_id: str,
    system_id: str,
    file: Annotated[UploadFile, File()],
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
    payment_mode: Annotated[str, Header(alias="X-Payment-Mode")] = "byok",
    authorization: Annotated[str | None, Header()] = None,
):
    payload = authorize(case_id, case_token)
    validate_model(deepseek_model)
    ensure_idle(payload)
    if system_id not in payload["systems"]:
        raise HTTPException(422, "该 chamber 不属于此案件")
    filename = file.filename or "uploaded report"
    data, suffix, _ = await read_upload(file)
    facts: list[Fact] = []
    commentary: list[str] = []
    warnings: list[str] = []
    source_text = ""
    extraction_engine = "manual_required"
    try:
        source_text, file_warnings = await extract_bytes(data, suffix)
        warnings.extend(file_warnings)
    except HTTPException as exc:
        warnings.append(str(exc.detail))
    if len(source_text) >= 12:
        structured_facts = extract_structured_facts(system_id, source_text)
        if structured_facts:
            facts = structured_facts
            extraction_engine = "structured_text"
            warnings.append("已按结构化 TXT/JSON 原样解析；未使用 AI 猜测盘面字段，请仍在确认页核对。")
        else:
            if payment_mode == "trial":
                raise HTTPException(409, "免费体验用于两间密室解读，请先使用自动排盘或结构化 TXT")
            payer, key, model = resolve_payer(payment_mode, authorization, deepseek_key, deepseek_model)
            marker = payer_context.set(payer)
            try:
                extracted_facts, excluded_commentary, extraction_warning = await extract_facts_only(
                    system_id, source_text, filename, key, model,
                )
            finally:
                payer_context.reset(marker)
            if extracted_facts:
                facts = extracted_facts
                commentary = excluded_commentary
                extraction_engine = "deepseek_text"
            if extraction_warning:
                warnings.append(extraction_warning)
    else:
        warnings.append("本地读取没有取得足够文字；请改用 TXT/文本 PDF，或在确认页手动补充事实。")
    extraction = {
        "system_id": system_id,
        "display_name": SYSTEMS[system_id],
        "filename": filename,
        "extracted_characters": len(source_text),
        "source_bytes": len(data),
        "extraction_engine": extraction_engine,
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "source_commentary": commentary,
        "warnings": warnings,
        "confirmed": False,
    }
    async with case_write_lock:
        payload = authorize(case_id, case_token)
        ensure_idle(payload)
        payload["extractions"][system_id] = extraction
        payload["confirmed_facts"].pop(system_id, None)
        payload["reports"] = {}
        payload["tribunal"] = None
        invalidate_facts(payload)
        payload["status"] = "awaiting_confirmation"
        get_store().save(payload)
    return extraction


@app.put("/cases/{case_id}/facts/{system_id}")
async def confirm_facts(
    case_id: str,
    system_id: str,
    request: FactConfirmation,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
):
    normalized: list[Fact] = []
    seen = set()
    for index, fact in enumerate(request.facts, start=1):
        fact_id = fact.id if fact.id.startswith(f"{system_id}.") else f"{system_id}.confirmed-{index}"
        if fact_id in seen:
            fact_id = f"{system_id}.confirmed-{index}"
        seen.add(fact_id)
        normalized.append(fact.model_copy(update={"id": fact_id}))
    async with case_write_lock:
        payload = authorize(case_id, case_token)
        ensure_idle(payload)
        if system_id not in payload["systems"]:
            raise HTTPException(422, "该 chamber 不属于此案件")
        items = [fact.model_dump(mode="json") for fact in normalized]
        if items != payload["confirmed_facts"].get(system_id):
            invalidate_facts(payload)
            payload["reports"] = {}
            payload["tribunal"] = None
        payload["confirmed_facts"][system_id] = items
        if system_id in payload["extractions"]:
            payload["extractions"][system_id]["confirmed"] = True
            payload["extractions"][system_id]["facts"] = payload["confirmed_facts"][system_id]
        payload["status"] = "facts_confirmed" if all(system in payload["confirmed_facts"] for system in payload["systems"]) else "awaiting_confirmation"
        get_store().save(payload)
    return {"system_id": system_id, "facts": payload["confirmed_facts"][system_id], "status": payload["status"]}


@app.post("/cases/{case_id}/reports", status_code=202)
async def create_reports(
    case_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
    request: ReportRequest = ReportRequest(),
    payment_mode: Annotated[str, Header(alias="X-Payment-Mode")] = "byok",
    authorization: Annotated[str | None, Header()] = None,
):
    payload = authorize(case_id, case_token)
    selected = selected_systems(payload, request.systems)
    if payment_mode == "trial" and len(selected) != 2:
        raise HTTPException(422, "免费体验请选择两间密室")
    payer, key, model = resolve_payer(payment_mode, authorization, deepseek_key, deepseek_model)
    runner = Jobs(payer.commerce)
    job, launch = runner.create(payload, "reports", selected, model, payer)
    if launch:
        runner.launch(job, payload, key, payer)
    return Jobs.public(job)


@app.post("/cases/{case_id}/debates", status_code=202)
async def create_debate(
    case_id: str,
    request: DebateRequest,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
    payment_mode: Annotated[str, Header(alias="X-Payment-Mode")] = "byok",
    authorization: Annotated[str | None, Header()] = None,
):
    payload = authorize(case_id, case_token)
    if not payload.get("reports"):
        raise HTTPException(409, "请先生成至少一份独立报告")
    if payment_mode == "trial":
        raise HTTPException(402, "免费体验包含两间密室与 Tribunal；追问请选择案卷额度或自带 Key")
    selected = selected_systems(payload, request.systems if request.systems is not None else list(payload["reports"])[:3])
    payer, key, model = resolve_payer(payment_mode, authorization, deepseek_key, deepseek_model)
    runner = Jobs(payer.commerce)
    job, launch = runner.create(payload, "debate", selected, model, payer, request.question)
    if launch:
        runner.launch(job, payload, key, payer)
    return Jobs.public(job)


@app.post("/cases/{case_id}/jobs/{job_id}/stop", status_code=202)
async def stop_job(case_id: str, job_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None):
    authorize(case_id, case_token)
    runner = Jobs(Commerce(get_store().path))
    if runner.get(job_id)["case_id"] != case_id:
        raise HTTPException(404, "任务不存在")
    # Possession of the case token permits stopping without resending a paid key.
    return Jobs.public(runner.request_stop(job_id))


@app.post("/cases/{case_id}/jobs/{job_id}/retry", status_code=202)
async def retry_job(case_id: str, job_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    payment_mode: Annotated[str, Header(alias="X-Payment-Mode")] = "byok",
    authorization: Annotated[str | None, Header()] = None):
    payload = authorize(case_id, case_token)
    runner = Jobs(Commerce(get_store().path))
    old = runner.get(job_id)
    if old["case_id"] != case_id:
        raise HTTPException(404, "任务不存在")
    payer, key, _ = resolve_payer(payment_mode, authorization, deepseek_key, old["model"])
    job, launch = runner.resume(job_id, payer)
    if launch:
        runner.launch(job, payload, key, payer)
    return Jobs.public(job)


def selected_systems(payload, requested):
    selected = validate_systems(requested if requested is not None else payload["systems"])
    if any(s not in payload["systems"] or not payload["confirmed_facts"].get(s) for s in selected):
        raise HTTPException(409, "请先确认所选密室的事实")
    return selected


def resolve_payer(mode, authorization, key, model):
    commerce = Commerce(get_store().path)
    model = model or "deepseek-flash"
    validate_model(model)
    if mode == "byok":
        if not key or not key.strip():
            raise HTTPException(401, "请填写自己的 DeepSeek Key，或选择 Castle 额度")
        # Account is deliberately optional and not used for BYOK billing.
        return Payer(commerce), key.strip(), model
    if mode not in {"paid", "trial"}:
        raise HTTPException(422, "无效的付费方式")
    account_id = commerce.authenticate(authorization)
    available = config()["trial_available" if mode == "trial" else "hosted_available"]
    if not available:
        raise HTTPException(402, "Castle AI 额度暂未开放，可以使用自己的 Key")
    return Payer(commerce, mode, account_id), os.environ["DEEPSEEK_API_KEY"], "deepseek-flash"


def ensure_idle(payload):
    if any(j["state"] in ACTIVE for j in Jobs(Commerce(get_store().path)).for_case(payload["case_id"])):
        raise HTTPException(409, "任务进行中，请完成后再修改事实")


def invalidate_facts(payload):
    payload["facts_revision"] = payload.get("facts_revision", 0) + 1
    if payload.get("debates"):
        payload.setdefault("archived_debates", []).extend(payload["debates"])
        payload["debates"] = []


def validate_systems(systems: list[str]) -> list[str]:
    selected = list(dict.fromkeys(systems))
    invalid = set(selected) - SYSTEMS.keys()
    if invalid:
        raise HTTPException(422, f"Unsupported systems: {', '.join(sorted(invalid))}")
    if not selected:
        raise HTTPException(422, "请至少选择一个体系")
    return selected


def validate_model(model: str | None) -> None:
    if model and model not in ALLOWED_MODELS:
        raise HTTPException(422, "Unsupported DeepSeek model")


def authorize(case_id: str, token: str | None) -> dict:
    payload = get_store().get(case_id, token or "")
    if not payload:
        raise HTTPException(404, "案件不存在或恢复令牌不正确")
    return payload


def public_case(payload: dict) -> dict:
    result = {key: value for key, value in payload.items() if key != "resume_token"}
    result["jobs"] = Jobs(Commerce(get_store().path)).for_case(payload["case_id"])
    return result


def get_store() -> CaseStore:
    global store
    if store is None:
        store = CaseStore()
    return store
