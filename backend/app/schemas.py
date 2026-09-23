from pydantic import BaseModel, Field


class CaseCreateRequest(BaseModel):
    systems: list[str] = [
        "bazi",
        "ziwei",
        "western",
        "jyotish",
        "numerology",
        "human_design",
        "dreamspell",
    ]


class Fact(BaseModel):
    id: str = Field(max_length=180)
    label: str = Field(max_length=240)
    value: str = Field(max_length=2500)
    time_sensitive: bool = False
    source_span: str | None = None
    extraction_confidence: float | None = None


class FactConfirmation(BaseModel):
    facts: list[Fact] = Field(min_length=1, max_length=120)


class DebateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    systems: list[str] | None = None


class ReportRequest(BaseModel):
    systems: list[str] | None = None
