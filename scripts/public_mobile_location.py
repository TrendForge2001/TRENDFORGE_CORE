"""Validate the owner portal redirect without entering owner credentials."""

from urllib.parse import parse_qs, urlsplit


def validate_owner_signin_url(requested_url: str, resolved_url: str) -> None:
    expected, actual = urlsplit(requested_url), urlsplit(resolved_url)
    if (
        expected.scheme != "https"
        or actual.scheme != "https"
        or actual.netloc != expected.netloc
        or actual.username is not None
        or actual.password is not None
        or actual.fragment
        or actual.path not in {"/owner/laptop", "/owner/mobile"}
        or parse_qs(actual.query) != {"next": [expected.path]}
    ):
        raise AssertionError(
            "Expected a same-origin owner login preserving the app link"
        )
