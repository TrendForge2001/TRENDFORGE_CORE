"""R71 Streamlit login contract: Access Key gates all pages, admin is optional."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


class FakeStreamlit(ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.inputs = {}
        self.submit = False
        self.reruns = 0
        self.errors = []

    def error(self, message):
        self.errors.append(message)

    def markdown(self, message):
        pass

    def caption(self, message):
        pass

    def text_input(self, label, **kwargs):
        assert kwargs.get("type") == "password"
        return self.inputs.get(label, "")

    def form(self, *args, **kwargs):
        class Form:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return Form()

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    def rerun(self):
        self.reruns += 1


def load_access(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    spec = importlib.util.spec_from_file_location(
        "webapp_access_secure_login_test",
        ROOT / "webapp" / "access.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


def test_missing_server_key_fails_closed(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_WEBAPP_ACCESS_KEY", raising=False)
    access, fake = load_access(monkeypatch)
    assert access.access_required()
    assert not access.access_granted()
    assert not access.render_access_gate()
    assert any("not configured" in message for message in fake.errors)


def test_correct_access_key_unlocks_and_sets_optional_admin(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "separate-access-secret")
    access, fake = load_access(monkeypatch)
    fake.submit = True
    fake.inputs = {
        "Webapp Access Key (required)": "separate-access-secret",
        "Admin API Key (optional)": "backend-admin-secret",
    }
    assert not access.render_access_gate()  # First run triggers Streamlit rerun
    assert fake.reruns == 1
    assert access.access_granted()
    assert fake.session_state["tf_admin_key"] == "backend-admin-secret"
    assert access.render_access_gate()


def test_wrong_access_key_does_not_accept_admin(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "correct-access")
    access, fake = load_access(monkeypatch)
    fake.submit = True
    fake.inputs = {
        "Webapp Access Key (required)": "wrong-access",
        "Admin API Key (optional)": "should-not-be-stored",
    }
    assert not access.render_access_gate()
    assert not access.access_granted()
    assert "tf_admin_key" not in fake.session_state
    assert fake.reruns == 0


def test_admin_optional_key_rotation_invalidates_session(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "original-access")
    access, fake = load_access(monkeypatch)
    fake.inputs = {"Webapp Access Key (required)": "original-access"}
    fake.submit = True
    access.render_access_gate()
    assert access.access_granted()
    assert fake.session_state["tf_admin_key"] == ""

    fake.submit = False
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "rotated-access")
    assert not access.access_granted()
    assert not access.render_access_gate()
    assert "tf_admin_key" not in fake.session_state
    assert not access.access_granted()


def test_lock_clears_admin_key_and_results(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "access-secret")
    access, fake = load_access(monkeypatch)
    fake.session_state.update({
        "tf_access_granted": True,
        "tf_access_fingerprint": access._access_fingerprint("access-secret"),
        "tf_admin_key": "admin-secret",
        "tf_last_scan": {"symbol": "BSE"},
        "unrelated": "preserve",
    })
    assert access.access_granted()
    access.revoke_access()
    assert not access.access_granted()
    assert "tf_admin_key" not in fake.session_state
    assert "tf_last_scan" not in fake.session_state
    assert fake.session_state["unrelated"] == "preserve"
