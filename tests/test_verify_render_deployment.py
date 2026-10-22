from __future__ import annotations

import io
import json
from urllib.error import HTTPError

from scripts.verify_render_deployment import probe_once, wait_for_deployment


SHA = "a" * 40


class Response(io.BytesIO):
    status = 200


def opener_with_sha(sha):
    def opener(request, **kwargs):
        assert request.method == "GET"
        assert "Authorization" not in request.headers
        return Response(json.dumps({"deployment": {"render_git_commit": sha}}).encode())

    return opener


def test_exact_sha_and_all_pages_are_required():
    assert probe_once("https://example.com", SHA, opener=opener_with_sha(SHA))[
        "verified"
    ]
    assert not probe_once("https://example.com", SHA, opener=opener_with_sha("b" * 40))[
        "verified"
    ]


def test_missing_ui_does_not_pass_with_matching_sha():
    def opener(request, **kwargs):
        if request.full_url.endswith("/app/"):
            raise HTTPError(request.full_url, 503, "unavailable", None, None)
        return opener_with_sha(SHA)(request)

    result = probe_once("https://example.com", SHA, opener=opener)
    assert result["ui"] == 503
    assert result["verified"] is False


def test_timeout_is_explicit_and_does_not_print_response_secrets(capsys):
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    def opener(request, **kwargs):
        return Response(json.dumps({"secret": "secret-sentinel"}).encode())

    assert not wait_for_deployment(
        "https://example.com",
        SHA,
        timeout=1,
        interval=0.5,
        opener=opener,
        clock=lambda: now[0],
        sleep=sleep,
    )
    output = capsys.readouterr().out
    assert "::error" in output
    assert "secret-sentinel" not in output


def test_delayed_deployment_eventually_passes(capsys):
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    def opener(request, **kwargs):
        sha = SHA if now[0] > 0 else "b" * 40
        return opener_with_sha(sha)(request)

    assert wait_for_deployment(
        "https://example.com",
        SHA,
        timeout=2,
        interval=0.5,
        opener=opener,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert "::notice" in capsys.readouterr().out
