from scripts.r7257_deployment_preflight import inspect


def _fixture(root, *, healthy=True):
    (root / "render.yaml").write_text(
        "healthCheckPath: /livez\nbuildCommand: pip install -r requirements-production.lock\n"
        "startCommand: uvicorn start:app --host 0.0.0.0 --port $PORT\n"
    )
    (root / "requirements-production.lock").write_text("fastapi==0.1\n")
    (root / ".python-version").write_text("3.12\n")
    (root / "start.py").write_text('app.add_api_route("/livez", lambda: {"ok": True})')
    if not healthy:
        (root / "render.yaml").write_text("healthCheckPath: /health\n")


def test_good_deployment_contract(tmp_path):
    _fixture(tmp_path)
    result = inspect(tmp_path)
    assert result["status"] == "pass"
    assert not result["failed"]


def test_wrong_health_path_fails_closed(tmp_path):
    _fixture(tmp_path, healthy=False)
    result = inspect(tmp_path)
    assert result["status"] == "fail"
    assert "healthcheck_livez" in result["failed"]


def test_missing_files_fail_closed(tmp_path):
    result = inspect(tmp_path)
    assert result["status"] == "fail"
    assert "entrypoint_exists" in result["failed"]
