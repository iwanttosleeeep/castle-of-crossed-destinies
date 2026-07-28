import json
import os
from collections import defaultdict
from urllib.error import HTTPError, URLError

from .deepseek import THEMES, bounded_input, call_json, clamp
from .schemas import Claim


FINDING_TYPES = {
    "genuine_convergence",
    "apparent_convergence",
    "direct_conflict",
    "different_emphasis",
    "uncomparable",
}


async def run_tribunal(
    claims: list[Claim], request_api_key: str | None = None, request_model: str | None = None
) -> tuple[dict, str | None]:
    api_key = request_api_key or os.getenv("DEEPSEEK_API_KEY")
    if len({claim.system_id for claim in claims}) < 2:
        return empty_tribunal("至少需要两套体系的证词才能比较。"), None
    if not api_key:
        return empty_tribunal("需要 DeepSeek API Key 才能进行语义比对。"), "DeepSeek 未配置"
    admissible = {
        claim.id: {
            "claim_id": claim.id,
            "system_id": claim.system_id,
            "statement": claim.neutral_statement,
            "themes": claim.themes,
            "specificity": claim.specificity,
            "barnum_risk": claim.barnum_risk,
        }
        for claim in claims
    }
    prompt = """You are the neutral Tribunal. You receive independent, neutral claims only.
Write every human-readable output field in Simplified Chinese.
Cluster claims that address the same proposition, not merely the same broad theme. Classify each cluster as:
genuine_convergence (different systems, specific compatible propositions), apparent_convergence (similar but generic/Barnum wording), direct_conflict (incompatible answers to the same question), different_emphasis (compatible but focused on different aspects), or uncomparable (different time scales/concepts).
Never decide which divination system is true. Do not create new claims. Use only supplied claim_ids.
Return JSON only: {"findings":[{"title":"concise label","type":"one classification","theme":"controlled theme","claim_ids":["id"],"explanation":"why this classification fits","open_question":"what evidence or clarification remains"}],"summary":"careful overall summary"}.
Every finding needs at least two claims from at least two systems. Do not reveal chain-of-thought."""
    payload = {
        "model": request_model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(list(admissible.values()), ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 3200,
        "stream": False,
    }
    try:
        body = await call_json(payload, api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return empty_tribunal("Tribunal 暂未完成。"), f"Tribunal error: {type(exc).__name__}"
    findings = []
    seen_groups: set[tuple[str, ...]] = set()
    for item in body.get("findings", [])[:24]:
        claim_ids = list(dict.fromkeys(cid for cid in item.get("claim_ids", []) if cid in admissible))
        systems = {admissible[cid]["system_id"] for cid in claim_ids}
        group = tuple(sorted(claim_ids))
        finding_type = item.get("type")
        if len(claim_ids) < 2 or len(systems) < 2 or group in seen_groups or finding_type not in FINDING_TYPES:
            continue
        seen_groups.add(group)
        score = agreement_score([admissible[cid] for cid in claim_ids]) if finding_type in {"genuine_convergence", "apparent_convergence"} else None
        findings.append({
            "id": f"finding-{len(findings) + 1}",
            "title": bounded_input(item.get("title"), 120) or "Untitled finding",
            "type": finding_type,
            "theme": item.get("theme") if item.get("theme") in THEMES else "identity_orientation",
            "claim_ids": claim_ids,
            "systems": sorted(systems),
            "agreement_strength": score,
            "explanation": bounded_input(item.get("explanation"), 800),
            "open_question": bounded_input(item.get("open_question"), 500),
        })
    counts = defaultdict(int)
    for finding in findings:
        counts[finding["type"]] += 1
    return {
        "findings": findings,
        "summary": bounded_input(body.get("summary"), 1200),
        "counts": dict(counts),
        "disclaimer": "Agreement strength measures narrative convergence, not accuracy or truth.",
    }, None


def agreement_score(items: list[dict]) -> int:
    system_count = len({item["system_id"] for item in items})
    coverage = min(1.0, system_count / 4)
    specificity = sum(clamp(item["specificity"]) for item in items) / len(items)
    anti_barnum = sum(1 - clamp(item["barnum_risk"]) for item in items) / len(items)
    return round(100 * coverage * specificity * anti_barnum)


def empty_tribunal(summary: str) -> dict:
    return {
        "findings": [],
        "summary": summary,
        "counts": {},
        "disclaimer": "Agreement strength measures narrative convergence, not accuracy or truth.",
    }
