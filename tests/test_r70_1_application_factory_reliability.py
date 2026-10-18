from __future__ import annotations

from core.application_factory import ApplicationFactory
from core.database import initialize_database


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


def test_application_factory_reuses_operations_repository_for_reliability(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "trendforge.db"
    monkeypatch.setenv(
        "DATABASE_PATH",
        str(database_path),
    )
    initialize_database(str(database_path))

    factory = ApplicationFactory(
        kite=FakeProvider(),
        yahoo=FakeProvider(),
    )
    operations = factory.market_day_operations_service()
    reliability = factory.operations_reliability_service()

    assert reliability.operations_service is operations
    assert reliability.repository is operations.repository
    assert (
        reliability.notification_center
        is factory.notification_center_service()
    )
    assert reliability.VERSION == "R70.1"

    factory.notification_center_service().close()
    operations.close()
