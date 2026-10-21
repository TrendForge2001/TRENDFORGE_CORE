from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_webapp_render_blueprint_is_isolated_from_backend():
    backend = (ROOT / "render.yaml").read_text(
        encoding="utf-8"
    )
    frontend = (
        ROOT / "deploy" / "render-webapp.yaml"
    ).read_text(encoding="utf-8")

    assert "name: trendforge-core" in backend
    assert (
        "startCommand: uvicorn start:app "
        "--host 0.0.0.0 --port $PORT"
    ) in backend
    assert "healthCheckPath: /livez" in backend

    assert "name: trendforge-webapp" in frontend
    assert (
        "python -m pip install -r webapp/requirements.txt"
        in frontend
    )
    assert "python -m streamlit run webapp/app.py" in frontend
    assert "healthCheckPath: /_stcore/health" in frontend


def test_webapp_blueprint_requires_separate_access_secret():
    frontend = (
        ROOT / "deploy" / "render-webapp.yaml"
    ).read_text(encoding="utf-8")

    assert "TRENDFORGE_API_URL" in frontend
    assert "TRENDFORGE_ADMIN_API_KEY" in frontend
    assert "TRENDFORGE_WEBAPP_ACCESS_KEY" in frontend
    assert frontend.count("sync: false") >= 3
