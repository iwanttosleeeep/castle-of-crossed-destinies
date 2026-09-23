"""Opt-in, synthetic-data-only cost probe. Run as a separate local CLI process.

Default is offline: provider transport is replaced, even if real keys exist.
Live mode requires a dedicated environment key AND an explicit USD ceiling.
No production cases/accounts/ledger are opened; the temporary database is removed.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from contextlib import contextmanager, nullcontext
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unittest.mock import patch

from .calculation import BirthRequest, calculate_case
from .commerce import Commerce
from .jobs import Jobs
from .metering import Payer, cost_for
from .providers import SYSTEMS
from .store import CaseStore


SCENARIOS = {
    "trial": {"systems": ["numerology", "dreamspell"], "hearing": False, "credits": 5},
    "full": {"systems": list(SYSTEMS), "hearing": False, "credits": 15},
    "full-hearing": {"systems": list(SYSTEMS), "hearing": True, "credits": 30},
}
MODELS = ("deepseek-flash", "deepseek-v4-pro")
QUESTION = "这是一份合成测试案卷：面对工作节奏与自主空间的取舍，可以观察哪些具体问题？"


def budget_value(text):
    try:
        value = Decimal(text)
        if not value.is_finite() or not Decimal("0.000001") <= value <= 5:
            raise ValueError()
        return value
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError("预算须为 0.000001–5 USD 的有限正数") from None


@contextmanager
def private_budget(value):
    """This CLI's temporary ledger is the only consumer of the scoped budget."""
    name = "CASTLE_PAID_BUDGET_USD"
    previous = os.environ.get(name)
    os.environ[name] = str(value)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def offline_response(payload, _key):
    # Illustrative output lengths from the actual prompts, NOT measured tokens.
    # Omit usage: accounting then records its conservative per-attempt reserve.
    length = {2600: 1600, 2200: 1200, 1400: 700, 1200: 600, 2000: 1100}[payload["max_tokens"]]
    return {"choices": [{"message": {"content": "测" * length}, "finish_reason": "stop"}]}


