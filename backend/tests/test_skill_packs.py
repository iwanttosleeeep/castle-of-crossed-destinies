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

        self.assertIn("两次生成", warning)
        self.assertEqual(claims, [])
        payload, api_key = mocked_call.await_args_list[0].args
        self.assertEqual(api_key, "visitor-key")
        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(mocked_call.await_count, 2)
        prompt = payload["messages"][0]["content"]
        self.assertIn("FACT DOSSIER", prompt)
        self.assertIn("ADMISSIBLE SUPPORT PAIRS", prompt)
        self.assertIn("WEST-PLANET-SUN", prompt)
        self.assertIn("single explicit fact", prompt)

    async def test_persona_pass_cannot_replace_neutral_testimony(self):
        neutral_response = {
            "claims": [
                {
                    "neutral_statement": "这条太阳事实支持一项边界明确的自我组织解读。",
                    "themes": ["identity_orientation"],
                    "evidence_ids": ["western.sun-1"],
                    "rule_ids": ["WEST-PLANET-SUN"],
                    "caveat": "尚未提供宫位或相位背景。",
                    "counter_reading": "其他盘面因素可能改变其外显方式。",
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
                    "statement": "制图师在这里标下一条路线：这条太阳事实支持一项边界明确的自我组织解读。",
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
            "这条太阳事实支持一项边界明确的自我组织解读。",
        )
        self.assertEqual(
            claims[0].statement,
            "制图师在这里标下一条路线：这条太阳事实支持一项边界明确的自我组织解读。",
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

        self.assertIn("两次生成", warning)
        self.assertEqual(claims, [])
        self.assertEqual(mocked_call.await_count, 2)

    async def test_empty_or_invalid_first_pass_gets_one_grounded_retry(self):
        invalid_response = {
            "claims": [
                {
                    "neutral_statement": "This candidate uses invalid references.",
                    "themes": ["identity"],
                    "evidence_ids": ["western.missing"],
                    "rule_ids": ["WEST-INVENTED-999"],
                }
            ]
        }
        repaired_response = {
            "claims": [
                {
                    "neutral_statement": "太阳这一明确位置可在西占内部谨慎地讨论自我组织与可见性，但不能单独定义整个人格。",
                    "themes": "identity",
                    "support_ids": "s1",
                    "caveat": "缺少宫位与相位上下文。",
                    "counter_reading": "其他行星配置可能改变表达重心。",
                    "confidence": 0.42,
                    "specificity": 0.5,
                    "barnum_risk": 0.45,
                }
            ]
        }
        style_response = {"statements": []}
        mocked_call = AsyncMock(side_effect=[invalid_response, repaired_response, style_response])
        with patch("backend.app.deepseek.call_json", mocked_call):
            claims, warning = await run_chamber_skill(
                "western",
                [Fact(id="western.sun-1", label="Sun", value="Sagittarius")],
                request_api_key="visitor-key",
            )

        self.assertIsNone(warning)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].rule_ids, ["WEST-PLANET-SUN"])
        self.assertEqual(claims[0].themes, ["identity_orientation"])
        self.assertEqual(mocked_call.await_count, 3)

    async def test_persona_rewrite_that_drops_neutral_text_is_rejected(self):
        neutral_response = {
            "claims": [
                {
                    "neutral_statement": "仅凭已提供的数字，可以形成一项谨慎的探索主题。",
                    "themes": ["meaning_imagination"],
                    "evidence_ids": ["numerology.life-path-1"],
                    "rule_ids": ["NUM-LIFEPATH-001"],
                    "caveat": "计算约定尚不完整。",
                    "counter_reading": "另一种缩减约定可能产生不同结果。",
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

    async def test_non_chinese_persona_framing_is_rejected(self):
        neutral_response = {
            "claims": [{
                "neutral_statement": "这项类型事实适合转化为可观察的决策实验。",
                "themes": ["decision_style"],
                "evidence_ids": ["human_design.type-1"],
                "rule_ids": ["HD-TYPE-GENERATOR"],
                "caveat": "这不是科学因果声明。",
                "counter_reading": "一次体验不能代表长期模式。",
                "confidence": 0.6,
                "specificity": 0.6,
                "barnum_risk": 0.3,
            }]
        }
        german_style = {
            "statements": [{
                "index": 0,
                "statement": "Der Mechaniker notiert: 这项类型事实适合转化为可观察的决策实验。",
            }]
        }
        mocked_call = AsyncMock(side_effect=[neutral_response, german_style])
        with patch("backend.app.deepseek.call_json", mocked_call):
            claims, warning = await run_chamber_skill(
                "human_design",
                [Fact(id="human_design.type-1", label="Type", value="Generator")],
                request_api_key="visitor-key",
            )

        self.assertIsNone(warning)
        self.assertEqual(claims[0].statement, claims[0].neutral_statement)

    async def test_non_chinese_claim_is_localized_before_display(self):
        german_claim = {
            "claims": [{
                "neutral_statement": "Der Typ Generator wird hier als beobachtbares Experiment gelesen.",
                "themes": ["decision_style"],
                "evidence_ids": ["human_design.type-1"],
                "rule_ids": ["HD-TYPE-GENERATOR"],
                "caveat": "Dies ist keine wissenschaftliche Kausalbehauptung.",
                "counter_reading": "Eine einzelne Erfahrung belegt kein dauerhaftes Muster.",
                "confidence": 0.6,
                "specificity": 0.6,
                "barnum_risk": 0.3,
            }]
        }
        chinese_translation = {
            "translations": [{
                "index": 0,
                "neutral_statement": "这里把生产者类型理解为一项可观察的实验。",
                "caveat": "这不是科学因果声明。",
                "counter_reading": "一次体验不能证明长期模式。",
            }]
        }
        style_response = {"statements": []}
        mocked_call = AsyncMock(side_effect=[german_claim, chinese_translation, style_response])
        with patch("backend.app.deepseek.call_json", mocked_call):
            claims, warning = await run_chamber_skill(
                "human_design",
                [Fact(id="human_design.type-1", label="Type", value="Generator")],
                request_api_key="visitor-key",
            )

        self.assertIsNone(warning)
        self.assertEqual(claims[0].neutral_statement, "这里把生产者类型理解为一项可观察的实验。")
        self.assertEqual(claims[0].caveat, "这不是科学因果声明。")
        self.assertEqual(mocked_call.await_count, 3)


if __name__ == "__main__":
    unittest.main()
