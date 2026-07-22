from datetime import date, time
from typing import Literal
from pydantic import BaseModel, Field


class BirthProfile(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    birth_date: date
    birth_time: time | None = None
    birthplace_text: str = Field(min_length=2, max_length=160)
    timezone_name: str = "Asia/Shanghai"
    time_precision: Literal["exact", "approximate", "unknown"] = "exact"
    gender_marker: str | None = None


class ReportRequest(BaseModel):
    profile: BirthProfile
    systems: list[str] = ["western", "jyotish", "bazi", "human_design"]


class Fact(BaseModel):
    id: str
    label: str
    value: str
    time_sensitive: bool = False


class Chamber(BaseModel):
    system_id: str
    display_name: str
    source_type: Literal["api", "demo"]
    provider: str
    facts: list[Fact]
    warning: str | None = None


class Claim(BaseModel):
    id: str
    system_id: str
    statement: str
    themes: list[str]
    evidence_ids: list[str]
    confidence: float
    specificity: float
    barnum_risk: float


class ReportResponse(BaseModel):
    case_id: str
    mode: Literal["live", "demo"]
    time_sensitivity: Literal["high", "moderate", "low"]
    chambers: list[Chamber]
    claims: list[Claim]
    consensus: list[dict]
    conflicts: list[dict]
    questions: list[dict]
    audit: dict
