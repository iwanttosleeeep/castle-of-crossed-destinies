from datetime import datetime, timezone
from html import escape

from .providers import SYSTEMS


def export_case_markdown(payload: dict) -> str:
    """Render the complete persisted case as portable, inert Markdown."""
    lines = [
        "# The Castle of Crossed Destinies",
        "",
        f"> Case ID: `{safe(payload.get('case_id', 'unknown'))}`",
        "",
        f"- Exported: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Case status: `{safe(payload.get('status', 'unknown'))}`",
        f"- Chambers: {', '.join(SYSTEMS.get(item, item) for item in payload.get('systems', []))}",
        "",
        "> Symbolic interpretation—not proof, diagnosis, or professional advice.",
        "",
        "## I. Confirmed dossier",
        "",
    ]
    for system_id in payload.get("systems", []):
        lines.extend([f"### {safe(SYSTEMS.get(system_id, system_id))}", ""])
        facts = payload.get("confirmed_facts", {}).get(system_id, [])
        if not facts:
            lines.extend(["_No confirmed facts._", ""])
            continue
        for fact in facts:
            lines.append(f"- **{safe(fact.get('label', 'Fact'))}:** {safe(fact.get('value', ''))}")
            if fact.get("source_span"):
                lines.append(f"  - Source: {safe(fact['source_span'])}")
            if fact.get("time_sensitive"):
                lines.append("  - Time-sensitive: yes")
        lines.append("")

    lines.extend(["## II. Independent general reports", ""])
    for system_id in payload.get("systems", []):
        report = payload.get("reports", {}).get(system_id, {})
        lines.extend([f"### {safe(SYSTEMS.get(system_id, system_id))}", ""])
        report_text = report.get("text") or report.get("free_text")
        lines.extend([safe(report_text) if report_text else "_No report was generated._", ""])
        if report.get("warning"):
            lines.extend([f"> Warning: {safe(report['warning'])}", ""])

    lines.extend(["## III. Tribunal", ""])
    tribunal = payload.get("tribunal") or {}
    lines.extend([safe(tribunal.get("summary")) or "_No Tribunal summary was generated._", ""])
    if tribunal.get("disclaimer"):
        lines.extend([f"> {safe(tribunal['disclaimer'])}", ""])

    lines.extend(["## IV. Cross-examinations", ""])
    debates = payload.get("debates", [])
    if not debates:
        lines.extend(["_No hearing questions were submitted._", ""])
    for index, hearing in enumerate(debates, start=1):
        hearing_id = hearing.get("id") or f"hearing-{index}"
        lines.extend(
            [
                f"### {safe(hearing_id)}",
                "",
                "#### Visitor question",
                "",
                safe(hearing.get("question")) or "_Question unavailable._",
                "",
                "#### Independent answers",
                "",
            ]
        )
        append_testimonies(lines, hearing.get("guided_answers", []))
        lines.extend(["#### One rebuttal each", ""])
        append_testimonies(lines, hearing.get("guided_rebuttals", []))
        lines.extend(
            [
                "#### Moderator summary",
                "",
                safe(hearing.get("guided_summary")) or "_Summary unavailable._",
                "",
            ]
        )
        for warning in hearing.get("warnings", []):
            lines.extend([f"> Warning: {safe(warning)}", ""])

    warnings = payload.get("report_warnings", [])
    if warnings:
        lines.extend(["## Appendix: generation warnings", ""])
        lines.extend(f"- {safe(warning)}" for warning in warnings)
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "Exported from **The Castle of Crossed Destinies**.",
            "",
        ]
    )
    return "\n".join(lines)


def append_testimonies(lines: list[str], testimonies: list[dict]) -> None:
    if not testimonies:
        lines.extend(["_No testimony was generated._", ""])
        return
    for testimony in testimonies:
        system_id = testimony.get("system_id", "unknown")
        lines.extend(
            [
                f"##### {safe(SYSTEMS.get(system_id, system_id))}",
                "",
                safe(testimony.get("text")) or "_Empty testimony._",
                "",
            ]
        )


def safe(value: object) -> str:
    if value is None:
        return ""
    return escape(str(value).replace("\r", "").strip(), quote=False)
