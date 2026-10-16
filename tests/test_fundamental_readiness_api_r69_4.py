from fastapi.testclient import TestClient

from api.app import create_app


class FakeCoverage:
    def __init__(self):
        self.calls = []

    def report(self, *, refresh_universe=False, incomplete_only=False, limit=5000):
        self.calls.append(
            {
                "refresh_universe": refresh_universe,
                "incomplete_only": incomplete_only,
                "limit": limit,
            }
        )
        return {
            "version": "R69.4",
            "universe": "NIFTY 500",
            "tradable_symbols": 500,
            "database_records": 11,
            "database_coverage_pct": 2.2,
            "scoring_ready_records": 2,
            "scoring_readiness_pct": 0.4,
            "quality_pass_records": 1,
            "stale_records": 0,
            "missing_database_records": 489,
            "readiness_counts": {
                "DATA_INCOMPLETE": 9,
                "MISSING": 489,
                "READY_PASS": 1,
                "READY_FAIL_QUALITY": 1,
            },
            "field_coverage": {
                "roce": {
                    "present": 11,
                    "missing": 489,
                    "invalid": 0,
                    "coverage_pct": 2.2,
                }
            },
            "required_fields": ["roce"],
            "returned": 1,
            "records": [
                {
                    "symbol": "ABC",
                    "status": "DATA_INCOMPLETE",
                    "missing": ["roe"],
                }
            ],
        }


class Factory:
    def __init__(self):
        self.coverage = FakeCoverage()

    def fundamental_coverage_service(self):
        return self.coverage


def test_fundamental_readiness_endpoint_exposes_r69_4_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.get(
        "/fundamentals/readiness",
        params={
            "refresh_universe": "true",
            "incomplete_only": "true",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "R69.4"
    assert body["tradable_symbols"] == 500
    assert body["database_records"] == 11
    assert body["missing_database_records"] == 489
    assert body["readiness_counts"]["MISSING"] == 489
    assert body["field_coverage"]["roce"]["coverage_pct"] == 2.2
    assert factory.coverage.calls == [
        {
            "refresh_universe": True,
            "incomplete_only": True,
            "limit": 100,
        }
    ]


def test_fundamental_readiness_route_is_not_captured_as_symbol():
    response = TestClient(create_app(Factory())).get(
        "/fundamentals/readiness"
    )
    assert response.status_code == 200
    assert response.json()["version"] == "R69.4"
