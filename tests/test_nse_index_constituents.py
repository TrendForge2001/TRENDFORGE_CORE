from __future__ import annotations

from providers.nse_index_constituents import (
    NIFTY500_CSV_URL,
    NSEIndexConstituentProvider,
    parse_nifty500_csv,
)


def _csv(count: int = 500) -> str:
    rows = [
        "Company Name,Industry,Symbol,Series,ISIN Code"
    ]
    for index in range(count):
        rows.append(
            f"Company {index},Industry {index % 10},SYM{index},EQ,"
            f"INE{index:09d}"
        )
    return "\n".join(rows)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {
            "content-type": "text/csv",
            "last-modified": "Fri, 09 Oct 2026 12:00:00 GMT",
            "etag": '"fixture"',
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_parse_nifty500_csv_preserves_source_fields():
    parsed = parse_nifty500_csv(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Alpha Ltd,Finance, alpha ,EQ,INE000000001\n"
        "Beta Ltd,IT,BETA.NS,EQ,INE000000002\n"
    )

    assert [row["symbol"] for row in parsed.members] == [
        "ALPHA",
        "BETA",
    ]
    assert parsed.members[0]["sector"] == "Finance"
    assert parsed.members[0]["isin"] == "INE000000001"
    assert parsed.invalid_rows == 0
    assert parsed.duplicate_symbols == ()


def test_parse_nifty500_csv_reports_duplicates_without_padding():
    parsed = parse_nifty500_csv(
        "Company Name,Industry,Symbol\n"
        "Alpha,Finance,AAA\n"
        "Alpha Duplicate,Finance,AAA\n"
        "Missing,Finance,\n"
    )

    assert len(parsed.members) == 1
    assert parsed.invalid_rows == 1
    assert parsed.duplicate_symbols == ("AAA",)


def test_official_provider_accepts_nominal_500_unique_securities():
    session = FakeSession(FakeResponse(_csv(500)))
    provider = NSEIndexConstituentProvider(session=session)

    payload = provider.nifty500()

    assert payload["source"] == "NSE_NIFTY500_CSV"
    assert payload["source_url"] == NIFTY500_CSV_URL
    assert payload["count"] == 500
    assert payload["security_count"] == 500
    assert payload["nominal_company_count"] == 500
    assert payload["expected_count"] == 500
    assert payload["count_variance"] == 0
    assert payload["invalid_rows"] == 0
    assert payload["duplicate_symbols"] == []
    assert len(payload["members"]) == 500
    assert provider.health()["status"] == "runtime_verified"


def test_official_provider_accepts_501_source_securities_without_padding():
    session = FakeSession(FakeResponse(_csv(501)))
    provider = NSEIndexConstituentProvider(session=session)

    payload = provider.nifty500()

    assert payload["count"] == 501
    assert payload["security_count"] == 501
    assert payload["nominal_company_count"] == 500
    assert payload["count_variance"] == 1
    assert len(payload["members"]) == 501
    assert provider.health()["status"] == "runtime_verified"
    assert provider.health()["count_variance"] == 1


def test_official_provider_rejects_partial_constituent_download():
    session = FakeSession(FakeResponse(_csv(499)))
    provider = NSEIndexConstituentProvider(session=session)

    try:
        provider.nifty500()
    except RuntimeError as exc:
        assert "minimum 500, received 499" in str(exc)
    else:
        raise AssertionError("partial NIFTY 500 source must fail")

    health = provider.health()
    assert health["status"] == "degraded"
    assert "499" in health["last_error"]


def test_official_provider_reuses_verified_cache():
    session = FakeSession(FakeResponse(_csv(500)))
    provider = NSEIndexConstituentProvider(
        session=session,
        cache_ttl=3600,
    )

    first = provider.nifty500()
    second = provider.nifty500()

    assert first["count"] == second["count"] == 500
    assert len(session.calls) == 1


def test_official_provider_rejects_implausibly_large_source():
    session = FakeSession(FakeResponse(_csv(526)))
    provider = NSEIndexConstituentProvider(session=session)

    try:
        provider.nifty500()
    except RuntimeError as exc:
        assert "maximum 525, received 526" in str(exc)
    else:
        raise AssertionError("implausibly large NIFTY 500 source must fail")

    assert provider.health()["status"] == "degraded"
