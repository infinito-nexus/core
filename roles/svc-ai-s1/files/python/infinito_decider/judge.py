"""Putting one typed choice to the decider, and judging answers blind."""

from __future__ import annotations

import json
import urllib.request


class Decider:
    """The System One endpoint, asked for one typed choice at a time.

    Args:
        url: base URL of the decider.
        key: bearer token it expects.
        model: model it should answer with.
        timeout: seconds to wait for an answer.
        max_state_chars: how much of the state is sent; a longer state is cut.
    """

    def __init__(self, url, key, model, timeout, max_state_chars):
        self._url = url
        self._key = key
        self._model = model
        self._timeout = timeout
        self._max_state_chars = max_state_chars

    def ask(self, state, question, instructions, criteria):
        """Put one typed choice and return the answer block it sent.

        Raises:
            OSError: when the decider cannot be reached.
            ValueError: when it answers a different question than the one asked.
        """
        payload = {
            "state": state[: self._max_state_chars],
            "model": self._model,
            "questions": {
                question: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            },
        }
        request = urllib.request.Request(  # noqa: S310 configured internal origin
            f"{self._url}/v1/systemone",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 configured internal origin
            body = json.loads(response.read())
        answer = (body.get("answers") or {}).get(question)
        if not answer:
            raise ValueError(f"the decider returned no answer to {question!r}")
        return answer

    def judge_answers(self, text, replies, question):
        """The option whose reply the decider calls the best answer to *text*.

        The options are the replies themselves, not the routes that produced
        them, so the verdict rests on what came back rather than on what a
        catalog promised. Aliases are never shown to the decider for the same
        reason.
        """
        labels = {
            f"option-{index}": alias for index, alias in enumerate(sorted(replies))
        }
        answer = self.ask(
            text,
            question,
            "Which of these answers serves the request best?",
            {
                label: replies[alias][: self._max_state_chars]
                for label, alias in labels.items()
            },
        )
        label = answer.get("choice")
        if label not in labels:
            raise ValueError(
                f"the decider chose {label!r}, which was not among {sorted(labels)}"
            )
        return labels[label]
