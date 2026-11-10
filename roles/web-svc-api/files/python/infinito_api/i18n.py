"""Languages and ``core`` gettext catalogs of a commit."""

from __future__ import annotations

import io
from functools import lru_cache

from babel.messages.pofile import read_po

from infinito_api.repository import DEPLOYED, NotFoundError
from infinito_api.roles import mapping, parse_yaml

LANGUAGES_FILE = "meta/languages.yml"
SOURCE_LANGUAGE = "en"


def catalog_file(code: str) -> str:
    return f"locale/{code}/LC_MESSAGES/core.po"


def accepted(header: str | None) -> list[str]:
    """Return the primary language subtags of ``Accept-Language``, best first.

    Args:
        header: the raw header value.
    """
    ranked = []
    for position, part in enumerate((header or "").split(",")):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                continue
        if tag and tag != "*" and quality > 0:
            ranked.append((-quality, position, tag.split("-")[0].lower()))
    return [code for _, _, code in sorted(ranked)]


class Translator:
    """Looks up the translation of a source text.

    Args:
        language: the ISO 639-1 code the translations belong to.
        messages: ``(msgctxt, msgid)`` mapped to ``msgstr``.
    """

    def __init__(self, language: str, messages: dict):
        self.language = language
        self.messages = messages

    def text(self, context: str, source: str) -> str:
        return self.messages.get((context, source), source) if source else source


class Translations:
    """Readers for the languages and catalogs of a commit.

    Args:
        repository: the ``Repository`` to read from.
    """

    def __init__(self, repository):
        self.repository = repository

    def _deployed(self) -> str:
        return self.repository.resolve(DEPLOYED)

    @lru_cache(maxsize=64)  # noqa: B019  the readers live as long as the process
    def languages(self, commit: str) -> dict[str, dict]:
        content = self.repository.blobs(commit, [LANGUAGES_FILE]).get(LANGUAGES_FILE)
        if content is None:
            deployed = self._deployed()
            return {} if commit == deployed else self.languages(deployed)
        return {
            str(code): mapping(entry)
            for code, entry in mapping(parse_yaml(content)).items()
        }

    @lru_cache(maxsize=64)  # noqa: B019  the readers live as long as the process
    def catalog_commit(self, commit: str) -> str:
        return commit if self.repository.paths(commit, "locale") else self._deployed()

    @lru_cache(maxsize=512)  # noqa: B019  the readers live as long as the process
    def catalog(self, commit: str, code: str) -> tuple[dict, int]:
        """Return the usable translations of a catalog and its message count.

        Args:
            commit: commit SHA holding ``locale/``.
            code: ISO 639-1 code.
        """
        content = self.repository.blobs(commit, [catalog_file(code)]).get(
            catalog_file(code)
        )
        if content is None:
            return {}, 0
        entries = [
            message
            for message in read_po(io.BytesIO(content))
            if isinstance(message.id, str) and message.id
        ]
        return (
            {
                (message.context, message.id): message.string
                for message in entries
                if message.string and not message.fuzzy
            },
            len(entries),
        )

    def completeness(self, commit: str, code: str) -> float:
        if code == SOURCE_LANGUAGE:
            return 1.0
        messages, total = self.catalog(self.catalog_commit(commit), code)
        return round(len(messages) / total, 4) if total else 0.0

    def negotiate(
        self, commit: str, lang: str | None, accept_language: str | None
    ) -> str:
        """Return the language a request is answered in.

        Args:
            commit: commit SHA of the request.
            lang: the explicit ``lang`` parameter, if any.
            accept_language: the ``Accept-Language`` header, if any.
        """
        languages = self.languages(commit)
        if lang is not None:
            if lang not in languages:
                raise NotFoundError(f"unknown language: {lang}")
            return lang
        for code in accepted(accept_language):
            if code in languages:
                return code
        return SOURCE_LANGUAGE

    def translator(self, commit: str, code: str) -> Translator:
        if code == SOURCE_LANGUAGE:
            return Translator(code, {})
        return Translator(code, self.catalog(self.catalog_commit(commit), code)[0])
