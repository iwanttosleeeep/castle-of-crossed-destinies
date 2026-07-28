import asyncio
import json
import os
from urllib.error import HTTPError, URLError

from .deepseek import (
    RULE_PATTERN,
    bounded_input,
    call_json,
    contains_han,
    persona_instructions,
    skill_instructions,
)
from .schemas import Fact


async def run_debate(
    question: str,
    confirmed_facts: dict[str, list[Fact]],
    request_api_key: str | None = None,
    request_model: str | None = None,
) -> tuple[dict | None, str | None]:
    api_key = request_api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None, "需要 DeepSeek API Key 才能开始质询。"
    rounds = await asyncio.gather(
        *(independent_answer(system_id, facts, question, api_key, request_model) for system_id, facts in confirmed_facts.items())
    )
    answers = [answer for answer in rounds if answer]
    if not answers:
        return None, "没有 chamber 产生可采纳的独立回答。"
    challenges = await moderate_challenges(question, answers, api_key, request_model)
    rebuttals = await asyncio.gather(
        *(
            rebuttal(
                challenge["target_system"],
                confirmed_facts[challenge["target_system"]],
                question,
                next(answer for answer in answers if answer["system_id"] == challenge["target_system"]),
                challenge,
                api_key,
                request_model,
            )
            for challenge in challenges
            if challenge["target_system"] in confirmed_facts
            and any(answer["system_id"] == challenge["target_system"] for answer in answers)
        )
    )
    admitted_rebuttals = [item for item in rebuttals if item]
    summary = await final_summary(question, answers, challenges, admitted_rebuttals, api_key, request_model)
    return {
        "question": question,
        "answers": answers,
        "challenges": challenges,
        "rebuttals": admitted_rebuttals,
        "summary": summary,
    }, None


