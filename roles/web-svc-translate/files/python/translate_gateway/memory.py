"""Weblate as the translation memory and the glossary of protected terms."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

APPROVED = 30


def _quote(text):
    """*text* as a Weblate search literal.

    Weblate's query language delimits a literal with double quotes, so a
    backslash and a quote inside the string have to survive as escapes or the
    query ends in the middle of the searched text.
    """
    escaped = (text or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class WeblateClient:
    """Weblate's HTTP API, authenticated with a token from the store.

    Args:
        base_url: Weblate's root, without a trailing slash.
        token: the API token Weblate issued for the reading account.
        timeout: seconds to wait for a response.
    """

    def __init__(self, base_url, token, *, timeout=10):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def get(self, path, params=None):
        """The decoded body of ``GET <base>/api/<path>``.

        Raises:
            OSError: when Weblate cannot be reached.
            ValueError: when it answers with something other than JSON.
        """
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base_url}/api/{path.lstrip('/')}{query}",
            headers={"Authorization": f"Token {self._token}"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            return json.loads(response.read())


class WeblateMemory:
    """The reviewed translation of a string, when a human approved one.

    Args:
        client: a WeblateClient.
    """

    def __init__(self, client):
        self._client = client

    def reviewed(self, target, text):
        """The approved translation of *text* into *target*, or None.

        Args:
            target: target language code.
            text: the string to look up verbatim.

        Raises:
            OSError: when Weblate cannot be reached.
            ValueError: when it answers with something other than JSON.
        """
        query = f"source:={_quote(text)} AND language:{target} AND state:>=approved"
        body = self._client.get("units/", {"q": query, "format": "json"})
        for unit in (body or {}).get("results") or []:
            if int(unit.get("state") or 0) < APPROVED:
                continue
            translation = next(
                (part for part in unit.get("target") or [] if part.strip()), ""
            )
            if translation:
                return translation
        return None


class WeblateGlossary:
    """The glossary terms a translation into a language must keep.

    Weblate keeps a glossary as an ordinary component flagged
    ``is_glossary``, so the terms are the sources of that component's units.
    The per-language term list is read once and kept, because it changes when
    a human edits the glossary rather than per request.

    Args:
        client: a WeblateClient.
        project: the project whose glossaries are read.
    """

    def __init__(self, client, project):
        self._client = client
        self._project = project
        self._terms = {}

    def _glossary_slugs(self):
        body = self._client.get(f"projects/{self._project}/components/")
        return [
            component.get("slug")
            for component in (body or {}).get("results") or []
            if component.get("is_glossary") and component.get("slug")
        ]

    def _load(self, target):
        terms = []
        for slug in self._glossary_slugs():
            body = self._client.get(
                f"translations/{self._project}/{slug}/{target}/units/"
            )
            terms += [
                part
                for unit in (body or {}).get("results") or []
                for part in unit.get("source") or []
                if part.strip()
            ]
        return tuple(dict.fromkeys(terms))

    def terms(self, target, text):
        """The glossary terms of *target* that *text* contains.

        Raises:
            OSError: when Weblate cannot be reached.
            ValueError: when it answers with something other than JSON.
        """
        if target not in self._terms:
            self._terms[target] = self._load(target)
        return tuple(term for term in self._terms[target] if term in (text or ""))
