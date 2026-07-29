import unittest
from unittest.mock import AsyncMock, patch

from backend.app.guided_debate import guided_answer, run_guided_debate
from backend.app.schemas import Fact


class GuidedDebateTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_uses_persona_guardrails_without_json_output(self):
        call = AsyncMock(return_value="在宫阙录事看来，这一配置强调取舍。")
        fact = Fact(id="ziwei.fact-1", label="命宫", value="武曲 天相")

        with patch("backend.app.guided_debate.call_text", call):
            text, warning = await guided_answer(
                "ziwei", [fact], "我应该如何看待职业选择？", "request-key", "deepseek-v4-flash"
            )

        self.assertIsNone(warning)
        self.assertIn("宫阙录事", text)
        payload = call.await_args.args[0]
        self.assertNotIn("response_format", payload)
        self.assertIn("The Palace Registrar", payload["messages"][0]["content"])
        self.assertIn("武曲 天相", payload["messages"][1]["content"])

    async def test_full_round_keeps_answers_rebuttals_and_summary(self):
        facts = {
            "bazi": [Fact(id="bazi.fact-1", label="四柱", value="甲申 丙子 庚申 壬午")],
            "ziwei": [Fact(id="ziwei.fact-1", label="命宫", value="武曲 天相")],
        }

        async def answer(system_id, *_args):
            return f"{system_id} 独立回答", None

        async def rebuttal(system_id, *_args):
            return f"{system_id} 一次反驳", None

        with patch("backend.app.guided_debate.guided_answer", new=answer), patch(
            "backend.app.guided_debate.guided_rebuttal", new=rebuttal
        ), patch(
            "backend.app.guided_debate.guided_summary",
            new=AsyncMock(return_value=("主持人结案总结", None)),
        ):
            hearing, warning = await run_guided_debate(
                "职业选择怎么看？", facts, "request-key", "deepseek-v4-flash"
            )

        self.assertIsNone(warning)
        self.assertEqual(hearing["mode"], "guided")
        self.assertEqual(len(hearing["guided_answers"]), 2)
        self.assertEqual(len(hearing["guided_rebuttals"]), 2)
        self.assertEqual(hearing["guided_summary"], "主持人结案总结")


if __name__ == "__main__":
    unittest.main()
