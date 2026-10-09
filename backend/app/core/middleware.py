"""Request correlation and a safe boundary for unexpected HTTP errors."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import logger


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex  # Ignore untrusted caller-supplied IDs.
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started = perf_counter()
        response_started = False
        status = 500

        async def send_response(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as exc:
            state["error_type"] = type(exc).__name__
            if response_started:
                # A second response is illegal. Hide sensitive exception chains
                # from the server's traceback logger when propagating this failure.
                raise RuntimeError("Request failed after response started.") from None
            # Own the HTTP error boundary so the server does not also print the
            # original exception, which can contain SQL parameters or credentials.
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Unexpected server error. Please try again.",
                    "request_id": request_id,
                },
            )
            await response(scope, receive, send_response)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"]
            logger.log(
                logging.ERROR
                if status >= 500 or state.get("error_type")
                else logging.INFO,
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": method
                    if method
                    in {
                        "GET",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "HEAD",
                        "OPTIONS",
                        "TRACE",
                        "CONNECT",
                    }
                    else "OTHER",
                    "route": route,  # Template, never raw path or query string.
                    "status": status,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "error_type": state.get("error_type"),
                },
            )
