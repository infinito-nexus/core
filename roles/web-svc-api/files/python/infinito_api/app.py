"""HTTP routes of the Infinito.Nexus API."""

# nocheck: mirrored-unit-test - the HTTP routes need FastAPI, which only the API image installs; the Playwright spec of web-svc-api drives every route against the live stack

from __future__ import annotations

import re
from typing import Annotated

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from infinito_api.i18n import Translations
from infinito_api.repository import (
    DEPLOYED,
    SHA,
    InvalidRequestError,
    NotFoundError,
    Repository,
)
from infinito_api.roles import RoleData

DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
IMMUTABLE = "public, max-age=31536000, immutable"
MUTABLE = "public, max-age=60"

Ref = Annotated[
    str,
    Query(
        description="deployed, a commit SHA, a branch or tag, or <owner>:<branch or tag>"
    ),
]
Lang = Annotated[
    str | None, Query(description="ISO 639-1 code; overrides Accept-Language")
]
AcceptLanguage = Annotated[str | None, Header()]


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def create_app(repository: Repository) -> FastAPI:
    """Return the application serving ``repository``.

    Args:
        repository: the initialized ``Repository``.
    """
    roles = RoleData(repository)
    translations = Translations(repository)
    app = FastAPI(
        title="Infinito.Nexus API",
        version="1",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Language"],
    )

    @app.middleware("http")
    async def open_cors(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.exception_handler(InvalidRequestError)
    async def invalid(_: Request, exc: InvalidRequestError) -> JSONResponse:
        return _error(400, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(400, str(exc.errors()))

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return _error(404, str(exc))

    def route(path: str):
        return app.api_route(path, methods=["GET", "HEAD"])

    def pinned(response: Response, ref: str, commit: str) -> None:
        response.headers["Cache-Control"] = (
            IMMUTABLE if SHA.match(ref) and commit.startswith(ref) else MUTABLE
        )

    def localized(
        response: Response, commit: str, lang: str | None, accept: str | None
    ):
        code = translations.negotiate(commit, lang, accept)
        response.headers["Content-Language"] = code
        response.headers["Vary"] = "Accept-Language"
        return translations.translator(commit, code)

    @route("/")
    def index() -> dict:
        return {
            "name": "Infinito.Nexus API",
            "version": "v1",
            "documentation": "/v1/docs",
        }

    @route("/v1/health")
    def health() -> dict:
        return {
            "status": "ok",
            "deployed": repository.resolve(DEPLOYED),
            "fetched": repository.fetched(),
        }

    @route("/v1/repositories")
    def repositories(response: Response) -> list[dict]:
        response.headers["Cache-Control"] = MUTABLE
        return repository.repositories()

    @route("/v1/log")
    def log(
        response: Response,
        ref: Ref,
        limit: Annotated[int, Query(ge=1, le=1000)],
        since: Annotated[str | None, Query()] = None,
        until: Annotated[str | None, Query()] = None,
    ) -> dict:
        for value in (since, until):
            if value is not None and not DATE.match(value):
                raise InvalidRequestError(f"invalid date: {value}")
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        return {
            "ref": ref,
            "commit": commit,
            "commits": repository.log(commit, since, until, limit),
        }

    @route("/v1/roles")
    def role_list(
        response: Response,
        ref: Ref,
        lang: Lang = None,
        accept_language: AcceptLanguage = None,
    ) -> dict:
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        translator = localized(response, commit, lang, accept_language)
        return {
            "ref": ref,
            "commit": commit,
            "language": translator.language,
            "roles": [
                roles.summary(commit, role, translator) for role in roles.roles(commit)
            ],
        }

    @route("/v1/roles/{role}")
    def role_detail(
        response: Response,
        role: str,
        ref: Ref,
        lang: Lang = None,
        accept_language: AcceptLanguage = None,
    ) -> dict:
        commit = repository.resolve(ref)
        if role not in roles.roles(commit):
            raise NotFoundError(f"unknown role: {role}")
        pinned(response, ref, commit)
        translator = localized(response, commit, lang, accept_language)
        return {
            "ref": ref,
            "commit": commit,
            "language": translator.language,
            "role": roles.detail(commit, role, translator),
        }

    @route("/v1/categories")
    def categories(
        response: Response,
        ref: Ref,
        lang: Lang = None,
        accept_language: AcceptLanguage = None,
    ) -> dict:
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        translator = localized(response, commit, lang, accept_language)
        return {
            "ref": ref,
            "commit": commit,
            "language": translator.language,
            "categories": roles.categories(commit, translator),
        }

    @route("/v1/bundles")
    def bundles(response: Response, ref: Ref) -> dict:
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        return {"ref": ref, "commit": commit, "bundles": roles.bundles(commit)}

    @route("/v1/tree")
    def tree(response: Response, ref: Ref, path: Annotated[str, Query()]) -> dict:
        path = repository.check_path(path)
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        return {
            "ref": ref,
            "commit": commit,
            "path": path,
            "entries": repository.listing(commit, path),
        }

    @route("/v1/file")
    def file(ref: Ref, path: Annotated[str, Query()]) -> Response:
        path = repository.check_path(path)
        commit = repository.resolve(ref)
        content = repository.blob(commit, path)
        try:
            content.decode("utf-8")
            media_type = "text/plain; charset=utf-8"
        except UnicodeDecodeError:
            media_type = "application/octet-stream"
        response = Response(content, media_type=media_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        pinned(response, ref, commit)
        return response

    @route("/v1/todos")
    def todos(response: Response, ref: Ref) -> dict:
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        return {"ref": ref, "commit": commit, **repository.todos(commit)}

    @route("/v1/languages")
    def languages(response: Response, ref: Ref) -> dict:
        commit = repository.resolve(ref)
        pinned(response, ref, commit)
        return {
            "ref": ref,
            "commit": commit,
            "languages": [
                {
                    "code": code,
                    "name": entry.get("name"),
                    "native": entry.get("native"),
                    "direction": entry.get("direction"),
                    "translated": translations.completeness(commit, code),
                }
                for code, entry in translations.languages(commit).items()
            ],
        }

    @route("/v1/catalogs/core/{code}")
    def catalog(response: Response, code: str, ref: Ref) -> dict:
        commit = repository.resolve(ref)
        entry = translations.languages(commit).get(code)
        if entry is None:
            raise NotFoundError(f"unknown language: {code}")
        pinned(response, ref, commit)
        messages: dict[str, dict[str, str]] = {}
        for (context, msgid), msgstr in translations.translator(
            commit, code
        ).messages.items():
            messages.setdefault(context or "", {})[msgid] = msgstr
        return {
            "ref": ref,
            "commit": commit,
            "language": code,
            "direction": entry.get("direction"),
            "messages": messages,
        }

    return app
