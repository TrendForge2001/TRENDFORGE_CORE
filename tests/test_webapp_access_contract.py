from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_webapp_uses_separate_access_secret():
    access = (ROOT / "webapp" / "access.py").read_text(
        encoding="utf-8"
    )
    app = (ROOT / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )

    assert "TRENDFORGE_WEBAPP_ACCESS_KEY" in access
    assert "secrets.compare_digest" in access
    assert "render_access_gate" in app
    assert "st.stop()" in app


def test_webapp_access_secret_is_not_backend_admin_key():
    access = (ROOT / "webapp" / "access.py").read_text(
        encoding="utf-8"
    )

    assert "TRENDFORGE_ADMIN_API_KEY" not in access
