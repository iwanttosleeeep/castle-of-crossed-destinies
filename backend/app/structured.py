import json
import re
from collections.abc import Iterator

from .schemas import Fact


MAX_STRUCTURED_FACTS = 80

JSON_SIGNATURES = {
    "bazi": "bazi_chart",
    "ziwei": "twelve_palaces",
    "numerology": "numerology_chart",
    "dreamspell": "kin",
}

PIPE_SIGNATURES = {
    "western": "[PLANET_POSITIONS]",
    "jyotish": "[BODY_POSITIONS]",
}

PIPE_SECTIONS = {
    "western": {"METADATA", "PLANET_POSITIONS", "HOUSE_CUSPS", "ASPECTS"},
    "jyotish": {
        "METADATA",
        "BODY_POSITIONS",
        "D-1 Rasi",
        "D-9 Navamsa",
        "SHADBALA",
        "PLANETARY_STATES_D1",
        "VIMSOTTARI_DASA",
    },
}

TABLE_HEADER_FIRST_CELLS = {
    "object",
    "object_1",
    "cusp",
    "sign",
    "planet",
    "body",
    "major_period",
}


def extract_structured_facts(system_id: str, source_text: str) -> list[Fact]:
    """Parse the project's AI-readable JSON/pipe TXT formats without an LLM."""
    if system_id in JSON_SIGNATURES:
        parsed = parse_json_document(source_text)
        if isinstance(parsed, dict) and JSON_SIGNATURES[system_id] in parsed:
            return json_facts(system_id, parsed)
    signature = PIPE_SIGNATURES.get(system_id)
    if signature and signature in source_text:
        return pipe_facts(system_id, source_text)
    return []


def parse_json_document(source_text: str) -> dict | None:
    start = source_text.find("{")
    end = source_text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(source_text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def json_facts(system_id: str, document: dict) -> list[Fact]:
    facts = []
    for path, value in walk_json(document):
        if len(facts) >= MAX_STRUCTURED_FACTS:
            break
        rendered = render_value(value)
        if not rendered:
            continue
        label = ".".join(path)
        facts.append(make_fact(system_id, len(facts) + 1, label, rendered, f"JSON {label}: {rendered}"))
    return facts


def walk_json(value: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, path + (str(key),))
        return
    if isinstance(value, list):
        if not value:
            return
        if all(not isinstance(item, (dict, list)) for item in value):
            yield path, value
            return
        for index, child in enumerate(value, start=1):
            if isinstance(child, dict):
                identity = next(
                    (child.get(key) for key in ("palace_name", "name", "label", "type") if child.get(key)),
                    index,
                )
                yield path + (str(identity),), child
            else:
                yield from walk_json(child, path + (str(index),))
        return
    if value is not None and value != "":
        yield path, value


def pipe_facts(system_id: str, source_text: str) -> list[Fact]:
    allowed_sections = PIPE_SECTIONS[system_id]
    facts: list[Fact] = []
    section = ""
    headers: list[str] | None = None
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        section_match = re.fullmatch(r"\[([^]]+)\]", line)
        if section_match:
            section = section_match.group(1)
            headers = None
            continue
        if section not in allowed_sections or "|" not in line or len(facts) >= MAX_STRUCTURED_FACTS:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 2 or not any(cells):
            continue
        first = cells[0].lower()
        if first in TABLE_HEADER_FIRST_CELLS:
            headers = cells
            continue
        if headers and len(headers) == len(cells):
            pairs = [(header, cell) for header, cell in zip(headers[1:], cells[1:]) if cell]
            value = "; ".join(f"{header}: {cell}" for header, cell in pairs)
            label = f"{section} · {cells[0]}"
        else:
            label = f"{section} · {cells[0]}"
            value = " | ".join(cell for cell in cells[1:] if cell)
        if value:
            facts.append(make_fact(system_id, len(facts) + 1, label, value, f"[{section}] {line}"))
    return facts


def make_fact(system_id: str, index: int, label: str, value: str, source_span: str) -> Fact:
    return Fact(
        id=f"{system_id}.structured-{index}",
        label=label[:120],
        value=value[:500],
        source_span=source_span[:600],
        extraction_confidence=1.0,
        time_sensitive=system_id not in {"numerology", "dreamspell"},
    )


def render_value(value: object) -> str:
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            rendered = render_value(child)
            if rendered:
                parts.append(f"{key}: {rendered}")
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None and item != "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()
