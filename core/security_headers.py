"""Baseline HTTP headers for the outer UI and the standalone Core API."""

from starlette.datastructures import MutableHeaders


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault(
                    "Content-Security-Policy",
                    "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
                )
                if scope.get("scheme") == "https":
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            await send(message)

        await self.app(scope, receive, secure_send)
