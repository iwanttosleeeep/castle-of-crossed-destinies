import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .deepseek import extract_facts_only
from .export import export_case_markdown
from .files import extract_bytes, read_upload
from .guided_debate import run_guided_debate
from .guided_reports import run_guided_chamber, run_guided_tribunal
from .providers import SYSTEMS
from .schemas import CaseCreateRequest, DebateRequest, Fact, FactConfirmation
from .store import CaseStore
from .structured import extract_structured_facts


store: CaseStore | None = None
case_write_lock = asyncio.Lock()
ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store
    store = CaseStore()
    yield


app = FastAPI(title="The Castle of Crossed Destinies", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "confirmed facts + lightweight persona skills", "chambers": list(SYSTEMS)}


@app.post("/cases")
async def create_case(request: CaseCreateRequest):
    selected = validate_systems(request.systems)
    payload, token = get_store().create(selected)
    return public_case(payload) | {"resume_token": token}


@app.get("/cases/{case_id}")
async def restore_case(
    case_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
):
    return public_case(authorize(case_id, case_token))


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
):
    payload = authorize(case_id, case_token)
    validate_model(deepseek_model)
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
            extracted_facts, excluded_commentary, extraction_warning = await extract_facts_only(
                system_id,
                source_text,
                filename,
                deepseek_key,
                deepseek_model,
            )
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
        payload["extractions"][system_id] = extraction
        payload["confirmed_facts"].pop(system_id, None)
        payload["reports"] = {}
        payload["tribunal"] = None
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
        if system_id not in payload["systems"]:
            raise HTTPException(422, "该 chamber 不属于此案件")
        payload["confirmed_facts"][system_id] = [fact.model_dump(mode="json") for fact in normalized]
        if system_id in payload["extractions"]:
            payload["extractions"][system_id]["confirmed"] = True
            payload["extractions"][system_id]["facts"] = payload["confirmed_facts"][system_id]
        payload["reports"] = {}
        payload["tribunal"] = None
        payload["status"] = "facts_confirmed" if all(system in payload["confirmed_facts"] for system in payload["systems"]) else "awaiting_confirmation"
        get_store().save(payload)
    return {"system_id": system_id, "facts": payload["confirmed_facts"][system_id], "status": payload["status"]}


@app.post("/cases/{case_id}/reports")
async def create_reports(
    case_id: str,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
):
    payload = authorize(case_id, case_token)
    validate_model(deepseek_model)
    missing = [system for system in payload["systems"] if system not in payload["confirmed_facts"]]
    if missing:
        raise HTTPException(409, f"请先确认这些 chamber 的事实：{', '.join(missing)}")
    facts_by_system = {
        system: [Fact.model_validate(item) for item in payload["confirmed_facts"][system]]
        for system in payload["systems"]
    }
    facts_snapshot = payload["confirmed_facts"]
    results = await asyncio.gather(
        *(
            run_guided_chamber(
                system, SYSTEMS[system], facts_by_system[system], deepseek_key, deepseek_model
            )
            for system in payload["systems"]
        )
    )
    reports = {}
    report_texts = {}
    warnings = []
    for system, (report_text, warning) in zip(payload["systems"], results):
        if report_text:
            report_texts[system] = report_text
        if warning:
            warnings.append(f"{SYSTEMS[system]}: {warning}")
        reports[system] = {
            "system_id": system,
            "display_name": SYSTEMS[system],
            "text": report_text,
            "warning": warning,
        }
    tribunal_text, tribunal_warning = await run_guided_tribunal(
        report_texts, deepseek_key, deepseek_model
    )
    tribunal = {
        "summary": tribunal_text,
        "disclaimer": "这是跨体系叙事比较，不代表科学准确或事实证明。",
    }
    if tribunal_warning:
        warnings.append(tribunal_warning)
    async with case_write_lock:
        payload = authorize(case_id, case_token)
        if payload["confirmed_facts"] != facts_snapshot:
            raise HTTPException(409, "事实在报告生成期间发生了变化，请重新生成")
        payload["reports"] = reports
        payload["tribunal"] = tribunal
        payload["status"] = "reports_ready"
        payload["report_warnings"] = warnings
        get_store().save(payload)
    return public_case(payload)


@app.post("/cases/{case_id}/debates")
async def create_debate(
    case_id: str,
    request: DebateRequest,
    case_token: Annotated[str | None, Header(alias="X-Case-Token")] = None,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
):
    payload = authorize(case_id, case_token)
    validate_model(deepseek_model)
    if not payload.get("reports"):
        raise HTTPException(409, "请先生成七份 general reports")
    facts_by_system = {
        system: [Fact.model_validate(item) for item in items]
        for system, items in payload["confirmed_facts"].items()
    }
    hearing, warning = await run_guided_debate(
        request.question, facts_by_system, deepseek_key, deepseek_model
    )
    if warning or not hearing:
        raise HTTPException(502, warning or "质询未完成")
    async with case_write_lock:
        payload = authorize(case_id, case_token)
        hearing["id"] = f"hearing-{len(payload['debates']) + 1}"
        payload["debates"].append(hearing)
        payload["status"] = "hearing_complete"
        get_store().save(payload)
    return hearing


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
    return {key: value for key, value in payload.items() if key != "resume_token"}


def get_store() -> CaseStore:
    global store
    if store is None:
        store = CaseStore()
    return store
