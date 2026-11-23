"""An explicitly authenticated synthetic Kite-window session for UI unit tests."""

from core.report_access import kite_token


def authorize_kite_window(app, monkeypatch):
    key = "synthetic-kite-window-password-for-component-tests"
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", key)
    app.session_state["tf_kite_window_token"] = kite_token(key)
    return app.run(timeout=15)
