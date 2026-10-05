from pathlib import Path


def test_api_runtime_dependencies_are_declared():
    requirements = Path(__file__).parents[1] / "requirements.txt"
    text = requirements.read_text(encoding="utf-8")
    assert "fastapi" in text.lower()
    assert "uvicorn" in text.lower()


def test_fastapi_app_module_is_present():
    app = Path(__file__).parents[1] / "api" / "app.py"
    assert app.exists()
