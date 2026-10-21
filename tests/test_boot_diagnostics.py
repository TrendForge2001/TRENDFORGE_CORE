from __future__ import annotations

import subprocess
import sys


def test_import_watchdog_emits_stack_and_cancels_after_completion():
    result = subprocess.run(
        [sys.executable, "-c", """
import os
import time
os.environ['TRENDFORGE_PRODUCTION_RUNTIME'] = 'true'
from core.boot_diagnostics import startup_import
with startup_import(stall_seconds=0.05):
    time.sleep(0.12)
time.sleep(0.12)
"""],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "phase=asgi_import status=starting" in result.stderr
    assert "Timeout" in result.stderr
    assert "phase=asgi_import status=complete" in result.stderr
    after_completion = result.stderr.split("phase=asgi_import status=complete", 1)[1]
    assert "Timeout" not in after_completion
