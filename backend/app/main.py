from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
async def create_report(request: ReportRequest):
    selected = list(dict.fromkeys(request.systems))
    invalid = set(selected) - SYSTEMS.keys()
    if invalid:
        raise HTTPException(422, f"Unsupported systems: {', '.join(invalid)}")
    supplied = parse_facts(request.facts_text)
    chambers = [generate_chamber(system, request.profile, supplied[system]) for system in selected]
    claims = [
        Claim(id="bazi.structure", system_id="bazi", statement="A BaZi skill may assess the balance between adaptability and structure from the supplied pillars.", themes=["adaptability", "need_for_structure"], evidence_ids=["bazi.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="ziwei.identity", system_id="ziwei", statement="A Zi Wei skill may interpret palace and transformation relationships from the supplied chart record.", themes=["identity", "career_orientation"], evidence_ids=["ziwei.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="western.exploration", system_id="western", statement="A Western skill may assess exploration themes from supplied planets, houses, and aspects.", themes=["exploration", "language_and_communication"], evidence_ids=["western.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="jyotish.dharma", system_id="jyotish", statement="A Jyotish skill may assess study and purpose themes from supplied Lagna, houses, and dasha context.", themes=["exploration", "academic_orientation"], evidence_ids=["jyotish.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="numerology.pattern", system_id="numerology", statement="A numerology skill may interpret only the explicitly supplied numbers and tradition.", themes=["identity", "decision_style"], evidence_ids=["numerology.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="human_design.authority", system_id="human_design", statement="A Human Design skill may interpret decision process only from a verified bodygraph record.", themes=["decision_style", "need_for_freedom"], evidence_ids=["human_design.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
        Claim(id="dreamspell.cycle", system_id="dreamspell", statement="A Dreamspell skill may interpret the supplied Kin and wavespell as a modern symbolic system.", themes=["creativity", "life_transformation"], evidence_ids=["dreamspell.dossier"], confidence=.0, specificity=.0, barnum_risk=.0),
    ]
    verified = {chamber.system_id for chamber in chambers if chamber.source_type == "user_dossier"}
    claims = [claim for claim in claims if claim.system_id in selected and claim.system_id in verified]
    sensitivity = "high" if request.profile.time_precision != "unknown" else "moderate"
    return ReportResponse(case_id=f"CCD-{datetime.now():%y%m%d-%H%M}", mode="skills_ready", time_sensitivity=sensitivity, chambers=chambers, claims=claims, consensus=[{"theme": "awaiting testimony", "score": 0, "support": ["No skill testimony has been run"], "independence": "not yet assessed"}], conflicts=[{"topic": "No admissible conflict yet", "positions": "Supply verified chart facts, then run the chamber skills to create evidence-linked claims.", "severity": "pending"}], questions=[{"target": "All chambers", "type": "admissibility check", "question": "Which supplied fact supports this claim, and what would count against it?"}], audit={"barnum_risk": "not assessed", "traceability": "Only user-supplied facts are admitted; no API or hidden calculation is used.", "limitation": "Skills are interpretive tools, not evidence of prediction or scientific validity."})
