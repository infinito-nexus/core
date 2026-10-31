"""Ask a model how faithfully one text states another.

The oracle suite needs a verdict in every language the repository names, and
``laya`` cannot give one: measured against the suite's fixture its ``english``
checkpoint separates a faithful rendering from an unrelated text in 17 of 47
languages and its ``multilingual`` checkpoint in none, answering around 1.5
either way. A chat model covers the rest, so the whole suite asks one judge
rather than routing per language.

The question keeps the shape the checkpoint answered: levels written out and
an index over them, never a bare probability. A probability carries this
deployment's calibration, and a fixed threshold on it would encode that
calibration into the suite; "below the middle level" instead means what the
middle level says.

The model is reached through the model gateway, not through a model server, so
the request carries a consumer identity and resolves through the gateway's
model list like every other model call in this deployment.
"""

from __future__ import annotations

import json
import re
import urllib.request

LEVELS = (
    "the second text states something other than the first text",
    "the second text states the first text but distorts a detail",
    "the second text faithfully states the first text",
)
LANGUAGE_LEVELS = (
    "the text is not written in {language}",
    "the text mixes {language} with another language",
    "the text is written in {language}",
)
MIDDLE = (len(LEVELS) - 1) // 2
TIMEOUT_SECONDS = 120
ASK_ATTEMPTS = 3
NUDGE = "Answer with one digit and nothing else."
_INDEX = re.compile(r"-?\d+")

PROMPT = """\
Rate how faithfully the second text states what the first text states.

Answer with one digit and nothing else, choosing the line that fits best:
{levels}

First text:
{source}

Second text:
{translation}
"""

LANGUAGE_PROMPT = """\
Decide which language the text below is written in.

Answer with one digit and nothing else, choosing the line that fits best:
{levels}

Text:
{text}
"""


def question(source: str, translation: str) -> str:
    """Return the prompt that asks for a level index.

    Args:
        source: the English source.
        translation: the text to judge against it.
    """
    levels = "\n".join(f"{index} {level}" for index, level in enumerate(LEVELS))
    return PROMPT.format(levels=levels, source=source, translation=translation)


def language_question(text: str, language: str) -> str:
    """Return the prompt that asks which language a text is written in.

    Faithfulness alone passes a translation that states the source correctly
    in the wrong language, which is how catalogues end up holding one
    language's text under another's code.

    Args:
        text: the text to place on the levels.
        language: the English name of the language it should be written in.
    """
    levels = "\n".join(
        f"{index} {level.format(language=language)}"
        for index, level in enumerate(LANGUAGE_LEVELS)
    )
    return LANGUAGE_PROMPT.format(levels=levels, text=text)


def parse_level(answer: str) -> int:
    """Return the level index *answer* names.

    Args:
        answer: the model's reply.

    Raises:
        ValueError: the reply names no index, or one outside the levels. Both
            are refusals to answer the question that was asked, and reading
            them as a score would put a number on a non-answer.
    """
    found = _INDEX.search(answer or "")
    if found is None:
        raise ValueError(f"the judge answered {answer!r}, which names no level")
    level = int(found.group())
    if not 0 <= level < len(LEVELS):
        raise ValueError(
            f"the judge answered level {level}, outside the {len(LEVELS)} levels"
        )
    return level


class ChatJudge:
    """A model asked to place a translation on :data:`LEVELS`.

    Args:
        base_url: the model gateway's OpenAI-compatible root, without a
            trailing slash.
        model: the alias the gateway serves the prompt with.
        api_key: the virtual key the gateway issued for this consumer.
        timeout: seconds to wait for a completion.
    """

    def __init__(self, base_url, model, *, api_key=None, timeout=TIMEOUT_SECONDS):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def score(self, source: str, translation: str) -> int:
        """Return the level the judge places this pair on.

        Args:
            source: the English source.
            translation: the text to judge against it.

        Raises:
            OSError: the gateway cannot be reached.
            ValueError: it answered without a completion, or with no level.
        """
        return self._ask(question(source, translation))

    def speaks(self, text: str, language: str) -> int:
        """Return the level the judge places this text's language on.

        Args:
            text: the text to place on :data:`LANGUAGE_LEVELS`.
            language: the English name of the language it should be in.

        Raises:
            OSError: the gateway cannot be reached.
            ValueError: it answered without a completion, or with no level.
        """
        return self._ask(language_question(text, language))

    def _ask(self, prompt: str) -> int:
        """Return the level the judge names, re-asking a reply that names none.

        A small judge sometimes continues the text instead of answering, and
        the reply is then the source echoed back. That is a protocol failure,
        not a verdict, so the question is put again with the format restated.
        The answer is never supplied: a judge that keeps refusing raises.

        Args:
            prompt: the question to put.

        Raises:
            OSError: the gateway cannot be reached.
            ValueError: every attempt answered without a level.
        """
        messages = [{"role": "user", "content": prompt}]
        for attempt in range(ASK_ATTEMPTS):
            answer = self._complete(messages)
            try:
                return parse_level(answer)
            except ValueError:
                if attempt == ASK_ATTEMPTS - 1:
                    raise
                messages = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": NUDGE},
                ]
        raise ValueError("the judge named no level")

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "temperature": 0,
            "messages": messages,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(  # noqa: S310 - this deployment's own gateway
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(  # noqa: S310 - this deployment's own gateway
            request, timeout=self._timeout
        ) as response:
            body = json.loads(response.read())
        choices = (body or {}).get("choices") or []
        answer = (
            ((choices[0].get("message") or {}).get("content") or "").strip()
            if choices
            else ""
        )
        if not answer:
            raise ValueError("the judge answered without a completion")
        return answer
