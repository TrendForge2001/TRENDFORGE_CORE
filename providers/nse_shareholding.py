"""Parse official NSE shareholding-pattern XBRL into Big Shark evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping
from xml.etree import ElementTree as ET


CATEGORY_MEMBERS = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroupMember",
    "public": "PublicShareholdingMember",
    "fii": "InstitutionsForeignMember",
    "dii": "InstitutionsDomesticMember",
    "noninst": "NonInstitutionsMember",
}

PERCENT_FACT = "ShareholdingAsAPercentageOfTotalNumberOfShares"


def _local_name(value: str) -> str:
    text = str(value or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _scale_percentages(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}

    promoter = values.get("promoter")
    public = values.get("public")
    reference: float | None = None

    if promoter is not None and public is not None:
        reference = promoter + public
    else:
        non_null = [abs(value) for value in values.values()]
        if non_null:
            reference = max(non_null)

    scale = 1.0
    if reference is not None:
        if reference > 1000:
            scale = 0.01
        elif 0 < reference < 2:
            scale = 100.0

    return {
        key: round(value * scale, 4)
        for key, value in values.items()
    }


def parse_shareholding_xbrl(xml_text: str) -> dict[str, float]:
    """Extract NSE aggregate promoter/FII/DII/public percentages.

    The parser is namespace-prefix agnostic and intentionally keeps only
    aggregate category contexts. It does not infer investor classifications.
    """

    text = str(xml_text or "").strip()
    if not text:
        return {}

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    context_members: dict[str, set[str]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "context":
            continue

        context_id = str(element.attrib.get("id") or "").strip()
        if not context_id:
            continue

        members: set[str] = set()
        for child in element.iter():
            if _local_name(child.tag) != "explicitMember":
                continue
            member = _local_name(child.text or "")
            if member:
                members.add(member)
        context_members[context_id] = members

    candidates: dict[str, list[tuple[int, float]]] = {
        key: [] for key in CATEGORY_MEMBERS
    }

    for element in root.iter():
        if _local_name(element.tag) != PERCENT_FACT:
            continue

        value = _number(element.text)
        if value is None:
            continue

        context_ref = str(
            element.attrib.get("contextRef")
            or element.attrib.get("contextref")
            or ""
        ).strip()
        members = context_members.get(context_ref, set())
        if not members:
            continue

        # Aggregate rollups normally have one or two explicit dimensions.
        # Deep sub-category contexts are ignored to avoid double counting.
        if len(members) > 2:
            continue

        for category, member_name in CATEGORY_MEMBERS.items():
            if member_name in members:
                candidates[category].append((len(members), value))

    values: dict[str, float] = {}
    for category, rows in candidates.items():
        if not rows:
            continue
        rows.sort(key=lambda item: item[0])
        values[category] = rows[0][1]

    return _scale_percentages(values)


def _filing_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "rows", "results", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [
                    row for row in nested
                    if isinstance(row, Mapping)
                ]
    return []


def _filing_date(row: Mapping[str, Any]) -> datetime | None:
    value = (
        row.get("date")
        or row.get("filingDate")
        or row.get("filing_date")
        or row.get("submissionDate")
        or row.get("submission_date")
        or row.get("periodEndDate")
    )
    if value in (None, ""):
        return None

    text = str(value).strip()
    formats = (
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _xbrl_url(row: Mapping[str, Any]) -> str | None:
    for key in (
        "xbrl",
        "xbrlUrl",
        "xbrl_url",
        "filePath",
        "file_path",
        "attachment",
        "url",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            if "xml" in candidate.lower() or "xbrl" in candidate.lower():
                return candidate

    for value in row.values():
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if candidate.lower().startswith(("http://", "https://")) and (
            "xml" in candidate.lower() or "xbrl" in candidate.lower()
        ):
            return candidate

    return None


def build_shareholding_evidence(
    filings: Any,
    fetch_document: Callable[[str], str],
    *,
    max_filings: int = 5,
) -> tuple[dict[str, Any], list[str]]:
    """Build latest ownership + QoQ deltas from official SHP filings."""

    rows = _filing_rows(filings)
    rows.sort(
        key=lambda row: _filing_date(row) or datetime.min,
        reverse=True,
    )

    parsed: list[tuple[Mapping[str, Any], dict[str, float]]] = []
    errors: list[str] = []

    for row in rows[: max(1, int(max_filings))]:
        url = _xbrl_url(row)
        if not url:
            continue

        try:
            xml_text = fetch_document(url)
            facts = parse_shareholding_xbrl(xml_text)
        except Exception as exc:
            errors.append(f"xbrl:{exc}")
            continue

        if facts:
            parsed.append((row, facts))
        if len(parsed) >= 2:
            break

    if not parsed:
        return {}, errors

    latest_row, latest = parsed[0]
    previous_row, previous = (
        parsed[1] if len(parsed) > 1 else ({}, {})
    )

    latest_date = _filing_date(latest_row)
    previous_date = _filing_date(previous_row)

    snapshot = {
        key: latest.get(key)
        for key in ("promoter", "fii", "dii", "public", "noninst")
        if latest.get(key) is not None
    }
    snapshot.update(
        {
            "source": "NSE_SHP_XBRL",
            "as_of": latest_date.date().isoformat()
            if latest_date is not None
            else str(latest_row.get("date") or ""),
        }
    )

    changes: list[dict[str, Any]] = []
    labels = {
        "promoter": "PROMOTER",
        "fii": "FII",
        "dii": "DII",
    }
    for key, category in labels.items():
        current = latest.get(key)
        prior = previous.get(key)
        if current is None or prior is None:
            continue

        changes.append(
            {
                "name": f"NSE {category} aggregate",
                "category": category,
                "holding": current,
                "previous_holding": prior,
                "change": round(current - prior, 4),
                "date": latest_date.date().isoformat()
                if latest_date is not None
                else None,
                "previous_date": previous_date.date().isoformat()
                if previous_date is not None
                else None,
                "source": "NSE_SHP_XBRL",
            }
        )

    evidence: dict[str, Any] = {
        "shareholding_snapshot": snapshot,
        "holding_changes": changes,
    }

    promoter_current = latest.get("promoter")
    promoter_previous = previous.get("promoter")
    if promoter_current is not None:
        evidence["promoter"] = {
            "current": promoter_current,
            "previous": promoter_previous,
            "holding": promoter_current,
            "previous_holding": promoter_previous,
            "source": "NSE_SHP_XBRL",
        }

    evidence["_meta"] = {
        "source": "NSE_SHP_XBRL",
        "filings_parsed": len(parsed),
        "latest_as_of": snapshot.get("as_of"),
    }
    return evidence, errors


__all__ = [
    "CATEGORY_MEMBERS",
    "PERCENT_FACT",
    "build_shareholding_evidence",
    "parse_shareholding_xbrl",
]
