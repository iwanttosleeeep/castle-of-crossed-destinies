import json
import re
import unittest
from pathlib import Path

from backend.app.providers import SYSTEMS


ROOT = Path(__file__).resolve().parents[2]
RULE_PATTERN = re.compile(r"\b(?:BAZI|ZIWEI|WEST|JYOTISH|NUM|HD|DREAM)-[A-Z0-9-]+\b")


class ArchivedSkillPackTests(unittest.TestCase):
    def test_archived_full_packs_remain_complete(self):
        for system_id in SYSTEMS:
            root = ROOT / "skills" / f"{system_id.replace('_', '-')}-chamber"
            with self.subTest(system_id=system_id):
                for relative in ("SKILL.md", "references/knowledge.md", "references/persona.md"):
                    self.assertGreater((root / relative).stat().st_size, 100)
                self.assertTrue(RULE_PATTERN.findall((root / "references/knowledge.md").read_text()))

    def test_lightweight_personas_cover_every_system(self):
        root = ROOT / "skills" / "guided-chamber-reading"
        personas = json.loads((root / "references" / "personas.json").read_text())
        self.assertEqual(set(personas), set(SYSTEMS))
        skill = (root / "SKILL.md").read_text()
        self.assertIn("Do not invent", skill)
        self.assertIn("Do not output JSON", skill)


if __name__ == "__main__":
    unittest.main()
