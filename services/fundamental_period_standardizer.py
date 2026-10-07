"""Standardize period/source metadata for fundamental completion evidence."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping

import pandas as pd


class FundamentalPeriodStandardizer:
    FY_PATTERN = re.compile(r"^FY(\d{4})$", re.IGNORECASE)
    EPS_METHOD = "3Y_CAGR"
    EPS_STATUSES = {"VALID", "N/M"}
    EPS_NM_REASONS = {
        "NEGATIVE_BASE",
        "ZERO_BASE",
        "INSUFFICIENT_HISTORY",
        "OTHER",
    }
    SOURCE_TYPES = {
        "ANNUAL_REPORT",
        "EXCHANGE_FILING",
        "COMPANY_FILING",
        "SCREENER",
        "TIJORI",
        "OTHER",
    }

    GLOBAL_SOURCE_TYPE_ALIASES = (
        "completion source type",
        "source type",
    )
    GLOBAL_SOURCE_ALIASES = ("completion source", "source", "data source")
    GLOBAL_SOURCE_REF_ALIASES = (
        "completion source ref",
        "source ref",
        "source url",
        "reference",
    )
    GLOBAL_AS_OF_ALIASES = (
        "completion as of",
        "as of",
        "as_of",
        "completion date",
    )

    FIELD_SOURCE_TYPE_COLUMN = {
        "roe": "ROE Source Type",
        "eps_growth": "EPS Growth Source Type",
        "promoter_holding": "Promoter Holding Source Type",
        "pledged": "Pledged Source Type",
    }
    FIELD_SOURCE_COLUMN = {
        "roe": "ROE Source",
        "eps_growth": "EPS Growth Source",
        "promoter_holding": "Promoter Holding Source",
        "pledged": "Pledged Source",
    }
    FIELD_SOURCE_REF_COLUMN = {
        "roe": "ROE Source Ref",
        "eps_growth": "EPS Growth Source Ref",
        "promoter_holding": "Promoter Holding Source Ref",
        "pledged": "Pledged Source Ref",
    }
    FIELD_AS_OF_COLUMN = {
        "promoter_holding": "Promoter Holding As Of",
        "pledged": "Pledged As Of",
    }

    @staticmethod
    def normalize_column(value: Any) -> str:
        return " ".join(
            str(value or "")
            .strip()
            .lower()
            .replace("_", " ")
            .replace("%", " %")
            .split()
        )

    @classmethod
    def lookup(cls, payload: Mapping[str, Any], *aliases: str) -> Any:
        normalized = {
            cls.normalize_column(key): key
            for key in payload
        }
        for alias in aliases:
            key = normalized.get(cls.normalize_column(alias))
            if key is None:
                continue
            value = payload.get(key)
            if pd.isna(value):
                return None
            if isinstance(value, str) and not value.strip():
                return None
            return value
        return None

    @classmethod
    def fy(cls, value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip().upper()
        match = cls.FY_PATTERN.fullmatch(text)
        return f"FY{match.group(1)}" if match else None

    @staticmethod
    def date_value(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = pd.to_datetime(value).to_pydatetime()
            except Exception:
                return None
        return parsed.date().isoformat()

    @classmethod
    def metadata_columns_for(cls, missing_fields: list[str]) -> list[str]:
        columns = [
            "Completion Source Type",
            "Completion Source",
            "Completion Source Ref",
            "Completion As Of",
        ]
        missing = set(missing_fields)
        if "roe" in missing:
            columns += [
                "ROE Period",
                "ROE Source Type",
                "ROE Source",
                "ROE Source Ref",
            ]
        if "eps_growth" in missing:
            columns += [
                "EPS Growth Status",
                "EPS Growth Method",
                "EPS Start Period",
                "EPS End Period",
                "EPS Growth Reason",
                "EPS Growth Source Type",
                "EPS Growth Source",
                "EPS Growth Source Ref",
            ]
        if "promoter_holding" in missing:
            columns += [
                "Promoter Holding As Of",
                "Promoter Holding Source Type",
                "Promoter Holding Source",
                "Promoter Holding Source Ref",
            ]
        if "pledged" in missing:
            columns += [
                "Pledged As Of",
                "Pledged Source Type",
                "Pledged Source",
                "Pledged Source Ref",
            ]
        return columns

    def _source(
        self,
        payload: Mapping[str, Any],
        field: str,
        fallback_source: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        specific_type = self.FIELD_SOURCE_TYPE_COLUMN.get(field)
        specific = self.FIELD_SOURCE_COLUMN.get(field)
        specific_ref = self.FIELD_SOURCE_REF_COLUMN.get(field)
        source_type = (
            self.lookup(payload, specific_type) if specific_type else None
        ) or self.lookup(payload, *self.GLOBAL_SOURCE_TYPE_ALIASES)
        source = (
            self.lookup(payload, specific) if specific else None
        ) or self.lookup(payload, *self.GLOBAL_SOURCE_ALIASES) or fallback_source
        source_ref = (
            self.lookup(payload, specific_ref) if specific_ref else None
        ) or self.lookup(payload, *self.GLOBAL_SOURCE_REF_ALIASES)
        type_text = str(source_type).strip().upper() if source_type is not None else None
        source_text = str(source).strip() if source is not None else None
        ref_text = str(source_ref).strip() if source_ref is not None else None
        return type_text or None, source_text or None, ref_text or None

    def _as_of(
        self,
        payload: Mapping[str, Any],
        field: str,
        fallback_as_of: str | None,
    ) -> str | None:
        specific = self.FIELD_AS_OF_COLUMN.get(field)
        raw = (
            self.lookup(payload, specific) if specific else None
        ) or self.lookup(payload, *self.GLOBAL_AS_OF_ALIASES) or fallback_as_of
        return self.date_value(raw)

    def validate(
        self,
        *,
        symbol: str,
        payload: Mapping[str, Any],
        missing_fields: list[str],
        numeric_values: Mapping[str, float],
        fallback_source: str | None = None,
        fallback_as_of: str | None = None,
        source_file: str | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        evidence: list[dict[str, Any]] = []
        non_numeric: list[str] = []
        missing = set(missing_fields)

        def base(field: str, value: float | None, status: str) -> dict[str, Any] | None:
            source_type, source, source_ref = self._source(
                payload,
                field,
                fallback_source,
            )
            as_of = self._as_of(payload, field, fallback_as_of)
            if not source_type:
                errors.append(f"{field}: source type is required")
            elif source_type not in self.SOURCE_TYPES:
                errors.append(
                    f"{field}: source type must be one of "
                    + ", ".join(sorted(self.SOURCE_TYPES))
                )
            if not source:
                errors.append(f"{field}: source is required")
            if not source_ref:
                errors.append(f"{field}: source reference is required")
            if not as_of:
                errors.append(f"{field}: valid as-of date is required")
            if (
                not source_type
                or source_type not in self.SOURCE_TYPES
                or not source
                or not source_ref
                or not as_of
            ):
                return None
            return {
                "symbol": symbol,
                "field": field,
                "value": value,
                "value_status": status,
                "source_type": source_type,
                "source": source,
                "source_ref": source_ref,
                "as_of": as_of,
                "source_file": source_file,
            }

        for field, value in numeric_values.items():
            if field not in missing:
                continue

            if field == "roe":
                period = self.fy(self.lookup(payload, "ROE Period"))
                if not period:
                    errors.append("roe: ROE Period must be FY####")
                    continue
                item = base(field, value, "VALID")
                if item:
                    item.update(
                        {
                            "period_type": "ANNUAL_FY",
                            "period_label": period,
                            "methodology": "REPORTED_ANNUAL",
                        }
                    )
                    evidence.append(item)
                continue

            if field == "eps_growth":
                status = str(
                    self.lookup(payload, "EPS Growth Status") or "VALID"
                ).strip().upper()
                method = str(
                    self.lookup(payload, "EPS Growth Method") or ""
                ).strip().upper()
                start = self.fy(self.lookup(payload, "EPS Start Period"))
                end = self.fy(self.lookup(payload, "EPS End Period"))
                if status != "VALID":
                    errors.append("eps_growth: numeric value requires EPS Growth Status=VALID")
                if method != self.EPS_METHOD:
                    errors.append("eps_growth: EPS Growth Method must be 3Y_CAGR")
                if not start or not end:
                    errors.append("eps_growth: EPS Start/End Period must be FY####")
                elif int(end[2:]) - int(start[2:]) != 3:
                    errors.append("eps_growth: EPS period span must be exactly 3 fiscal years")
                if status != "VALID" or method != self.EPS_METHOD or not start or not end:
                    continue
                if int(end[2:]) - int(start[2:]) != 3:
                    continue
                item = base(field, value, "VALID")
                if item:
                    item.update(
                        {
                            "period_type": "CAGR",
                            "period_label": f"{start}-{end}",
                            "period_start": start,
                            "period_end": end,
                            "methodology": self.EPS_METHOD,
                        }
                    )
                    evidence.append(item)
                continue

            if field in {"promoter_holding", "pledged"}:
                item = base(field, value, "VALID")
                if item:
                    item.update(
                        {
                            "period_type": "POINT_IN_TIME",
                            "period_label": item["as_of"],
                            "methodology": "REPORTED_SHAREHOLDING",
                        }
                    )
                    evidence.append(item)
                continue

            item = base(field, value, "VALID")
            if item:
                item.update(
                    {
                        "period_type": "AS_REPORTED",
                        "period_label": item["as_of"],
                        "methodology": "REPORTED",
                    }
                )
                evidence.append(item)

        if "eps_growth" in missing and "eps_growth" not in numeric_values:
            status_raw = self.lookup(payload, "EPS Growth Status")
            if status_raw is not None:
                status = str(status_raw).strip().upper()
                if status not in self.EPS_STATUSES:
                    errors.append("eps_growth: EPS Growth Status must be VALID or N/M")
                elif status == "N/M":
                    method = str(
                        self.lookup(payload, "EPS Growth Method") or ""
                    ).strip().upper()
                    start = self.fy(self.lookup(payload, "EPS Start Period"))
                    end = self.fy(self.lookup(payload, "EPS End Period"))
                    reason = str(
                        self.lookup(payload, "EPS Growth Reason") or ""
                    ).strip().upper()
                    if method != self.EPS_METHOD:
                        errors.append("eps_growth: N/M evidence still requires 3Y_CAGR method")
                    if not start or not end:
                        errors.append("eps_growth: N/M requires EPS Start/End Period FY####")
                    elif int(end[2:]) - int(start[2:]) != 3:
                        errors.append("eps_growth: N/M EPS period span must be 3 fiscal years")
                    if reason not in self.EPS_NM_REASONS:
                        errors.append(
                            "eps_growth: N/M reason must be NEGATIVE_BASE, ZERO_BASE, "
                            "INSUFFICIENT_HISTORY, or OTHER"
                        )
                    if (
                        method == self.EPS_METHOD
                        and start
                        and end
                        and int(end[2:]) - int(start[2:]) == 3
                        and reason in self.EPS_NM_REASONS
                    ):
                        item = base(field, None, "N/M")
                        if item:
                            item.update(
                                {
                                    "period_type": "CAGR",
                                    "period_label": f"{start}-{end}",
                                    "period_start": start,
                                    "period_end": end,
                                    "methodology": self.EPS_METHOD,
                                    "reason": reason,
                                }
                            )
                            evidence.append(item)
                            non_numeric.append("eps_growth")

        return {
            "evidence": evidence,
            "errors": list(dict.fromkeys(errors)),
            "non_numeric_fields": non_numeric,
        }


__all__ = ["FundamentalPeriodStandardizer"]
