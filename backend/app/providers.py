import re
from .schemas import BirthProfile, Chamber, Fact


SYSTEMS = {
    "bazi": "BaZi 八字",
    "ziwei": "Zi Wei Dou Shu 紫微斗数",
    "western": "Western Astrology 西占",
    "jyotish": "Jyotish 印占",
    "numerology": "Numerology 数秘",
    "human_design": "Human Design 人类图",
    "dreamspell": "Dreamspell",
}


def parse_facts(text: str) -> dict[str, list[Fact]]:
    """Parse user-held chart facts, one per line: system | label | value.

    This intentionally does not calculate charts or call any external service.
    """
    result = {system_id: [] for system_id in SYSTEMS}
    for number, line in enumerate(text.splitlines(), start=1):
        parts = [part.strip() for part in line.split("|", maxsplit=2)]
        if len(parts) != 3 or parts[0] not in SYSTEMS or not parts[1] or not parts[2]:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", parts[1].lower()).strip("-") or f"fact-{number}"
        result[parts[0]].append(Fact(id=f"{parts[0]}.{slug}-{number}", label=parts[1], value=parts[2], time_sensitive=parts[0] not in {"numerology", "dreamspell"}))
    return result


def generate_chamber(system_id: str, profile: BirthProfile, supplied_facts: list[Fact]) -> Chamber:
    if supplied_facts:
        return Chamber(system_id=system_id, display_name=SYSTEMS[system_id], source_type="user_dossier", skill_path=f"skills/{system_id.replace('_', '-')}-chamber", facts=supplied_facts)
    return Chamber(system_id=system_id, display_name=SYSTEMS[system_id], source_type="unverified", skill_path=f"skills/{system_id.replace('_', '-')}-chamber", facts=[], warning="尚未提供可核验盘面事实；此 chamber 不会产生解释性结论。")
