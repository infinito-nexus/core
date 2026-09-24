"""Assert the System One server answers every question type on its input.

Runs inside the jeff container, where the API answers on loopback. Standard
library only: the image ships the server, not a test toolchain.

Each type is asked twice with texts whose correct answer is unambiguous and
opposite, so a server that loads the model but does not read the state fails:
it either breaks the wire contract or returns the same answer to both.

Env:
    PORT            http port the server listens on inside the container
    MODEL           alias the API accepts in a request's ``model`` field
    JEFF_API_KEYS   the server's own key list, read from its environment rather
                    than passed in, so no key reaches a command line
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 120

CHOICE_OPTIONS = {
    "weather": "the text is about weather, rain, storms or a forecast",
    "cooking": "the text is about food, recipes, ingredients or a kitchen",
}
NOUL_CRITERIA = {
    "true": "the text is about weather, rain, storms or a forecast",
    "false": "the text is about food, recipes, ingredients or a kitchen",
}
SCORE_LEVELS = [
    "the text is negative and unhappy",
    "the text is neutral",
    "the text is positive and happy",
]
SCORE_MIDPOINT = (len(SCORE_LEVELS) - 1) / 2
NOUL_MIN_SEPARATION = 0.2

RAIN = "It rained all morning and the forecast promises more storms tonight."
ONIONS = "Dice the onions, brown them in butter, then fold in the flour."
PRAISE = "Wonderful work, I am delighted with how well this turned out."
COMPLAINT = "Terrible work, I am furious about how badly this turned out."


def choice_question(name: str) -> dict:
    return {
        name: {
            "type": "choice",
            "instructions": "Pick the topic this text belongs to.",
            "criteria": CHOICE_OPTIONS,
        }
    }


def noul_question(name: str) -> dict:
    return {
        name: {
            "type": "noul",
            "instructions": "Decide whether this text is about weather.",
            "criteria": NOUL_CRITERIA,
        }
    }


def score_question(name: str) -> dict:
    return {
        name: {
            "type": "score",
            "instructions": "Rate how positive this text is.",
            "criteria": SCORE_LEVELS,
        }
    }


def verify_choice(answer: dict, expected: str) -> tuple[str, str]:
    """The observed value and a violation message, empty when the answer holds."""
    choice = answer.get("choice")
    if choice not in CHOICE_OPTIONS:
        return str(choice), (
            f"chose {choice!r}, which is not one of the options it was given "
            f"({sorted(CHOICE_OPTIONS)})"
        )
    if choice != expected:
        return choice, f"chose {choice!r} where the text is plainly {expected!r}"
    return choice, ""


def verify_noul(answer: dict, expected: str) -> tuple[str, str]:
    """noul is P(true) for the criterion indexed first upstream.

    Only the shape is judged here. The server does not centre this probability
    on 0.5: measured against a topic the encoder separates cleanly, a plainly
    false text still answered 0.5908 where a true one answered 0.9507. The
    ordering is what it carries, so the pair is judged in ``run_type``.
    """
    raw = answer.get("noul")
    if not isinstance(raw, (int, float)):
        return str(raw), f"returned noul={raw!r}, which is not a number"
    return f"{raw}", ""


def separated(observed: list[str], cases: tuple) -> str:
    """Why the true text did not outscore the false one, or the empty string."""
    scores = dict(zip((expected for _state, expected in cases), observed, strict=True))
    spread = float(scores["true"]) - float(scores["false"])
    if spread < NOUL_MIN_SEPARATION:
        return (
            f"answered {scores['true']} for the true text and {scores['false']} "
            f"for the false one, a spread of {spread:.4f}; below "
            f"{NOUL_MIN_SEPARATION} the two are not told apart"
        )
    return ""


def verify_score(answer: dict, expected: str) -> tuple[str, str]:
    """score is the expected level index over SCORE_LEVELS."""
    raw = answer.get("score")
    if not isinstance(raw, (int, float)):
        return str(raw), f"returned score={raw!r}, which is not a number"
    wants_high = expected == "high"
    if (raw > SCORE_MIDPOINT) != wants_high:
        side = "above" if raw > SCORE_MIDPOINT else "below"
        return f"{raw}", (
            f"returned score={raw}, {side} the {SCORE_MIDPOINT} midpoint, where "
            f"the text is plainly {expected}"
        )
    return f"{raw}", ""


PROBES = (
    (
        "choice",
        choice_question,
        verify_choice,
        ((RAIN, "weather"), (ONIONS, "cooking")),
        None,
    ),
    (
        "noul",
        noul_question,
        verify_noul,
        ((RAIN, "true"), (ONIONS, "false")),
        separated,
    ),
    (
        "score",
        score_question,
        verify_score,
        ((PRAISE, "high"), (COMPLAINT, "low")),
        None,
    ),
)


def ask(base: str, key: str, state: str, questions: dict, model: str) -> dict:
    """The answers block the server replied with.

    Args:
        base: ``http://host:port`` of the server.
        key: bearer key to authenticate with.
        state: the text the server classifies.
        questions: the ``questions`` mapping to send.
        model: the model alias to address.

    Returns:
        The ``answers`` mapping.
    """
    payload = json.dumps({"state": state, "model": model, "questions": questions})
    request = urllib.request.Request(  # noqa: S310 - literal http:// to loopback
        base + "/v1/systemone",
        data=payload.encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(  # noqa: S310 - literal http:// to loopback
        request, timeout=TIMEOUT
    ) as response:
        return json.loads(response.read().decode() or "{}").get("answers") or {}


def run_type(
    base: str, key: str, model: str, name, build, verify, cases, pair=None
) -> list[str]:
    """Every violation this question type showed, as messages."""
    failures: list[str] = []
    observed: list[str] = []
    for state, expected in cases:
        answers = ask(base, key, state, build(name), model)
        if name not in answers:
            failures.append(
                f"{name}: the answer carries no {name!r}: {sorted(answers)}"
            )
            continue
        if answers[name].get("type") != name:
            failures.append(
                f"{name}: the answer declares type "
                f"{answers[name].get('type')!r}, not {name!r}"
            )
            continue
        value, violation = verify(answers[name], expected)
        observed.append(value)
        if violation:
            failures.append(f"{name}: {violation}")
        else:
            print(f"[OK]   {name}: {expected} text -> {value}")
    if len(observed) == len(cases) and len(set(observed)) == 1:
        failures.append(
            f"{name}: both texts were answered {observed[0]}; the server returns a "
            f"constant rather than reading its input"
        )
    if pair is not None and len(observed) == len(cases):
        violation = pair(observed, cases)
        if violation:
            failures.append(f"{name}: {violation}")
    return failures


def rejects_a_wrong_key(base: str, model: str) -> str:
    """Why the server accepted a bad key, or the empty string.

    An empty ``JEFF_API_KEYS`` disables authentication upstream, so a server
    that answers an unknown key is open to anything that reaches its port.
    """
    try:
        ask(base, "not-the-configured-key", "anything", choice_question("probe"), model)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return ""
        return f"a wrong bearer key was refused with HTTP {error.code}, not 401/403"
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"the wrong-key probe could not reach the server: {exc}"
    return "the server answered a request carrying a bearer key it never issued"


def main() -> int:
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    keys = [k for k in os.environ["JEFF_API_KEYS"].replace(",", " ").split() if k]
    if not keys:
        print(
            "[FAIL] JEFF_API_KEYS is empty, which disables authentication and "
            "leaves the server open to anything that reaches its port",
            file=sys.stderr,
        )
        return 1
    key = keys[0]
    model = os.environ["MODEL"]

    failures: list[str] = []
    for name, build, verify, cases, pair in PROBES:
        failures.extend(run_type(base, key, model, name, build, verify, cases, pair))

    violation = rejects_a_wrong_key(base, model)
    if violation:
        failures.append(violation)
    else:
        print("[OK]   a bearer key the server never issued is refused")

    for failure in failures:
        print(f"[FAIL] {failure}", file=sys.stderr)
    if not failures:
        print("[OK]   every question type decides on its input")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
