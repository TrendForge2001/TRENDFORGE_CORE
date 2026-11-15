"""The deployed mobile check must follow only the protected owner redirect."""

import pytest

from scripts.public_mobile_location import validate_owner_signin_url

BASE = "https://trendforge.example"
APP = BASE + "/app/paper_session"


@pytest.mark.parametrize("device", ["laptop", "mobile"])
def test_owner_redirect_retains_the_requested_page(device):
    validate_owner_signin_url(
        APP, BASE + f"/owner/{device}?next=%2Fapp%2Fpaper_session"
    )


@pytest.mark.parametrize(
    "location",
    [
        APP,
        "https://other.example/owner/mobile?next=/app/paper_session",
        "http://trendforge.example/owner/mobile?next=/app/paper_session",
        BASE + "/owner/mobile?next=https://other.example",
        BASE + "/owner/mobile?next=/app/reports",
        BASE + "/owner/mobile?next=/app/paper_session&next=/app/reports",
        BASE + "/owner/mobile",
    ],
)
def test_incorrect_or_unprotected_signin_location_is_rejected(location):
    with pytest.raises(AssertionError):
        validate_owner_signin_url(APP, location)
