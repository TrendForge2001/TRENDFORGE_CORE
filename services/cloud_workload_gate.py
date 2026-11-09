"""One web-worker admission gate: prioritize paper control over heavy research."""

import threading
import weakref
from functools import wraps

from core.deployment_role import on_render

_LOCK = threading.RLock()
_RESEARCH = weakref.WeakSet()
_PAPER = weakref.WeakSet()
_VALIDATION = weakref.WeakSet()
_STARTING = weakref.WeakKeyDictionary()


class CloudWorkloadBusy(ValueError):
    pass


def register_research(manager):
    with _LOCK:
        _RESEARCH.add(manager)


def register_paper(automation):
    with _LOCK:
        _PAPER.add(automation)


def research_busy():
    return any(
        not manager._stopping.is_set()
        and any(not future.done() for future in manager.futures.values())
        for manager in list(_RESEARCH)
    )


def paper_busy():
    if _STARTING or any(
        paper._enabled and not paper._stopping for paper in list(_PAPER)
    ):
        return True
    for app in list(_VALIDATION):
        state = getattr(app.state, "r7253_validation", {})
        worker = state.get("_thread") if isinstance(state, dict) else None
        if worker is not None and worker.is_alive():
            return True
    return False


def research_admission(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        if not on_render():
            return function(self, *args, **kwargs)
        with _LOCK:
            if paper_busy():
                raise CloudWorkloadBusy(
                    "Research is paused while paper automation or validation is active"
                )
            return function(self, *args, **kwargs)

    return guarded


def paper_admission(function):
    @wraps(function)
    def guarded(self, enabled, *args, **kwargs):
        if not on_render() or not enabled:
            # Stop never waits behind a slow Start's validation or network call.
            result = function(self, enabled, *args, **kwargs)
            if not enabled:
                with _LOCK:
                    _STARTING.pop(self, None)
            return result
        token = object()
        with _LOCK:
            if research_busy():
                raise CloudWorkloadBusy(
                    "Finish or cancel research batches before starting "
                    "Render paper automation"
                )
            _STARTING[self] = token
        try:
            return function(self, enabled, *args, **kwargs)
        finally:
            with _LOCK:
                if _STARTING.get(self) is token:
                    _STARTING.pop(self, None)

    return guarded


def validation_admission(function):
    @wraps(function)
    def guarded(app, *args, **kwargs):
        if not on_render():
            return function(app, *args, **kwargs)
        with _LOCK:
            if research_busy():
                raise CloudWorkloadBusy(
                    "Finish or cancel research batches before starting paper validation"
                )
            _VALIDATION.add(app)
            return function(app, *args, **kwargs)

    return guarded