def summarize(commerce, live, samples, scenario, model, maximum, provenance):
    with commerce.transaction() as db:
        records = db.execute("""SELECT c.job_id,c.step,c.state AS outcome,c.credits,
            a.state,a.reserved,a.cost,a.usage,a.elapsed FROM attempts a JOIN calls c
            ON c.id=a.call_id ORDER BY a.created""").fetchall()
    sample_by_job = {job: sample["sample"] for sample in samples for job in sample["_jobs"]}
    samples = [{k: v for k, v in sample.items() if k != "_jobs"} for sample in samples]
    steps = []
    for row in records:
        usage = json.loads(row["usage"] or "{}")
        entry = {
            "sample": sample_by_job[row["job_id"]], "step": row["step"], "outcome": row["outcome"],
            "estimated_usd": round(row["cost"] / 1_000_000, 6),
            "reserved_usd": round(row["reserved"] / 1_000_000, 6),
        }
        if live:
            entry.update(usage_known=row["state"] == "settled", elapsed_seconds=round(row["elapsed"] or 0, 3),
                         tokens={k: usage[k] for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens") if k in usage})
        steps.append(entry)
    finished = [s for s in samples if s["completed"]]
    observed_costs = [s["estimated_usd"] for s in finished]
    return {
        "mode": "live" if live else "offline_simulation", "scenario": scenario, "model": model,
        "synthetic_fixture": "2000-01-01 12:00, Beijing city center; no name",
        "conventions": provenance,
        "model_rates_usd_per_million": {
            "cache_miss": cost_for(model, {"prompt_tokens": 1_000_000}) / 1_000_000,
            "cache_hit": cost_for(model, {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 1_000_000}) / 1_000_000,
            "output": cost_for(model, {"completion_tokens": 1_000_000}) / 1_000_000,
        },
        "max_usd": float(maximum) if live else None,
        "attempts": len(steps), "samples": samples, "steps": steps,
        "unknown_usage_attempts": sum(row["state"] != "settled" for row in records) if live else None,
        "total_estimated_usd": round(sum(r["cost"] for r in records) / 1_000_000, 6),
        "completed_samples": len(finished),
        "median_completed_sample_usd": statistics.median(observed_costs) if live and observed_costs else None,
        "p95_completed_sample_usd": sorted(observed_costs)[math.ceil(len(observed_costs)*.95)-1] if live and len(observed_costs)>=20 else None,
        "notice": ("真实调用的 token 用量按配置的峰时费率估算；缺失用量时保留整笔派发预留，不冒充已知 token。非供应商账单。预算限制派发预留，不能保证价格变更后的实际账单。"
                   if live else "没有网络模型调用。正文为模拟占位；费用是这些输入长度下的保守派发预留，不是实测平均费用、保证上限或建议售价。"),
        "pricing_readiness": "单一合成资料不足以定价；需不同长度资料与多次完整采样。少于 20 个完整样本不报告 P95。",
    }


async def run_probe(scenario="trial", model="deepseek-flash", samples=1, live=False, max_usd=None):
    if scenario not in SCENARIOS or model not in MODELS or not 1 <= samples <= 30:
        raise ValueError("Invalid benchmark settings")
    if live:
        if max_usd is None:
            raise ValueError("真实采样必须显式设置 --max-usd")
        maximum = budget_value(str(max_usd))
        key = os.getenv("CASTLE_BENCHMARK_KEY", "").strip()
        if not key:
            raise ValueError("请在本机环境变量 CASTLE_BENCHMARK_KEY 中设置测试 Key；不会读取网站 Key")
    else:
        key, maximum = "offline-synthetic-key", Decimal("100")
    spec = SCENARIOS[scenario]
    request = BirthRequest(birth_date="2000-01-01", birth_time="12:00", city_id="1816670",
                           gender="female", systems=spec["systems"])
    extractions, metadata = await calculate_case(request)
    facts = {system: e["facts"] for system, e in extractions.items()}
    skill = Path(__file__).resolve().parents[2]/"skills"/"guided-chamber-reading"
    provenance = {"versions": metadata["versions"], "tzdata": metadata["tzdata_version"],
                  "lock_sha256": metadata["engine_lock_sha256"],
                  "skill_sha256": hashlib.sha256((skill/"SKILL.md").read_bytes()+(skill/"references/personas.json").read_bytes()).hexdigest()}
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="castle-cost-probe-") as folder, private_budget(maximum):
        path = Path(folder)/"probe.db"
        store, commerce = CaseStore(path), Commerce(path)
        runner = Jobs(commerce)
        # Internal throwaway account, no credentials or public login route.
        with commerce.transaction() as db:
            db.execute("INSERT INTO ledger VALUES ('synthetic-grant','probe','paid',10000,'benchmark',?)", (time.time(),))
        payer = Payer(commerce, "paid", "probe")
        transport = nullcontext() if live else patch("backend.app.deepseek.post_json", side_effect=offline_response)
        with transport:
            for index in range(samples):
                started = time.monotonic()
                case, token = store.create(spec["systems"])
                case.update(confirmed_facts=facts, facts_revision=1)
                store.save(case)
                report, _ = runner.create(case, "reports", spec["systems"], model, payer)
                await runner.run(report, case, key, payer)
                ids, states = [report["id"]], [runner.get(report["id"])["state"]]
                if spec["hearing"] and states[0] == "completed":
                    case = store.get(case["case_id"], token)
                    hearing, _ = runner.create(case, "debate", spec["systems"], model, payer, QUESTION)
                    await runner.run(hearing, case, key, payer)
                    ids.append(hearing["id"])
                    states.append(runner.get(hearing["id"])["state"])
                with commerce.transaction() as db:
                    costs = db.execute(f"SELECT COALESCE(SUM(a.cost),0) FROM attempts a JOIN calls c ON c.id=a.call_id WHERE c.job_id IN ({','.join('?' for _ in ids)})", ids).fetchone()[0]
                completed = all(s == "completed" for s in states) and len(states) == (2 if spec["hearing"] else 1)
                outcomes.append({"sample": index+1, "completed": completed, "states": states, "_jobs": ids,
                                 "estimated_usd": round(costs/1_000_000, 6),
                                 "elapsed_seconds": round(time.monotonic()-started, 3) if live else None})
                if not completed:
                    break  # Never burn successive samples after auth/budget/provider failure.
        return summarize(commerce, live, outcomes, scenario, model, maximum, provenance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="trial")
    parser.add_argument("--model", choices=MODELS, default="deepseek-flash")
    parser.add_argument("--samples", type=int, choices=range(1,31), default=1)
    parser.add_argument("--live", action="store_true", help="显式允许有预算上限的真实 API 调用")
    parser.add_argument("--max-usd", type=budget_value, help="本次累计派发预算，真实模式必填，最多 5 USD")
    args = parser.parse_args()
    try:
        result = asyncio.run(run_probe(args.scenario, args.model, args.samples, args.live, args.max_usd))
    except (ValueError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not all(sample["completed"] for sample in result["samples"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
