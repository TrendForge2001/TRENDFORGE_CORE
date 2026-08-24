"""Application lifecycle tests."""
from services.application_service import ApplicationService


class FakeDatabase:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


def test_application_service_starts_and_stops():
    service = ApplicationService(database_factory=FakeDatabase)
    report = service.start()
    assert report["database"]["status"] == "connected"
    db = service.database
    service.stop()
    assert db.closed is True
    assert service.database is None


def test_application_service_isolates_database_failure():
    def failing_database():
        raise RuntimeError("database unavailable")
    report = ApplicationService(database_factory=failing_database).start()
    assert report["status"] == "degraded"
    assert report["database"]["status"] == "unavailable"
