import argparse
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.benchmark import budget_value, run_probe
from backend.app.store import CaseStore


RESPONSE = {"choices": [{"message": {"content": "仅为合成测试的中文正文"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "prompt_cache_hit_tokens": 50}}


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.production = Path(self.temp.name)/"untouched.db"
        CaseStore(self.production).create(["bazi"])
        self.original = self.production.read_bytes()
        self.env = patch.dict(os.environ, {"CASTLE_DB_PATH": str(self.production),
            "CASTLE_BENCHMARK_KEY": "synthetic-benchmark-secret", "DEEPSEEK_API_KEY": "synthetic-production-secret",
            "CASTLE_PAID_BUDGET_USD": "0", "CASTLE_FLASH_INPUT_RATE": "0.30",
            "CASTLE_FLASH_CACHED_RATE": "0.006", "CASTLE_FLASH_OUTPUT_RATE": "1.20"})
        self.env.start()
        self.slots = patch("backend.app.deepseek.provider_slots", asyncio.Semaphore(3))
        self.slots.start()

    async def asyncTearDown(self):
        self.assertEqual(self.production.read_bytes(), self.original)
        self.assertEqual(os.environ["CASTLE_PAID_BUDGET_USD"], "0")
        self.slots.stop()
        self.env.stop()
        self.temp.cleanup()

    async def test_offline_all_steps_never_use_network_or_existing_keys(self):
        with patch("backend.app.deepseek.urlopen", side_effect=AssertionError("No networking allowed")) as network:
            result = await run_probe("full-hearing")
        network.assert_not_called()
        self.assertEqual(result["mode"], "offline_simulation")
        self.assertEqual(result["attempts"], 23)
        self.assertEqual(result["completed_samples"], 1)
        self.assertIsNone(result["median_completed_sample_usd"])
        self.assertIsNone(result["p95_completed_sample_usd"])
        self.assertTrue(all("tokens" not in step for step in result["steps"]))
        self.assertNotIn("synthetic-production-secret", json.dumps(result))
        self.assertNotIn("synthetic-benchmark-secret", json.dumps(result))
        self.assertNotIn("测测测", json.dumps(result))

    async def test_live_requires_both_budget_and_dedicated_key(self):
        with patch("backend.app.deepseek.post_json") as provider:
            with self.assertRaises(ValueError):
                await run_probe(live=True)
            with patch.dict(os.environ, {"CASTLE_BENCHMARK_KEY": ""}):
                with self.assertRaises(ValueError):
                    await run_probe(live=True, max_usd="1")
        provider.assert_not_called()
        for value in ["NaN", "Infinity", "-1", "0", "6"]:
            with self.assertRaises(argparse.ArgumentTypeError):
                budget_value(value)

    async def test_live_metering_redaction_and_repeated_samples_are_not_cached(self):
        with patch("backend.app.deepseek.post_json", return_value=RESPONSE) as provider:
            result = await run_probe(samples=2, live=True, max_usd="1")
        self.assertEqual(provider.call_count, 6)
        self.assertTrue(all(call.args[1] == "synthetic-benchmark-secret" for call in provider.call_args_list))
        self.assertEqual(result["total_estimated_usd"], 0.000312)
        self.assertEqual(result["median_completed_sample_usd"], 0.000156)
        self.assertIsNone(result["p95_completed_sample_usd"])
        self.assertTrue(all(step["usage_known"] for step in result["steps"]))
        self.assertEqual({step["sample"] for step in result["steps"]}, {1,2})
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("synthetic-benchmark-secret", rendered)
        self.assertNotIn("仅为合成测试的中文正文", rendered)

    async def test_budget_refuses_dispatch_and_stops_further_samples(self):
        with patch("backend.app.deepseek.post_json") as provider:
            result = await run_probe(samples=3, live=True, max_usd="0.000001")
        provider.assert_not_called()
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(len(result["samples"]), 1)
        self.assertFalse(result["samples"][0]["completed"])
        self.assertEqual(result["total_estimated_usd"], 0)

    async def test_unknown_usage_is_not_presented_as_known_tokens(self):
        response = {"choices": RESPONSE["choices"]}
        with patch("backend.app.deepseek.post_json", return_value=response):
            result = await run_probe(live=True, max_usd="1")
        self.assertTrue(all(not step["usage_known"] for step in result["steps"]))
        self.assertTrue(all(step["tokens"] == {} for step in result["steps"]))
        self.assertGreater(result["total_estimated_usd"], 0)


if __name__ == "__main__":
    unittest.main()
