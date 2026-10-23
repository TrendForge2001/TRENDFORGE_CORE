"""The production Kite integration must not load the retired SDK dependency tree."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"kiteconnect", "autobahn", "twisted"}


def test_production_sources_do_not_import_the_retired_sdk_stack():
    violations = []
    for package in ("api", "core", "providers", "services", "scripts", "execution"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Call) and node.args:
                    function = node.func
                    dynamic_import = (
                        isinstance(function, ast.Name) and function.id == "__import__"
                    ) or (
                        isinstance(function, ast.Attribute)
                        and function.attr == "import_module"
                    )
                    value = node.args[0]
                    if (
                        dynamic_import
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        names = [value.value]
                for name in names:
                    if name.split(".", 1)[0] in FORBIDDEN:
                        violations.append(
                            (str(path.relative_to(ROOT)), node.lineno, name)
                        )
    assert violations == []


def test_production_requirements_exclude_the_retired_sdk_stack():
    for name in (
        "requirements.txt",
        "requirements-production.lock",
        "webapp/requirements.txt",
    ):
        packages = {
            line.split("=", 1)[0]
            .split(">", 1)[0]
            .split("<", 1)[0]
            .split("[", 1)[0]
            .lower()
            for line in (ROOT / name).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }
        assert not FORBIDDEN & packages, name


def test_broker_modules_import_with_sdk_stack_and_network_explicitly_denied():
    script = r"""
import importlib.abc
import sys
import requests

class RetiredSDKDenied(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in {"kiteconnect", "autobahn", "twisted"}:
            raise AssertionError("Retired SDK import attempted: " + fullname)
        return None

def no_network(*args, **kwargs):
    raise AssertionError("Broker module import must remain offline")

sys.meta_path.insert(0, RetiredSDKDenied())
requests.sessions.Session.request = no_network
import providers.kite_provider
import api.kite_service
import api.websocket_service
import scripts.local_engine_runtime
assert not {"kiteconnect", "autobahn", "twisted"} & set(sys.modules)
print("KITE_STACK_IMPORTS_OFFLINE=true")
"""
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "KITE_API_KEY": "",
        "KITE_API_SECRET": "",
        "KITE_ACCESS_TOKEN": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KITE_STACK_IMPORTS_OFFLINE=true" in result.stdout
