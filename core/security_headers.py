"""Baseline browser protections for the API and unified Streamlit surface."""
from starlette.datastructures import MutableHeaders


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Strict-Transport-Security", "max-age=31536000")
                headers.setdefault("Content-Security-Policy", "object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
            await send(message)

        await self.app(scope, receive, with_headers)
