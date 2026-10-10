from pathlib import Path


def test_render_python_runtime_is_pinned_to_312():
    root = Path(__file__).resolve().parents[1]
    pin = root / ".python-version"

    assert pin.is_file()
    assert pin.read_text(encoding="utf-8").strip() == "3.12"


def test_render_service_uses_native_python_runtime():
    root = Path(__file__).resolve().parents[1]
    render_yaml = (root / "render.yaml").read_text(encoding="utf-8")

    assert "runtime: python" in render_yaml
