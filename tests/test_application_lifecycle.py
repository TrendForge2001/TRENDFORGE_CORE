from __future__ import annotations

from core.application_factory import ApplicationFactory
from api.app import create_app


def test_each_fastapi_app_owns_one_explicit_application_factory():
    factory = ApplicationFactory()
    app = create_app(factory)

    assert app.state.application_factory is factory


def test_application_factory_is_reused_for_dependency_resolution():
    factory = ApplicationFactory()
    app = create_app(factory)

    assert app.state.application_factory is factory
    assert app.state.application_factory is factory


def test_create_app_allows_isolated_composition_roots_for_tests_or_multiple_apps():
    first = ApplicationFactory()
    second = ApplicationFactory()

    first_app = create_app(first)
    second_app = create_app(second)

    assert first_app.state.application_factory is first
    assert second_app.state.application_factory is second
    assert first_app.state.application_factory is not second_app.state.application_factory
