import unittest
from unittest.mock import AsyncMock, patch

from backend.app.guided_reports import (
    clean_text_response,
    run_guided_chamber,
    run_guided_tribunal,
)
from backend.app.schemas import Fact


class GuidedReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_chamber_uses_compact_skill_without_json_output(self):
        fact = Fact(id="ziwei.fact-1", label="命宫", value="武曲 天相", time_sensitive=True)
        call = AsyncMock(return_value="## 宫阙录事\n本宫呈现的是一种配置。")

        with patch("backend.app.guided_reports.call_text", call):
            text, warning = await run_guided_chamber(
                "ziwei", "Zi Wei Dou Shu", [fact], "request-key", "deepseek-v4-flash"
            )

        self.assertIsNone(warning)
        self.assertIn("宫阙录事", text)
        payload = call.await_args.args[0]
        self.assertNotIn("response_format", payload)
        self.assertIn("The Palace Registrar", payload["messages"][0]["content"])
        self.assertNotIn("ZIWEI-STAR-WQ", payload["messages"][0]["content"])

    async def test_tribunal_returns_plain_text(self):
        call = AsyncMock(return_value="## 具体共识\n两份报告都讨论了变化。")
        with patch("backend.app.guided_reports.call_text", call):
            text, warning = await run_guided_tribunal(
                {"bazi": "八字报告", "ziwei": "紫微报告"},
                "request-key",
                "deepseek-v4-flash",
            )
        self.assertIsNone(warning)
        self.assertIn("具体共识", text)
        self.assertNotIn("response_format", call.await_args.args[0])

    def test_outer_code_fence_is_removed(self):
        self.assertEqual(clean_text_response("```markdown\n正文\n```"), "正文")


if __name__ == "__main__":
    unittest.main()
