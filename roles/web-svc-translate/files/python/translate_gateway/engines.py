"""Backends: the three protocols a translation engine speaks in this deployment."""

from __future__ import annotations

import json
import re
import urllib.request

from .flores import code as flores_code
from .flores import pairs as flores_pairs

PROMPT = (
    "Translate the text between the markers from {source} to {target}. "
    "Answer with the translation and nothing else, no quotes, no explanation.\n"
    "{glossary}"
    "---\n{text}\n---"
)
GLOSSARY = "Keep these terms exactly as they are written: {terms}.\n"
FENCE = "---"
LABEL = re.compile(r"^[A-Za-z][A-Za-z ]{0,31}:[ \t]+")


def clean(answer: str, text: str) -> str:
    """Return the translation a chat model buried in its answer.

    A small model copies the prompt's markers back, echoes the source line
    and labels the result with the target language's English name. All three
    reach the catalog as part of the translation unless they are stripped
    here, and an entry carrying its own source text scores below the oracle's
    middle level however good the rendering after it is.

    The label is only stripped from an answer that carried one of the other
    two, because on its own ``Hinweis: `` is a translation and not a label,
    and cutting it would corrupt a correct rendering invisibly. A model that
    labels its answer has always repeated the markers or the source line
    with it.

    Args:
        answer: the completion, already stripped.
        text: the source the prompt asked about.
    """
    fenced = answer.split(FENCE)
    scaffolded = len(fenced) >= 3
    if scaffolded:
        answer = fenced[-2].strip()
    source = text.strip()
    lines = answer.splitlines()
    kept = [line for line in lines if line.strip() != source]
    answer = "\n".join(kept).strip()
    if not scaffolded and len(kept) == len(lines):
        return answer
    return LABEL.sub("", answer, count=1).strip()


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
        self._read = None

    @property
    def pairs(self):
        """The pairs this backend declares, or an empty set when it declares none.

        The gateway's ``/languages`` is the union over its backends, so a
        backend without a catalogue contributes nothing there while still
        serving every pair it is asked for.
        """
        return frozenset(self._languages or ())

    def known(self):
        """The pairs this backend serves, or None while that is unknown.

        A declared catalogue wins. Otherwise the backend is asked once and
        the answer kept, because the backend is the only thing that knows
        which models it loaded, and a second copy in the role's
        configuration goes stale the moment one lands. Only a successful
        read is kept: a backend that was unreachable once must not be
        written off for the life of the process.
        """
        if self._languages is not None:
            return self._languages
        if self._read is None:
            try:
                self._read = self.catalogue()
            except (OSError, ValueError):
                return None
        return self._read

    def serves(self, source, target):
        """True when this backend covers the pair.

        A catalogue that cannot be read reads as "any pair": treating the
        absence as a refusal would silence a backend that works. A catalogue
        that can be read is binding, which is what keeps a language the
        engine holds no model for from being routed here and answered with
        HTTP 400 instead of falling through to the next backend.
        """
        known = self.known()
        if known is None:
            return True
        if not source or source == "auto":
            return any(declared == target for _, declared in known)
        return (source, target) in known

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
        translation = clean(answer, text)
        if not translation:
            raise ValueError(f"{self.name} answered without a translation")
        return translation


class NllbEngine:
    """NLLB-200 behind the inference server of ``svc-ai-nllb-engine``.

    NLLB is a sequence-to-sequence translation model rather than a chat
    model, so nothing here is a prompt: the request carries the source and
    target language as FLORES-200 codes and the server conditions the decoder
    on them. That is also why this is a third backend kind and not an alias of
    the other two. The LibreTranslate client speaks ISO codes to an engine
    that answers which ones it loaded; the chat client speaks a prompt to a
    model that will answer in whatever it feels like. This one has to cross
    the ISO 639-1 to FLORES-200 boundary on every call, and a language that
    boundary has no crossing for is refused rather than handed to the model to
    invent, which is the failure the chat backend produced for Belarusian,
    Abkhaz and Amharic.

    Args:
        name: how the router and the learning log refer to this backend.
        base_url: the inference server's root, without a trailing slash.
        timeout: seconds to wait for a translation.
        languages: ``{(source, target)}`` it serves, or None to take the full
            catalogue the FLORES mapping derives.
    """

    def __init__(self, name, base_url, *, timeout=120, languages=None):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._languages = (
            frozenset(tuple(pair) for pair in languages)
            if languages is not None
            else flores_pairs()
        )

    @property
    def pairs(self):
        """The ISO 639-1 pairs this backend serves."""
        return self._languages

    def serves(self, source, target):
        """True when NLLB has a FLORES code for both ends of the pair.

        An absent or ``auto`` source is refused. NLLB carries no language
        detector and the decoder needs a source token, so there is nothing
        honest to send: answering such a request would mean guessing the
        token, and the guess reaches the catalog as a translation. Refusing
        leaves the request to a backend that does detect.
        """
        if not source or source == "auto":
            return False
        return (source, target) in self._languages

    def translate(self, source, target, text, protected=(), fmt="text"):
        """The translation the model generated.

        Args:
            source: source language code; required, see :meth:`serves`.
            target: target language code.
            text: the string to translate.
            protected: accepted for signature parity; NLLB takes no glossary,
                so the terms are checked on the answer by the router instead.
            fmt: ``text`` only. NLLB has no markup-preserving mode, so an
                ``html`` payload would come back with its tags translated and
                a caller's masked spans destroyed.

        Raises:
            OSError: when the inference server cannot be reached.
            ValueError: when a language has no FLORES code, when ``html`` is
                asked for, or when the server answers without a translation.
        """
        if fmt != "text":
            raise ValueError(f"{self.name} serves no {fmt} payloads")
        payload = {
            "source": flores_code(source),
            "target": flores_code(target),
            "text": text,
        }
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base_url}/translate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            body = json.loads(response.read())
        answer = ((body or {}).get("translation") or "").strip()
        if not answer:
            raise ValueError(f"{self.name} answered without a translation")
        return answer

    def catalogue(self):
        """The ISO pairs this backend serves, as the gateway's route reads them.

        The model is the same 202 FLORES codes whatever host it runs on, so
        the mapping answers this without a round trip; reading it back off the
        server would only report the same table a slow start had not loaded
        yet.
        """
        return set(self._languages)
