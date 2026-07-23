import json
import os
import asyncio
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .schemas import Claim, Fact


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://api.deepseek.com/chat/completions"
THEMES = {
    "identity_orientation",
    "decision_style",
    "thinking_communication",
    "relationships_boundaries",
    "work_creation",
    "resources_stewardship",
    "stress_adaptation",
    "change_timing",
    "meaning_imagination",
}
RULE_PATTERN = re.compile(r"\b(?:BAZI|ZIWEI|WEST|JYOTISH|NUM|HD|DREAM)-[A-Z0-9-]+\b")


def skill_instructions(system_id: str) -> str:
    skills_root = ROOT / "skills"
    chamber_root = skills_root / f"{system_id.replace('_', '-')}-chamber"
    paths = [
        skills_root / "_shared" / "grounding.md",
        skills_root / "_shared" / "theme-taxonomy.md",
        chamber_root / "SKILL.md",
        chamber_root / "references" / "knowledge.md",
    ]
    return "\n\n".join(path.read_text(encoding="utf-8") for path in paths)


def persona_instructions(system_id: str) -> str:
    path = ROOT / "skills" / f"{system_id.replace('_', '-')}-chamber" / "references" / "persona.md"
    return path.read_text(encoding="utf-8")


async def run_chamber_skill(system_id: str, facts: list[Fact]) -> tuple[list[Claim], str | None]:
    """Build neutral claims, then style them in an isolated persona pass."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return [], "DeepSeek 尚未配置；已保存事实档案，但没有生成解释性证词。"
    allowed_ids = {fact.id for fact in facts}
    instructions = skill_instructions(system_id)
    allowed_rule_ids = set(RULE_PATTERN.findall(instructions))
    system = f"""{instructions}

Return JSON only, using exactly this shape:
{{"claims":[{{"neutral_statement":"plain evidence-bound interpretation","themes":["one_to_three_controlled_themes"],"evidence_ids":["fact.id"],"rule_ids":["PERMITTED-RULE-ID"],"caveat":"material limitation","counter_reading":"factor that could weaken this reading","confidence":0.0,"specificity":0.0,"barnum_risk":0.0}}]}}
Use only fact ids in the dossier and rule ids printed in the instructions. Produce at most five claims.
Return no claims if evidence is insufficient. Do not use a persona or decorative voice in this pass.
Do not reveal chain-of-thought."""
    dossier = [{"id": fact.id, "label": fact.label, "value": fact.value, "time_sensitive": fact.time_sensitive} for fact in facts]
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": f"JSON dossier for {system_id}:\n{json.dumps(dossier, ensure_ascii=False)}"}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 2200,
        "stream": False,
    }
    try:
        body = await call_json(payload, api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [], f"DeepSeek chamber 未完成：{type(exc).__name__}。"
    claims: list[Claim] = []
    for index, item in enumerate(body.get("claims", [])[:5], start=1):
        evidence_ids = [fact_id for fact_id in item.get("evidence_ids", []) if fact_id in allowed_ids]
        rule_ids = [rule_id for rule_id in item.get("rule_ids", []) if rule_id in allowed_rule_ids]
        neutral = item.get("neutral_statement")
        themes = [str(theme) for theme in item.get("themes", []) if theme in THEMES][:3]
        if not evidence_ids or not rule_ids or not isinstance(neutral, str) or not neutral.strip():
            continue
        neutral = neutral.strip()
        claims.append(
            Claim(
                id=f"{system_id}.deepseek-{index}",
                system_id=system_id,
                neutral_statement=neutral,
                statement=neutral,
                themes=themes,
                evidence_ids=evidence_ids,
                rule_ids=rule_ids,
                caveat=bounded_text(item.get("caveat")),
                counter_reading=bounded_text(item.get("counter_reading")),
                confidence=clamp(item.get("confidence")),
                specificity=clamp(item.get("specificity")),
                barnum_risk=clamp(item.get("barnum_risk")),
            )
        )
    if claims:
        claims = await style_claims(system_id, claims, api_key)
    return claims, None


async def style_claims(system_id: str, claims: list[Claim], api_key: str) -> list[Claim]:
    """Apply voice without giving the style pass access to chart facts or other chambers."""
    system = f"""{persona_instructions(system_id)}

You are a voice framer, not an interpreter. Keep each neutral_statement as an exact,
unchanged, continuous substring. You may add one short in-character lead-in around it.
Do not paraphrase, add, remove, intensify, weaken, explain, or infer factual content.
Keep uncertainty and conditional language. Return JSON only:
{{"statements":[{{"index":0,"statement":"short lead-in + exact neutral_statement"}}]}}
If safe framing is not possible, repeat the neutral statement exactly."""
    neutral_claims = [
        {"index": index, "neutral_statement": claim.neutral_statement}
        for index, claim in enumerate(claims)
    ]
    payload = {
        "model": os.getenv("DEEPSEEK_STYLE_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(neutral_claims, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 1200,
        "stream": False,
    }
    try:
        body = await call_json(payload, api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return claims
    styled = {}
    for item in body.get("statements", []):
        index = item.get("index")
        statement = item.get("statement")
        if isinstance(index, int) and isinstance(statement, str):
            styled[index] = statement.strip()
    for index, claim in enumerate(claims):
        candidate = styled.get(index, "")
        if (
            candidate
            and claim.neutral_statement in candidate
            and len(candidate) <= len(claim.neutral_statement) + 120
        ):
            claim.statement = candidate
    return claims


async def call_json(payload: dict, api_key: str) -> dict:
    """Retry once because JSON mode can occasionally return empty content."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = await asyncio.to_thread(post_json, payload, api_key)
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise json.JSONDecodeError("empty JSON content", "", 0)
            return json.loads(content)
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def bounded_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "No additional limitation supplied."
    return value.strip()[:500]


def clamp(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def post_json(payload: dict, api_key: str) -> dict:
    request = Request(BASE_URL, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))
