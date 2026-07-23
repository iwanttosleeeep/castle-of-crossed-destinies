import asyncio
from typing import Annotated
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .deepseek import run_chamber_skill
from .providers import SYSTEMS, generate_chamber, parse_facts
from .schemas import Claim, ReportRequest, ReportResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="The Castle of Crossed Destinies", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "local skills", "chambers": list(SYSTEMS)}


@app.post("/reports", response_model=ReportResponse)
async def create_report(
    request: ReportRequest,
    deepseek_key: Annotated[str | None, Header(alias="X-DeepSeek-Key")] = None,
    deepseek_model: Annotated[str | None, Header(alias="X-DeepSeek-Model")] = None,
):
    selected = list(dict.fromkeys(request.systems))
    invalid = set(selected) - SYSTEMS.keys()
    if invalid:
        raise HTTPException(422, f"Unsupported systems: {', '.join(invalid)}")
    allowed_models = {"deepseek-v4-flash", "deepseek-v4-pro"}
    if deepseek_model and deepseek_model not in allowed_models:
        raise HTTPException(422, "Unsupported DeepSeek model")
    supplied = parse_facts(request.facts_text)
    chambers = [generate_chamber(system, request.profile, supplied[system]) for system in selected]
    verified = {chamber.system_id for chamber in chambers if chamber.source_type == "user_dossier"}
    results = await asyncio.gather(
        *(
            run_chamber_skill(system, supplied[system], deepseek_key, deepseek_model)
            for system in selected
            if system in verified
        )
    )
    claims = [claim for chamber_claims, _ in results for claim in chamber_claims]
    run_warnings = [warning for _, warning in results if warning]
    sensitivity = "high" if request.profile.time_precision != "unknown" else "moderate"
    status = "DeepSeek 已运行" if claims else (run_warnings[0] if run_warnings else "请先提供至少一个 chamber 的事实档案。")
    return ReportResponse(case_id=f"CCD-{datetime.now():%y%m%d-%H%M}", mode="skills_ready", time_sensitivity=sensitivity, chambers=chambers, claims=claims, consensus=[{"theme": "awaiting tribunal", "score": 0, "support": ["Skill claims will be clustered after review"], "independence": "not yet assessed"}], conflicts=[{"topic": "No admissible conflict yet", "positions": "The Skills only receive their own chamber facts. Cross-examination starts after evidence-linked claims exist.", "severity": "pending"}], questions=[{"target": "All chambers", "type": "admissibility check", "question": "Which supplied fact supports this claim, and what would count against it?"}], audit={"barnum_risk": "not assessed", "traceability": "Only user-supplied facts are sent to the relevant chamber skill. " + status, "limitation": "Skills are interpretive tools, not evidence of prediction or scientific validity."})
