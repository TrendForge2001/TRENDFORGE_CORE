"""Temporary R71.5 research-artifact relay for Render.

Reads only the token-protected historical validation export. It has no
TrendForge admin key, Kite credentials, paper-trading permission, or broker
write path.
"""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import threading
import time
import zlib

import requests


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("trendforge.r715.bridge")
DONE = False


def relay() -> None:
    global DONE
    base = str(
        os.getenv(
            "TRENDFORGE_R715_SOURCE_URL",
            "https://trendforge-core.onrender.com",
        )
    ).rstrip("/")
    token = str(os.getenv("TRENDFORGE_R715_EXPORT_TOKEN") or "").strip()
    if not token:
        LOGGER.error("R715_BRIDGE_FAILED reason=missing_export_token")
        return
    url = f"{base}/technical/validation/export"
    for attempt in range(1, 241):
        try:
            response = requests.get(
                url,
                params={"token": token},
                timeout=30,
            )
            if response.status_code == 200:
                payload = response.content
                parsed = json.loads(payload)
                if parsed.get("status") != "completed":
                    raise RuntimeError(
                        f"unexpected export status: {parsed.get('status')}"
                    )
                compressed = zlib.compress(payload, level=9)
                encoded = base64.b64encode(compressed).decode("ascii")
                size = 7000
                chunks = [
                    encoded[start : start + size]
                    for start in range(0, len(encoded), size)
                ]
                digest = hashlib.sha256(payload).hexdigest()
                run_id = str(parsed.get("run_id") or "unknown")
                LOGGER.warning(
                    "R715_BRIDGE_META run_id=%s chunks=%s sha256=%s raw_bytes=%s compressed_bytes=%s",
                    run_id,
                    len(chunks),
                    digest,
                    len(payload),
                    len(compressed),
                )
                for index, chunk in enumerate(chunks):
                    LOGGER.warning(
                        "R715_BRIDGE_CHUNK run_id=%s index=%s data=%s",
                        run_id,
                        index,
                        chunk,
                    )
                LOGGER.warning(
                    "R715_BRIDGE_COMPLETED run_id=%s master_symbols=%s errors=%s",
                    run_id,
                    parsed.get("master_symbol_count"),
                    len(parsed.get("errors") or []),
                )
                DONE = True
                return
            LOGGER.info(
                "R715_BRIDGE_POLL attempt=%s http_status=%s",
                attempt,
                response.status_code,
            )
        except Exception as exc:
            LOGGER.warning(
                "R715_BRIDGE_POLL_ERROR attempt=%s error=%s",
                attempt,
                str(exc).replace("\n", " ")[:500],
            )
        time.sleep(10)
    LOGGER.error("R715_BRIDGE_FAILED reason=export_not_available")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {"status": "complete" if DONE else "polling"}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main() -> None:
    threading.Thread(
        target=relay,
        name="r715-artifact-relay",
        daemon=True,
    ).start()
    port = int(os.getenv("PORT", "10000"))
    LOGGER.info("R715_BRIDGE_SERVER port=%s", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
