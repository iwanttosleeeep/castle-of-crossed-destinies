import unittest

from backend.app.structured import extract_structured_facts


class StructuredExtractionTests(unittest.TestCase):
    def test_western_pipe_table_is_parsed_without_model(self):
        text = """[METADATA]
house_system | Placidus
[PLANET_POSITIONS]
object | sign | longitude | house | motion
Sun | Sagittarius | 15°24'25\" | 10 | direct
[HOUSE_CUSPS]
cusp | sign | longitude
Ascendant | Aquarius | 28°47'59\"
[ASPECTS]
object_1 | aspect | object_2 | signed_orb | phase
Moon | sextile | Sun | +4°44' | applying
"""
        facts = extract_structured_facts("western", text)

        self.assertEqual(len(facts), 4)
        self.assertEqual(facts[1].label, "PLANET_POSITIONS · Sun")
        self.assertIn("sign: Sagittarius", facts[1].value)
        self.assertEqual(facts[1].extraction_confidence, 1.0)

    def test_jyotish_uses_priority_sections_and_ignores_bulk_tables(self):
        text = """[BODY_POSITIONS]
object | longitude | motion | chara_karaka | nakshatra | pada | rasi | navamsa
Lagna | 4° Aquarius | direct | | Dhanishtha | 4 | Aquarius | Scorpio
[DIVISIONAL_CHARTS]
[D-1 Rasi]
sign | raw_tokens | expanded_placements
Scorpio | Me; Su | Mercury; Sun
[ASHTOTTARI_DASA]
major_period | subperiod | start_date
Mars | Mars | 2003-12-03
[VIMSOTTARI_DASA]
major_period | subperiod | start_date
Rahu | Mercury | 2024-10-24
"""
        facts = extract_structured_facts("jyotish", text)

        self.assertEqual(len(facts), 3)
        self.assertTrue(any(fact.label == "D-1 Rasi · Scorpio" for fact in facts))
        self.assertFalse(any("ASHTOTTARI" in fact.label for fact in facts))

    def test_ziwei_palaces_are_grouped_instead_of_truncated_field_by_field(self):
        text = """ZiWeiDouShu
{"basic_info":{"chart_type":"飞星盘","life_master":"武曲"},"twelve_palaces":[
{"palace_name":"命宫","stem_branch":"己巳","main_stars":["武曲[平]","破军[平]"],"decade_limit":"3~12虚岁"},
{"palace_name":"夫妻宫","stem_branch":"丁卯","main_stars":[],"decade_limit":"23~32虚岁"}
]}"""
        facts = extract_structured_facts("ziwei", text)

        self.assertEqual(len(facts), 4)
        palace = next(fact for fact in facts if fact.label == "twelve_palaces.命宫")
        self.assertIn("武曲[平]", palace.value)
        self.assertIn("decade_limit", palace.value)

    def test_wrong_system_signature_does_not_claim_structured_success(self):
        self.assertEqual(extract_structured_facts("western", '{"kin":133}'), [])


if __name__ == "__main__":
    unittest.main()
