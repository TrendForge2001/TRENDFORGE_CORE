from __future__ import annotations

from services.corporate_action_service import CorporateActionService


class WindowProvider:
    def __init__(self):
        self.calls = []

    def corporate_actions(self, symbol=None, days=120):
        self.calls.append((symbol, days))
        return [
            {
                "symbol": symbol,
                "subject": "Dividend",
                "purpose": "DIVIDEND",
                "date": "2026-10-30",
            }
        ]


def test_corporate_action_service_uses_symbol_scoped_provider():
    provider = WindowProvider()
    service = CorporateActionService(
        provider=provider,
        require_symbol=True,
    )

    result = service.get_actions(
        "tcs",
        force_refresh=True,
        days=30,
    )

    assert provider.calls == [("TCS", 30)]
    assert result[0]["symbol"] == "TCS"
    assert result[0]["score"] == 5


def test_corporate_action_cache_is_scoped_by_days():
    provider = WindowProvider()
    service = CorporateActionService(
        provider=provider,
        require_symbol=True,
    )

    service.get_actions("TCS", days=30)
    service.get_actions("TCS", days=30)
    service.get_actions("TCS", days=365)

    assert provider.calls == [
        ("TCS", 30),
        ("TCS", 365),
    ]


class LegacyProvider:
    def corporate_actions(self):
        return [
            {
                "symbol": "INFY",
                "subject": "Bonus",
                "purpose": "BONUS",
                "date": "2026-10-30",
            }
        ]


def test_corporate_action_service_keeps_legacy_provider_compatibility():
    service = CorporateActionService(
        provider=LegacyProvider(),
        require_symbol=True,
    )

    result = service.get_actions(
        "INFY",
        force_refresh=True,
        days=90,
    )

    assert len(result) == 1
    assert result[0]["score"] == 8


def test_corporate_action_service_normalizes_ex_date():
    class ExDateProvider:
        def corporate_actions(self, symbol=None, days=120):
            return [
                {
                    "symbol": symbol,
                    "subject": "Dividend",
                    "purpose": "DIVIDEND",
                    "exDate": "30-Oct-2026",
                }
            ]

    service = CorporateActionService(
        provider=ExDateProvider(),
        require_symbol=True,
    )

    result = service.get_actions(
        "TCS",
        force_refresh=True,
        days=120,
    )

    assert result[0]["date"] == "30-Oct-2026"
