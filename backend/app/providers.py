import os
from collections.abc import Mapping
import httpx
from .schemas import BirthProfile, Chamber, Fact

SYSTEMS = {
    "western": ("Western Astrology", "WESTERN"),
    "jyotish": ("Jyotish", "JYOTISH"),
    "bazi": ("BaZi 八字", "BAZI"),
    "human_design": ("Human Design", "HUMAN_DESIGN"),
}


def demo_facts(system_id: str) -> list[Fact]:
    data = {
        "western": [("sun", "Sun sign", "Aries"), ("mercury", "Mercury", "9th house")],
        "jyotish": [("lagna", "Lagna", "Sagittarius"), ("jupiter", "Jupiter", "Angular placement")],
        "bazi": [("day_master", "Day Master", "Yang Wood"), ("element", "Five elements", "Wood / Fire emphasis")],
        "human_design": [("type", "Type", "Generator"), ("authority", "Authority", "Sacral")],
    }[system_id]
    return [Fact(id=f"{system_id}.{key}", label=label, value=value, time_sensitive=system_id != "bazi") for key, label, value in data]


async def generate_chart(system_id: str, profile: BirthProfile) -> Chamber:
    """Provider seam: normalise a configured vendor response into a Chamber.

    Vendor-specific field extraction belongs here, never in tribunal code.
    """
    name, prefix = SYSTEMS[system_id]
    url, key = os.getenv(f"{prefix}_API_URL"), os.getenv(f"{prefix}_API_KEY")
    if not (url and key):
        return Chamber(system_id=system_id, display_name=name, source_type="demo", provider="Demo adapter", facts=demo_facts(system_id), warning="未配置 API 密钥：此 chamber 使用演示数据。")
    payload = {"name": profile.display_name, "date": profile.birth_date.isoformat(), "time": profile.birth_time.isoformat() if profile.birth_time else None, "place": profile.birthplace_text, "timezone": profile.timezone_name}
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        body: Mapping = response.json()
    # API adapters should replace these generic values with supplier-specific fact paths.
    facts = [Fact(id=f"{system_id}.provider.response", label="Provider response received", value=str(bool(body)), time_sensitive=system_id != "bazi")]
    return Chamber(system_id=system_id, display_name=name, source_type="api", provider=url, facts=facts)
