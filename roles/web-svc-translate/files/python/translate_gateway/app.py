"""HTTP routes of the translation gateway, in LibreTranslate's shapes."""

# nocheck: mirrored-unit-test - the routes need FastAPI, which only the gateway image installs; the routing they expose is covered by test_router/test_gateway and the Playwright spec drives the HTTP surface against the live stack

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from translate_gateway.errors import GatewayError, NoBackendError

UNPROCESSABLE = 422
UNAVAILABLE = 503


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
    app = FastAPI(title="Infinito.Nexus Translation Gateway")

    def _detector():
        if detector is not None:
            return detector
        return next((e for e in engines.values() if hasattr(e, "detect")), None)

    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

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
        engine, answer = await gateway.translate(body.get("source"), target, text)
        return JSONResponse(
            content={"translatedText": answer, "engine": engine},
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

    @app.get("/languages")
    async def languages() -> JSONResponse:
        pairs = sorted(
            {
                (source, target)
                for engine in engines.values()
                for source, target in getattr(engine, "pairs", None) or ()
            }
        )
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
