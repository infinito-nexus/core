"""The assistant's models, reached through the svc-ai-litellm gateway.

Each persona has its own pinned model alias, built from the base model and
that persona's adapter; the embedding model has a pin of its own. The
passages go to the model as quoted reference data inside the user turn, never
as instructions.
"""

from __future__ import annotations

import json
import re
import urllib.request

from assistant.pins import unpinned

REFERENCE_OPEN = "<reference>"
REFERENCE_CLOSE = "</reference>"
DEFUSED = "[reference]"

_DELIMITER = re.compile(r"<\s*/?\s*reference\b[^>]*>", re.IGNORECASE)


def defused(text: str) -> str:
    """Return *text* with every reference tag replaced by :data:`DEFUSED`.

    Args:
        text: a passage part or the question, as it would enter the chat turn.
    """
    return _DELIMITER.sub(DEFUSED, str(text))


def messages(question: str, passages) -> list[dict]:
    """Return the chat turn that asks *question* over *passages*.

    Args:
        question: the user's question.
        passages: the passages the answer may draw on.
    """
    quoted = "\n\n".join(
        f"{REFERENCE_OPEN}\n[{defused(p.title)}]({defused(p.url)})\n"
        f"{defused(p.text)}\n{REFERENCE_CLOSE}"
        for p in passages
    )
    return [{"role": "user", "content": f"{quoted}\n\nQuestion: {defused(question)}"}]


class Models:
    """The persona chat models and the embedding model of one deployment.

    Args:
        base_url: the OpenAI-compatible gateway URL on the container network.
        api_key: this role's virtual key for the gateway.
        chat: persona name to pinned chat model alias.
        embedding: the pinned embedding model alias.
        timeout: seconds one model call may take.

    Raises:
        ValueError: a reference is not pinned to one version.
    """

    def __init__(
        self, base_url: str, api_key: str, chat: dict, embedding: str, timeout: float
    ) -> None:
        refused = unpinned({**chat, "embedding": embedding})
        if refused:
            raise ValueError(f"unpinned model references: {refused}")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._chat = dict(chat)
        self._embedding = embedding
        self._timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            return json.loads(response.read().decode("utf-8"))

    def complete(self, persona: str, question: str, passages) -> str:
        """Return the persona model's reply to *question* over *passages*."""
        reply = self._post(
            "/chat/completions",
            {"model": self._chat[persona], "messages": messages(question, passages)},
        )
        choices = reply.get("choices") or [{}]
        return str(choices[0].get("message", {}).get("content") or "")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text, in the order of *texts*."""
        reply = self._post(
            "/embeddings", {"model": self._embedding, "input": list(texts)}
        )
        rows = sorted(reply.get("data", []), key=lambda row: row.get("index", 0))
        return [list(map(float, row["embedding"])) for row in rows]
