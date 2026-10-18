"""Backends: the two protocols a translation engine speaks in this deployment."""

from __future__ import annotations

import json
import urllib.request

PROMPT = (
    "Translate the text between the markers from {source} to {target}. "
    "Answer with the translation and nothing else, no quotes, no explanation.\n"
    "{glossary}"
    "---\n{text}\n---"
)
GLOSSARY = "Keep these terms exactly as they are written: {terms}.\n"


class LibreTranslateEngine:
    """One backend behind the LibreTranslate HTTP API.

    LibreTranslate and LTEngine both serve this shape, so one client reaches
    either. What differs between them is the deployment, not the protocol.

    Args:
        name: how the router and the learning log refer to this backend.
        base_url: its root, without a trailing slash.
        api_key: sent as ``api_key`` when the backend demands one.
        timeout: seconds to wait for a translation.
        languages: ``{(source, target)}`` it serves, or None for any pair.
    """

    def __init__(self, name, base_url, *, api_key=None, timeout=30, languages=None):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._languages = set(languages) if languages is not None else None

    @property
    def pairs(self):
        """The pairs this backend declares, or an empty set when it declares none.

        The gateway's ``/languages`` is the union over its backends, so a
        backend without a catalogue contributes nothing there while still
        serving every pair it is asked for.
        """
        return frozenset(self._languages or ())

    def serves(self, source, target):
        """True when this backend covers the pair.

        An unknown language list reads as "any pair": the catalogue is an
        optimisation, and treating its absence as a refusal would silence a
        backend that works.
        """
        if self._languages is None:
            return True
        return (source or "auto", target) in self._languages

    def catalogue(self):
        """The pairs the backend itself reports, as ``{(source, target)}``.

        Asked only when nothing was declared for this backend. The engine
        knows its own models, so reading them back beats a second copy in
        the role's configuration that would go stale when a model lands.

        Raises:
            OSError: when the backend cannot be reached.
        """
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base_url}/languages", method="GET"
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            body = json.loads(response.read())
        return {
            (entry.get("code"), target)
            for entry in body or []
            for target in entry.get("targets") or ()
        }

    def _post(self, path, payload):
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            return json.loads(response.read())

    def translate(self, source, target, text, protected=(), fmt="text"):
        """The translation of *text*, as this backend returns it.

        Args:
            source: source language code, or None for auto-detection.
            target: target language code.
            text: the string to translate.
            protected: glossary terms; the LibreTranslate API takes none, so
                they are checked on the answer instead of sent.
            fmt: the LibreTranslate payload format, ``text`` or ``html``. A
                caller that masks its protected spans as tags MUST ask for
                ``html``, because in text mode the engine translates the tag
                itself and the mask never comes back.

        Raises:
            OSError: when the backend cannot be reached.
            ValueError: when it answers without a translation.
        """
        payload = {
            "q": text,
            "source": source or "auto",
            "target": target,
            "format": fmt,
        }
        if self._api_key:
            payload["api_key"] = self._api_key
        body = self._post("/translate", payload)
        answer = (body or {}).get("translatedText")
        if not answer:
            raise ValueError(f"{self.name} answered without a translation")
        return answer

    def detect(self, text):
        """The language code this backend reads *text* as.

        Raises:
            OSError: when the backend cannot be reached.
            ValueError: when it answers without a candidate.
        """
        payload = {"q": text}
        if self._api_key:
            payload["api_key"] = self._api_key
        body = self._post("/detect", payload)
        candidates = body if isinstance(body, list) else []
        if not candidates:
            raise ValueError(f"{self.name} detected no language")
        return candidates[0].get("language")


class ChatModelEngine:
    """A model asked to translate, through the model gateway's chat API.

    A model serves completions, not translations, so this engine is the one
    place where a translation is a prompt. It talks to svc-ai-litellm rather
    than to the model server directly, so the request carries a consumer
    identity and resolves through the gateway's model list like every other
    model call in the deployment.

    Args:
        name: how the router and the learning log refer to this backend.
        base_url: the gateway's OpenAI-compatible root, without a trailing
            slash.
        model: the alias the gateway serves the prompt with.
        api_key: the virtual key the gateway issued for this consumer.
        timeout: seconds to wait for a completion.
        languages: ``{(source, target)}`` it serves, or None for any pair.
    """

    def __init__(
        self, name, base_url, model, *, api_key=None, timeout=60, languages=None
    ):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._languages = set(languages) if languages is not None else None

    @property
    def pairs(self):
        """The pairs this backend declares, empty when it declares none."""
        return frozenset(self._languages or ())

    def serves(self, source, target):
        """True when this backend covers the pair."""
        if self._languages is None:
            return True
        return (source or "auto", target) in self._languages

    def translate(self, source, target, text, protected=(), fmt="text"):
        """The translation the model generated.

        Args:
            source: source language code, or None for an undeclared one.
            target: target language code.
            text: the string to translate.
            protected: glossary terms the prompt tells the model to keep.
            fmt: accepted for signature parity with the LibreTranslate
                backend; a prompt carries no payload format.

        Raises:
            OSError: when the model gateway cannot be reached.
            ValueError: when it answers without a completion.
        """
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT.format(
                        source=source or "the source language",
                        target=target,
                        text=text,
                        glossary=(
                            GLOSSARY.format(terms=", ".join(protected))
                            if protected
                            else ""
                        ),
                    ),
                }
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            body = json.loads(response.read())
        choices = (body or {}).get("choices") or []
        answer = (
            ((choices[0].get("message") or {}).get("content") or "").strip()
            if choices
            else ""
        )
        if not answer:
            raise ValueError(f"{self.name} answered without a translation")
        return answer
