"""HTTP routes of the translation gateway, in LibreTranslate's shapes."""

# nocheck: mirrored-unit-test - the routes need FastAPI, which only the gateway image installs; the routing they expose is covered by test_router/test_gateway and the Playwright spec drives the HTTP surface against the live stack

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from translate_gateway.errors import GatewayError, NoBackendError

NAME = "Infinito.Nexus Translation Gateway"
UNPROCESSABLE = 422
UNAVAILABLE = 503
BATCH_CONCURRENCY = 8


def create_app(gateway, engines, *, detector=None):
    """The ASGI application serving the LibreTranslate API over *gateway*.

    Args:
        gateway: the Gateway deciding what answers a translation.
        engines: ``{name: engine}``, read for the language catalogue.
        detector: the engine asked to detect a language, or None to use the
            first engine that offers detection.

    Returns:
        The FastAPI application.
    """
    app = FastAPI(title=NAME)

    def _detector():
        if detector is not None:
            return detector
        return next((e for e in engines.values() if hasattr(e, "detect")), None)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def _root() -> JSONResponse:
        """Name the service and where its schema lives.

        It answers rather than redirecting to ``/docs``, and it serves HEAD
        beside GET, because both health checks start here: the webserver one
        HEAD-requests every vhost and accepts only 200, 301 or 302, and the
        CSP one follows redirects and renders what it lands on. Swagger UI
        loads its assets from an external CDN this deployment forbids, so a
        redirect into it failed the deploy on a gateway that was healthy.
        """
        return JSONResponse(content={"service": NAME, "schema": "/docs"})

    @app.exception_handler(GatewayError)
    async def _refuse(_request: Request, exc: GatewayError) -> JSONResponse:
        """Answer an error rather than the untranslated source text.

        A caller handed back its own string with a 200 stores it as a
        translation, and that mistake outlives every later fix.
        """
        status = UNAVAILABLE if isinstance(exc, NoBackendError) else UNPROCESSABLE
        return JSONResponse(status_code=status, content={"error": str(exc)})

    @app.post("/translate")
    async def translate(request: Request) -> JSONResponse:
        body = await request.json()
        text = body.get("q")
        target = body.get("target")
        if not text or not target:
            return JSONResponse(
                status_code=UNPROCESSABLE,
                content={"error": "'q' and 'target' are required"},
            )
        source = body.get("source")
        fmt = body.get("format") or "text"
        protected = tuple(body.get("protected") or ())
        exclude = tuple(body.get("exclude") or ())
        if not isinstance(text, list):
            engine, answer = await gateway.translate(
                source, target, text, fmt=fmt, protected=protected, exclude=exclude
            )
            return JSONResponse(content={"translatedText": answer, "engine": engine})

        if len(protected) == len(text) and all(
            isinstance(entry, list) for entry in protected
        ):
            per_item = [tuple(entry) for entry in protected]
        else:
            per_item = [protected] * len(text)
        limit = asyncio.Semaphore(BATCH_CONCURRENCY)

        async def _one(item, terms):
            async with limit:
                return await gateway.translate(
                    source, target, item, fmt=fmt, protected=terms, exclude=exclude
                )

        answered = await asyncio.gather(
            *(_one(item, terms) for item, terms in zip(text, per_item, strict=True))
        )
        return JSONResponse(
            content={
                "translatedText": [answer for _, answer in answered],
                "engine": [engine for engine, _ in answered],
            }
        )

    @app.post("/detect")
    async def detect(request: Request) -> JSONResponse:
        body = await request.json()
        text = body.get("q")
        if not text:
            return JSONResponse(
                status_code=UNPROCESSABLE, content={"error": "'q' is required"}
            )
        engine = _detector()
        if engine is None:
            return JSONResponse(
                status_code=UNAVAILABLE,
                content={"error": "no backend offers language detection"},
            )
        return JSONResponse(
            content=[{"language": engine.detect(text), "confidence": 1}]
        )

    async def _pairs_of(engine):
        """What *engine* offers: its declaration, else what it reports itself.

        A backend that declares nothing still serves every pair it is asked
        for, so leaving it out of the catalogue made the gateway advertise
        an empty language list while translating fine.
        """
        declared = getattr(engine, "pairs", None)
        if declared:
            return set(declared)
        reader = getattr(engine, "catalogue", None)
        if reader is None:
            return set()
        try:
            return await asyncio.to_thread(reader)
        except Exception:
            return set()

    @app.get("/languages")
    async def languages() -> JSONResponse:
        reported = await asyncio.gather(
            *(_pairs_of(engine) for engine in engines.values())
        )
        pairs = sorted(set().union(*reported) if reported else set())
        catalogue: dict[str, list[str]] = {}
        for source, target in pairs:
            catalogue.setdefault(source, []).append(target)
        return JSONResponse(
            content=[
                {"code": code, "targets": targets}
                for code, targets in sorted(catalogue.items())
            ]
        )

    return app
