"""HTTP routes of the help assistant."""

# nocheck: mirrored-unit-test - the routes need FastAPI, which only the assistant image installs; every decision they expose lives in service.py, which test_service covers

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

NAME = "Infinito.Nexus Help Assistant"
UNPROCESSABLE = 422


def create_app(assistant, path: str) -> FastAPI:
    """The ASGI application serving ``POST <path>/ask``.

    Args:
        assistant: the :class:`assistant.service.Assistant` answering questions.
        path: the same-origin path prefix the role config names.
    """
    app = FastAPI(title=NAME, docs_url=None, redoc_url=None, openapi_url=None)
    prefix = "/" + path.strip("/")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def _root() -> JSONResponse:
        return JSONResponse(content={"service": NAME})

    @app.post(f"{prefix}/ask")
    async def ask(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                status_code=UNPROCESSABLE, content={"error": "a JSON body is required"}
            )
        question = body.get("question") if isinstance(body, dict) else None
        reply = await assistant.ask(request.headers, question)
        return JSONResponse(
            status_code=reply.status, content=reply.body, headers=reply.headers
        )

    return app
