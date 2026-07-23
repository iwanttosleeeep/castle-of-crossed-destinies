import json
import os
import asyncio
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .schemas import Claim, Fact


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://api.deepseek.com/chat/completions"


def skill_instructions(system_id: str) -> str:
    path = ROOT / "skills" / f"{system_id.replace('_', '-')}-chamber" / "SKILL.md"
    return path.read_text(encoding="utf-8")


async def run_chamber_skill(system_id: str, facts: list[Fact]) -> tuple[list[Claim], str | None]:
    """Run one bounded chamber prompt. The model receives no other chamber's facts."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return [], "DeepSeek 尚未配置；已保存事实档案，但没有生成解释性证词。"
    allowed_ids = {fact.id for fact in facts}
    system = f"""{skill_instructions(system_id)}

Return JSON only, using exactly this shape:
{{"claims":[{{"statement":"string","themes":["one_to_three_controlled_themes"],"evidence_ids":["fact.id"],"confidence":0.0,"specificity":0.0,"barnum_risk":0.0}}]}}
Use only fact ids in the dossier. Return no claims if evidence is insufficient. Do not reveal chain-of-thought."""
    dossier = [{"id": fact.id, "label": fact.label, "value": fact.value, "time_sensitive": fact.time_sensitive} for fact in facts]
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": f"JSON dossier for {system_id}:\n{json.dumps(dossier, ensure_ascii=False)}"}],
        "response_format": {"type": "json_object"},
        "temperature": 0.35,
        "max_tokens": 1000,
        "stream": False,
    }
    try:
        body = await asyncio.to_thread(post_json, payload, api_key)
        content = body["choices"][0]["message"]["content"]
        body = json.loads(content)
    except (HTTPError, URLError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [], f"DeepSeek chamber 未完成：{type(exc).__name__}。"
    claims: list[Claim] = []
    for index, item in enumerate(body.get("claims", [])[:3], start=1):
        evidence_ids = [fact_id for fact_id in item.get("evidence_ids", []) if fact_id in allowed_ids]
        if not evidence_ids or not isinstance(item.get("statement"), str):
            continue
        claims.append(Claim(id=f"{system_id}.deepseek-{index}", system_id=system_id, statement=item["statement"], themes=[str(theme) for theme in item.get("themes", [])[:3]], evidence_ids=evidence_ids, confidence=clamp(item.get("confidence")), specificity=clamp(item.get("specificity")), barnum_risk=clamp(item.get("barnum_risk"))))
    return claims, None


def clamp(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def post_json(payload: dict, api_key: str) -> dict:
    request = Request(BASE_URL, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))
