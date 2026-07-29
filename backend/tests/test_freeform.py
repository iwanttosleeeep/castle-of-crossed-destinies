import unittest
from unittest.mock import AsyncMock, patch

from backend.app.freeform import clean_text_response, run_free_chamber, run_free_tribunal, run_guided_chamber
from backend.app.schemas import Fact


class FreeformTests(unittest.IsolatedAsyncioTestCase):
    async def test_chamber_returns_plain_text_without_json_contract_or_skills(self):
        fact = Fact(
            id="bazi.confirmed-1",
            label="四柱",
            value="甲申 丙子 庚申 壬午",
            time_sensitive=True,
        )
        call = AsyncMock(return_value="## 核心结构\n这是一份自然语言解读。")

        with patch("backend.app.freeform.call_text", call):
            text, warning = await run_free_chamber(
                "bazi",
                "BaZi 八字",
                [fact],
                "request-key",
                "deepseek-v4-flash",
            )

        self.assertIsNone(warning)
        self.assertIn("自然语言解读", text)
        payload = call.await_args.args[0]
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("Rule ID", payload["messages"][0]["content"])
        self.assertIn("甲申 丙子 庚申 壬午", payload["messages"][1]["content"])

    async def test_tribunal_returns_plain_text(self):
        call = AsyncMock(return_value="## 具体共识\n两份报告都讨论了变化。")
        with patch("backend.app.freeform.call_text", call):
            text, warning = await run_free_tribunal(
                {"bazi": "八字报告", "ziwei": "紫微报告"},
                "request-key",
                "deepseek-v4-flash",
            )

        self.assertIsNone(warning)
        self.assertIn("具体共识", text)
        self.assertNotIn("response_format", call.await_args.args[0])

    async def test_guided_chamber_loads_only_compact_skill_and_selected_persona(self):
        fact = Fact(id="ziwei.fact-1", label="命宫", value="武曲 天相", time_sensitive=True)
        call = AsyncMock(return_value="## 宫阙录事\n本宫呈现的是一种配置。")

        with patch("backend.app.freeform.call_text", call):
            text, warning = await run_guided_chamber(
                "ziwei", "Zi Wei Dou Shu", [fact], "request-key", "deepseek-v4-flash"
            )

        self.assertIsNone(warning)
        self.assertIn("宫阙录事", text)
        system_prompt = call.await_args.args[0]["messages"][0]["content"]
        self.assertIn("The Palace Registrar", system_prompt)
        self.assertIn("compact hallucination safeguards", system_prompt)
        self.assertNotIn("ZIWEI-STAR-WQ", system_prompt)
        self.assertNotIn("response_format", call.await_args.args[0])

    def test_outer_code_fence_is_removed(self):
        self.assertEqual(clean_text_response("```markdown\n正文\n```"), "正文")


if __name__ == "__main__":
    unittest.main()
