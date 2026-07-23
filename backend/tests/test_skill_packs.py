import re
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from backend.app.deepseek import (
    RULE_PATTERN,
    extract_facts_only,
    persona_instructions,
    run_chamber_skill,
    skill_instructions,
)
from backend.app.providers import SYSTEMS
from backend.app.schemas import Fact


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"


class SkillPackTests(unittest.TestCase):
    def test_all_systems_have_required_files(self):
        for system_id in SYSTEMS:
            chamber = SKILLS / f"{system_id.replace('_', '-')}-chamber"
            with self.subTest(system_id=system_id):
                self.assertTrue((chamber / "SKILL.md").is_file())
                self.assertTrue((chamber / "agents" / "openai.yaml").is_file())
                self.assertTrue((chamber / "references" / "knowledge.md").is_file())
                self.assertTrue((chamber / "references" / "persona.md").is_file())

    def test_neutral_prompt_excludes_persona(self):
        for system_id in SYSTEMS:
            with self.subTest(system_id=system_id):
                neutral = skill_instructions(system_id)
                persona = persona_instructions(system_id)
                self.assertIn("Castle Grounding Contract", neutral)
                self.assertIn("Source notes", neutral)
                self.assertNotIn("Style-only contract", neutral)
                self.assertIn("Style-only contract", persona)

    def test_each_pack_has_unique_grounded_rules(self):
        all_rules = {}
        for system_id in SYSTEMS:
            rules = set(RULE_PATTERN.findall(skill_instructions(system_id)))
            with self.subTest(system_id=system_id):
                self.assertGreaterEqual(len(rules), 10)
            for rule in rules:
                self.assertNotIn(rule, all_rules, f"{rule} repeated in {system_id} and {all_rules.get(rule)}")
                all_rules[rule] = system_id

    def test_sources_are_https(self):
        for system_id in SYSTEMS:
            knowledge = (
                SKILLS
                / f"{system_id.replace('_', '-')}-chamber"
                / "references"
                / "knowledge.md"
            ).read_text(encoding="utf-8")
            urls = re.findall(r"https://\S+", knowledge)
            with self.subTest(system_id=system_id):
                self.assertGreaterEqual(len(urls), 3)
                self.assertTrue(all(url.startswith("https://") for url in urls))

    def test_frontmatter_has_only_name_and_description(self):
        for system_id in SYSTEMS:
            path = SKILLS / f"{system_id.replace('_', '-')}-chamber" / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]
            keys = [
                line.split(":", 1)[0].strip()
                for line in frontmatter.splitlines()
                if ":" in line
            ]
            with self.subTest(system_id=system_id):
                self.assertEqual(keys, ["name", "description"])


class ChamberRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_extractor_rejects_items_without_source_span(self):
        mocked_call = AsyncMock(return_value={
            "facts": [
                {"label": "Sun", "value": "Aries", "source_span": "PAGE 1: Sun Aries", "confidence": 0.9},
                {"label": "Personality", "value": "brave", "confidence": 0.8},
            ],
            "source_commentary": ["The report says the visitor is brave."],
        })
        with patch("backend.app.deepseek.call_json", mocked_call):
            facts, commentary, warning = await extract_facts_only(
                "western", "Sun: Aries", "chart.txt", "visitor-key", "deepseek-v4-flash"
            )
        self.assertIsNone(warning)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].label, "Sun")
        self.assertEqual(commentary, ["The report says the visitor is brave."])
        extraction_prompt = mocked_call.await_args.args[0]["messages"][0]["content"]
        self.assertIn("Do not interpret", extraction_prompt)
        self.assertIn("untrusted data", extraction_prompt)

    async def test_request_scoped_key_and_model_are_forwarded_without_environment_storage(self):
        mocked_call = AsyncMock(return_value={"claims": []})
        with patch.dict("os.environ", {}, clear=True):
            with patch("backend.app.deepseek.call_json", mocked_call):
                claims, warning = await run_chamber_skill(
                    "western",
                    [Fact(id="western.sun-1", label="Sun", value="Aries")],
                    request_api_key="visitor-key",
                    request_model="deepseek-v4-pro",
                )

        self.assertIsNone(warning)
        self.assertEqual(claims, [])
        payload, api_key = mocked_call.await_args.args
        self.assertEqual(api_key, "visitor-key")
        self.assertEqual(payload["model"], "deepseek-v4-pro")

    async def test_persona_pass_cannot_replace_neutral_testimony(self):
        neutral_response = {
            "claims": [
                {
                    "neutral_statement": "The supplied Sun fact supports a bounded identity theme.",
                    "themes": ["identity_orientation"],
                    "evidence_ids": ["western.sun-1"],
                    "rule_ids": ["WEST-PLANET-SUN"],
                    "caveat": "No house or aspect context was supplied.",
                    "counter_reading": "Other chart factors could redirect visibility.",
                    "confidence": 0.55,
                    "specificity": 0.52,
                    "barnum_risk": 0.4,
                }
            ]
        }
        style_response = {
            "statements": [
                {
                    "index": 0,
                    "statement": "The cartographer marks this route: The supplied Sun fact supports a bounded identity theme.",
                }
            ]
        }
        mocked_call = AsyncMock(side_effect=[neutral_response, style_response])
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            with patch("backend.app.deepseek.call_json", mocked_call):
                claims, warning = await run_chamber_skill(
                    "western",
                    [Fact(id="western.sun-1", label="Sun", value="Aries")],
                )

        self.assertIsNone(warning)
        self.assertEqual(len(claims), 1)
        self.assertEqual(
            claims[0].neutral_statement,
            "The supplied Sun fact supports a bounded identity theme.",
        )
        self.assertEqual(
            claims[0].statement,
            "The cartographer marks this route: The supplied Sun fact supports a bounded identity theme.",
        )
        self.assertEqual(claims[0].rule_ids, ["WEST-PLANET-SUN"])
        self.assertEqual(mocked_call.await_count, 2)

    async def test_claim_with_invented_rule_is_rejected_before_styling(self):
        mocked_call = AsyncMock(
            return_value={
                "claims": [
                    {
                        "neutral_statement": "Unsupported.",
                        "themes": ["identity_orientation"],
                        "evidence_ids": ["western.sun-1"],
                        "rule_ids": ["WEST-INVENTED-999"],
                        "caveat": "None.",
                        "counter_reading": "None.",
                        "confidence": 0.9,
                        "specificity": 0.9,
                        "barnum_risk": 0.1,
                    }
                ]
            }
        )
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            with patch("backend.app.deepseek.call_json", mocked_call):
                claims, warning = await run_chamber_skill(
                    "western",
                    [Fact(id="western.sun-1", label="Sun", value="Aries")],
                )

        self.assertIsNone(warning)
        self.assertEqual(claims, [])
        self.assertEqual(mocked_call.await_count, 1)

    async def test_persona_rewrite_that_drops_neutral_text_is_rejected(self):
        neutral_response = {
            "claims": [
                {
                    "neutral_statement": "Only the supplied number supports a cautious inquiry theme.",
                    "themes": ["meaning_imagination"],
                    "evidence_ids": ["numerology.life-path-1"],
                    "rule_ids": ["NUM-LIFEPATH-001"],
                    "caveat": "The calculation convention is incomplete.",
                    "counter_reading": "Another reduction convention may differ.",
                    "confidence": 0.45,
                    "specificity": 0.45,
                    "barnum_risk": 0.5,
                }
            ]
        }
        unsafe_style_response = {
            "statements": [
                {
                    "index": 0,
                    "statement": "The ledger guarantees exceptional spiritual gifts.",
                }
            ]
        }
        mocked_call = AsyncMock(side_effect=[neutral_response, unsafe_style_response])
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            with patch("backend.app.deepseek.call_json", mocked_call):
                claims, _ = await run_chamber_skill(
                    "numerology",
                    [
                        Fact(
                            id="numerology.life-path-1",
                            label="Life Path",
                            value="7",
                        )
                    ],
                )

        self.assertEqual(claims[0].statement, claims[0].neutral_statement)


if __name__ == "__main__":
    unittest.main()
