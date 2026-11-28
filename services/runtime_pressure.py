"""Lightweight in-process metrics. Published only on authenticated diagnostics."""

import asyncio
import os
import time
from pathlib import Path


async def observe(state):
    clock = asyncio.get_running_loop()
    last, cpu = clock.time(), time.process_time()
    while True:
        await asyncio.sleep(2)
        now, current = clock.time(), time.process_time()
        elapsed = now - last
        try:
            rss = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf(
                "SC_PAGE_SIZE"
            )
        except (OSError, ValueError, IndexError, AttributeError):
            rss = None
        state.runtime_pressure = dict(
            process_rss_bytes=rss,
            process_cpu_cores=(current - cpu) / elapsed,
            event_loop_lag_ms=max(0, elapsed - 2) * 1000,
        )
        last, cpu = now, current
