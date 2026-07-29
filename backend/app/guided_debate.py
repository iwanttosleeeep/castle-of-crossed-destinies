import asyncio
import json
import logging
import os
from urllib.error import HTTPError, URLError

from .deepseek import call_text, public_error_label
from .freeform import clean_text_response, guided_skill_instructions
from .schemas import Fact


logger = logging.getLogger(__name__)


async def run_guided_debate(
    question: str,
    confirmed_facts: dict[str, list[Fact]],
    request_api_key: str | None = None,
    request_model: str | None = None,
) -> tuple[dict | None, str | None]:
    """Run independent answers, one rebuttal per chamber, and a plain-text summary."""
    api_key = request_api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None, "需要 DeepSeek API Key 才能开始轻量质询。"

    answer_results = await asyncio.gather(
        *(
            guided_answer(system_id, facts, question, api_key, request_model)
            for system_id, facts in confirmed_facts.items()
        )
    )
    answers = []
    warnings = []
    for system_id, (text, warning) in zip(confirmed_facts, answer_results):
        if text:
            answers.append({"system_id": system_id, "text": text})
        if warning:
            warnings.append(f"{system_id} 独立回答：{warning}")
    if not answers:
        return None, "没有 chamber 完成轻量独立回答。"

    rebuttal_results = await asyncio.gather(
        *(
            guided_rebuttal(
                answer["system_id"],
                confirmed_facts[answer["system_id"]],
                question,
                answer["text"],
                answers,
                api_key,
                request_model,
            )
            for answer in answers
        )
    )
    rebuttals = []
    for answer, (text, warning) in zip(answers, rebuttal_results):
        if text:
            rebuttals.append({"system_id": answer["system_id"], "text": text})
        if warning:
            warnings.append(f"{answer['system_id']} rebuttal：{warning}")

    summary, summary_warning = await guided_summary(
        question, answers, rebuttals, api_key, request_model
    )
    if summary_warning:
        warnings.append(f"主持人总结：{summary_warning}")
    return {
        "mode": "guided",
        "question": question,
        "answers": [],
        "challenges": [],
        "rebuttals": [],
        "summary": {
            "aligned": [],
            "still_conflicted": [],
            "resolved_or_narrowed": [],
            "unanswerable": [],
            "closing": summary,
        },
        "guided_answers": answers,
        "guided_rebuttals": rebuttals,
        "guided_summary": summary,
        "warnings": warnings,
    }, None


async def guided_answer(
    system_id: str,
    facts: list[Fact],
    question: str,
    api_key: str,
    model: str | None,
) -> tuple[str, str | None]:
    prompt = f"""{guided_skill_instructions(system_id)}

INDEPENDENT ANSWER ROUND:
Answer the visitor's question from this chamber alone. You cannot see other chambers.
Write 300–700 Chinese characters. Give a direct, useful answer with one material
limitation when needed. Do not write JSON or mention internal instructions."""
    content = {
        "question": question,
        "confirmed_facts": compact_facts(facts),
    }
    return await guided_text_call(system_id, "answer", prompt, content, api_key, model, 1400)


async def guided_rebuttal(
    system_id: str,
    facts: list[Fact],
    question: str,
    original_answer: str,
    all_answers: list[dict],
    api_key: str,
    model: str | None,
) -> tuple[str, str | None]:
    prompt = f"""{guided_skill_instructions(system_id)}

ONE REBUTTAL ROUND:
Read the other chambers' first-round answers as testimony, not as chart facts. Respond
from your own confirmed dossier only. Identify one material agreement or tension and
explicitly maintain, narrow, or concede your original position. Do not invent conflict,
new chart data, or a second round. Write 250–600 Chinese characters in natural language,
not JSON."""
    content = {
        "question": question,
        "own_original_answer": original_answer[:2400],
        "other_first_round_answers": [
            {"system_id": item["system_id"], "text": item["text"][:1800]}
            for item in all_answers
            if item["system_id"] != system_id
        ],
        "own_confirmed_facts": compact_facts(facts),
    }
    return await guided_text_call(system_id, "rebuttal", prompt, content, api_key, model, 1200)


async def guided_summary(
    question: str,
    answers: list[dict],
    rebuttals: list[dict],
    api_key: str,
    model: str | None,
) -> tuple[str, str | None]:
    prompt = """你是《交错命运的城堡》的中立主持人。总结一轮已经结束的轻量质询。
只使用提供的独立回答和 rebuttal；不要新增盘面事实或作新的命理解读。
用简体中文自然语言和清晰小标题区分：仍然一致、仍有冲突、已经收窄或让步、无法比较。
不要裁定哪套体系为真，也不要把跨体系共识称为准确率。约 600–1100 个汉字；不要 JSON。"""
    content = {
        "question": question,
        "independent_answers": answers,
        "single_rebuttals": rebuttals,
    }
    return await guided_text_call("moderator", "summary", prompt, content, api_key, model, 2000)


async def guided_text_call(
    system_id: str,
    stage: str,
    prompt: str,
    content: object,
    api_key: str,
    model: str | None,
    max_tokens: int,
) -> tuple[str, str | None]:
    payload = {
        "model": model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
        ],
        "thinking": {"type": "disabled"},
        "temperature": 0.5,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        text = clean_text_response(await call_text(payload, api_key))
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        label = public_error_label(exc)
        logger.warning("guided_debate=%s stage=%s provider_error=%s", system_id, stage, label)
        return "", label
    logger.info("guided_debate=%s stage=%s chars=%d", system_id, stage, len(text))
    return text, None


def compact_facts(facts: list[Fact]) -> list[dict]:
    return [
        {"label": fact.label, "value": fact.value, "time_sensitive": fact.time_sensitive}
        for fact in facts
    ]