async def independent_answer(
    system_id: str, facts: list[Fact], question: str, api_key: str, model: str | None
) -> dict | None:
    instructions = skill_instructions(system_id)
    allowed_fact_ids = {fact.id for fact in facts}
    allowed_rule_ids = set(RULE_PATTERN.findall(instructions))
    prompt = f"""{instructions}

Answer the visitor's question only when these facts support an answer. You cannot see other chambers.
Write every human-readable output field in Simplified Chinese, retaining technical terms when needed.
Return JSON only: {{"answer":"neutral evidence-bound answer or explicit abstention","evidence_ids":["fact.id"],"rule_ids":["RULE-ID"],"caveat":"material limitation","abstained":false}}.
If the question asks for unsupported prediction, health/legal/financial certainty, or facts outside the dossier, abstain.
Do not reveal chain-of-thought."""
    dossier = [fact.model_dump() for fact in facts]
    payload = model_payload(model, prompt, {"question": question, "dossier": dossier}, 1800, True)
    try:
        body = await call_json(payload, api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return None
    neutral = bounded_input(body.get("answer"), 1600)
    if not neutral:
        return None
    evidence_ids = [item for item in body.get("evidence_ids", []) if item in allowed_fact_ids]
    rule_ids = [item for item in body.get("rule_ids", []) if item in allowed_rule_ids]
    abstained = bool(body.get("abstained"))
    if not abstained and (not evidence_ids or not rule_ids):
        return None
    statement = await style_answer(system_id, neutral, api_key, model)
    return {
        "system_id": system_id,
        "neutral_answer": neutral,
        "statement": statement,
        "evidence_ids": evidence_ids,
        "rule_ids": rule_ids,
        "caveat": bounded_input(body.get("caveat"), 500),
        "abstained": abstained,
    }


async def moderate_challenges(question: str, answers: list[dict], api_key: str, model: str | None) -> list[dict]:
    system_ids = {answer["system_id"] for answer in answers}
    neutral = [{"system_id": answer["system_id"], "answer": answer["neutral_answer"]} for answer in answers]
    prompt = """You are a neutral moderator. Compare independent answers to one visitor question.
Write every human-readable output field in Simplified Chinese.
Identify only material contradictions or assumptions worth testing. Do not manufacture disagreement.
Issue at most one challenge to any chamber and at most five total. A challenge must name a target_system.
Return JSON only: {"challenges":[{"target_system":"id","raised_by":"another id or moderator","issue":"specific tension","question":"one precise rebuttal question"}]}.
Do not decide which symbolic system is true. Do not reveal chain-of-thought."""
    try:
        body = await call_json(model_payload(model, prompt, {"question": question, "answers": neutral}, 1800, True), api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return []
    challenges = []
    targeted = set()
    for item in body.get("challenges", [])[:5]:
        target = item.get("target_system")
        if target not in system_ids or target in targeted:
            continue
        targeted.add(target)
        challenges.append({
            "target_system": target,
            "raised_by": item.get("raised_by") if item.get("raised_by") in system_ids else "moderator",
            "issue": bounded_input(item.get("issue"), 500),
            "question": bounded_input(item.get("question"), 500),
        })
    return challenges


async def rebuttal(
    system_id: str,
    facts: list[Fact],
    question: str,
    original: dict,
    challenge: dict,
    api_key: str,
    model: str | None,
) -> dict | None:
    instructions = skill_instructions(system_id)
    allowed_fact_ids = {fact.id for fact in facts}
    allowed_rule_ids = set(RULE_PATTERN.findall(instructions))
    prompt = f"""{instructions}

This is your single rebuttal. Answer only the moderator's challenge using your own dossier.
Write every human-readable output field in Simplified Chinese, retaining technical terms when needed.
You may narrow, clarify, concede, or maintain the original neutral answer. Do not introduce new chart facts.
Return JSON only: {{"rebuttal":"neutral response","evidence_ids":["fact.id"],"rule_ids":["RULE-ID"],"disposition":"maintained|narrowed|conceded|unresolved","caveat":"limitation"}}.
Do not reveal chain-of-thought."""
    context = {
        "visitor_question": question,
        "original_answer": original["neutral_answer"],
        "challenge": challenge,
        "dossier": [fact.model_dump() for fact in facts],
    }
    try:
        body = await call_json(model_payload(model, prompt, context, 1600, True), api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return None
    neutral = bounded_input(body.get("rebuttal"), 1400)
    evidence_ids = [item for item in body.get("evidence_ids", []) if item in allowed_fact_ids]
    rule_ids = [item for item in body.get("rule_ids", []) if item in allowed_rule_ids]
    if not neutral or not evidence_ids or not rule_ids:
        return None
    return {
        "system_id": system_id,
        "neutral_rebuttal": neutral,
        "statement": await style_answer(system_id, neutral, api_key, model),
        "evidence_ids": evidence_ids,
        "rule_ids": rule_ids,
        "disposition": body.get("disposition") if body.get("disposition") in {"maintained", "narrowed", "conceded", "unresolved"} else "unresolved",
        "caveat": bounded_input(body.get("caveat"), 500),
    }


async def final_summary(
    question: str, answers: list[dict], challenges: list[dict], rebuttals: list[dict], api_key: str, model: str | None
) -> dict:
    prompt = """You are the final neutral moderator. Summarize a completed one-round hearing.
Write every human-readable output field in Simplified Chinese.
Use only the provided neutral answers, challenges, and neutral rebuttals. Separate what remains aligned,
what remains in conflict, what was narrowed or conceded, and what is unanswerable. Do not synthesize a prediction.
Return JSON only: {"aligned":["..."],"still_conflicted":["..."],"resolved_or_narrowed":["..."],"unanswerable":["..."],"closing":"short careful conclusion"}.
Do not reveal chain-of-thought."""
    neutral_context = {
        "question": question,
        "answers": [{"system_id": item["system_id"], "answer": item["neutral_answer"], "abstained": item["abstained"]} for item in answers],
        "challenges": challenges,
        "rebuttals": [{"system_id": item["system_id"], "rebuttal": item["neutral_rebuttal"], "disposition": item["disposition"]} for item in rebuttals],
    }
    try:
        body = await call_json(model_payload(model, prompt, neutral_context, 2200, True), api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return {"aligned": [], "still_conflicted": [], "resolved_or_narrowed": [], "unanswerable": [], "closing": "总结生成失败；独立回答仍已保留。"}
    return {
        key: [bounded_input(item, 600) for item in body.get(key, [])[:12] if bounded_input(item, 600)]
        for key in ("aligned", "still_conflicted", "resolved_or_narrowed", "unanswerable")
    } | {"closing": bounded_input(body.get("closing"), 1000)}


async def style_answer(system_id: str, neutral: str, api_key: str, model: str | None) -> str:
    prompt = f"""{persona_instructions(system_id)}
You are a voice framer, not an interpreter. Write framing in Simplified Chinese only.
Keep the neutral text as an exact continuous substring.
Add at most one short in-character lead-in. Do not change factual or modal content.
Return JSON only: {{"statement":"lead-in + exact neutral text"}}."""
    try:
        body = await call_json(model_payload(model, prompt, {"neutral": neutral}, 1000, False), api_key)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return neutral
    candidate = bounded_input(body.get("statement"), len(neutral) + 120)
    framing = candidate.replace(neutral, "", 1).strip() if neutral in candidate else ""
    return candidate if neutral in candidate and (not framing or contains_han(framing)) else neutral


def model_payload(model: str | None, prompt: str, content: object, max_tokens: int, thinking: bool) -> dict:
    payload = {
        "model": model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(content, ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled" if thinking else "disabled"},
        "max_tokens": max_tokens,
        "stream": False,
    }
    if thinking:
        payload["reasoning_effort"] = "high"
    else:
        payload["temperature"] = 0.2
    return payload
