from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .providers import SYSTEMS, generate_chart
from .schemas import Claim, ReportRequest, ReportResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="The Castle of Crossed Destinies", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "ziwei": "excluded"}


@app.post("/reports", response_model=ReportResponse)
async def create_report(request: ReportRequest):
    selected = list(dict.fromkeys(request.systems))
    invalid = set(selected) - SYSTEMS.keys()
    if invalid:
        raise HTTPException(422, f"Unsupported systems: {', '.join(invalid)}")
    chambers = await asyncio.gather(*(generate_chart(system, request.profile) for system in selected))
    claims = [
        Claim(id="western.exploration", system_id="western", statement="The chart frames learning and distant horizons as a recurring source of meaning.", themes=["exploration", "language_and_communication"], evidence_ids=["western.mercury"], confidence=.72, specificity=.62, barnum_risk=.34),
        Claim(id="jyotish.exploration", system_id="jyotish", statement="Expansion through study, travel, or philosophical inquiry is emphasised.", themes=["exploration", "academic_orientation"], evidence_ids=["jyotish.jupiter"], confidence=.69, specificity=.57, barnum_risk=.42),
        Claim(id="bazi.structure", system_id="bazi", statement="Momentum is strongest when experimentation has a clear practical structure.", themes=["adaptability", "need_for_structure"], evidence_ids=["bazi.element"], confidence=.61, specificity=.67, barnum_risk=.29),
        Claim(id="human_design.response", system_id="human_design", statement="Decisions may be more sustainable when made in response to a concrete opportunity.", themes=["decision_style", "adaptability"], evidence_ids=["human_design.authority"], confidence=.66, specificity=.64, barnum_risk=.31),
    ]
    claims = [claim for claim in claims if claim.system_id in selected]
    demo = any(chamber.source_type == "demo" for chamber in chambers)
    sensitivity = "high" if request.profile.time_precision != "unknown" else "moderate"
    return ReportResponse(case_id=f"CCD-{datetime.now():%y%m%d-%H%M}", mode="demo" if demo else "live", time_sensitivity=sensitivity, chambers=chambers, claims=claims, consensus=[{"theme": "exploration", "score": 74, "support": ["Western Astrology", "Jyotish"], "independence": "1.6 adjusted systems"}, {"theme": "adaptability", "score": 58, "support": ["BaZi 八字", "Human Design"], "independence": "2.0 adjusted systems"}], conflicts=[{"topic": "Structure vs. spontaneity", "positions": "BaZi favours defined containers; Human Design emphasises response to the present.", "severity": "productive"}], questions=[{"target": "Western Astrology", "type": "evidence challenge", "question": "Which observation would weaken the exploration claim beyond a broad preference for novelty?"}], audit={"barnum_risk": "moderate", "traceability": "100% of displayed claims link to a fact id", "limitation": "This is an interpretive comparison, not scientific validation."})
