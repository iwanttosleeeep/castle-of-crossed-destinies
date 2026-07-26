import unittest
from unittest.mock import AsyncMock, patch

from backend.app.gemini import FACT_SCHEMA, MAX_INLINE_BYTES, extract_facts_with_gemini


class GeminiExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_visual_file_is_sent_inline_and_facts_require_source_span(self):
        response = {
            "facts": [
                {
                    "label": "Kin",
                    "value": "133",
                    "source_span": "PAGE 1, center: Kin 133",
                    "confidence": 0.96,
                    "time_sensitive": False,
                },
                {
                    "label": "Unsupported",
                    "value": "invented",
                    "source_span": "",
                    "confidence": 0.9,
                    "time_sensitive": False,
                },
            ],
            "source_commentary": ["A poetic interpretation was excluded."],
        }
        mocked_call = AsyncMock(return_value=response)
        with patch("backend.app.gemini.call_gemini_json", mocked_call):
            facts, commentary, warning = await extract_facts_with_gemini(
                "dreamspell",
                b"synthetic-image-bytes",
                "image/png",
                "dreamspell.png",
                "visitor-gemini-key",
                "gemini-3.6-flash",
            )
        self.assertIsNone(warning)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].value, "133")
        self.assertEqual(commentary, ["A poetic interpretation was excluded."])
        payload, key, model = mocked_call.await_args.args
        self.assertEqual(key, "visitor-gemini-key")
        self.assertEqual(model, "gemini-3.6-flash")
        inline = payload["contents"][0]["parts"][0]["inline_data"]
        self.assertEqual(inline["mime_type"], "image/png")
        self.assertNotIn("visitor-gemini-key", str(payload))
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"], FACT_SCHEMA)

    async def test_text_input_does_not_become_an_inline_file(self):
        mocked_call = AsyncMock(return_value={"facts": [], "source_commentary": []})
        with patch("backend.app.gemini.call_gemini_json", mocked_call):
            _, _, warning = await extract_facts_with_gemini(
                "numerology",
                b"ignored",
                "text/plain",
                "report.txt",
                "visitor-gemini-key",
                source_text="Life Path: 7",
            )
        payload = mocked_call.await_args.args[0]
        parts = payload["contents"][0]["parts"]
        self.assertEqual(len(parts), 1)
        self.assertIn("Life Path: 7", parts[0]["text"])
        self.assertIn("没有识别", warning)

    async def test_oversized_inline_visual_falls_back_before_network(self):
        mocked_call = AsyncMock()
        with patch("backend.app.gemini.call_gemini_json", mocked_call):
            facts, _, warning = await extract_facts_with_gemini(
                "bazi",
                b"x" * (MAX_INLINE_BYTES + 1),
                "image/png",
                "large.png",
                "visitor-gemini-key",
            )
        self.assertEqual(facts, [])
        self.assertIn("20 MB", warning)
        mocked_call.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
