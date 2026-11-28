"""Read the Loki and Alertmanager answers the web-svc-loki CLI test fetches.

Usage: ``python3 -I loki_probe.py <command> [args] < answer.json``

Commands:
    lines: print every stored line of a ``query_range`` answer.
    count: print the summed sample of an instant-vector ``query`` answer, 0
        when the vector is empty.
    firing NAME APPLICATION: exit 0 when the ruler's ``/prometheus/api/v1/alerts``
        answer holds a firing NAME alert for APPLICATION, else 1.
    delivered NAME APPLICATION: exit 0 when the Alertmanager's ``/api/v2/alerts``
        answer holds an active NAME alert for APPLICATION, else 1.
    alert-line RUN_ID: print the synthetic critical line of run RUN_ID; it reads
        no answer.
    url BASE [KEY=VALUE ...]: print BASE with the pairs percent-encoded as its
        query string; it reads no answer.

Exit 2 reports an answer that is not the expected JSON shape, or a url pair
without ``=``.
"""

from __future__ import annotations

import json
import sys
from urllib.parse import quote

ALERT_LINE = "INFINITO-ALERT-CANARY {run_id} critical synthetic error line"


def query_url(base: str, pairs: list[str]) -> str:
    """*base* with the ``KEY=VALUE`` *pairs* percent-encoded as its query string.

    Args:
        base: the URL without a query string.
        pairs: the query parameters in order; a value may hold ``=``.

    Raises:
        ValueError: a pair holds no ``=``.
    """
    encoded = []
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        encoded.append(f"{quote(key, safe='')}={quote(value, safe='')}")
    return f"{base}?{'&'.join(encoded)}" if encoded else base


def stored_lines(answer: dict) -> list[str]:
    """Lines of a Loki ``query_range`` streams answer, in answer order.

    Args:
        answer: the decoded JSON answer.
    """
    return [
        value[1] for stream in answer["data"]["result"] for value in stream["values"]
    ]


def stored_count(answer: dict) -> int:
    """Sum of the samples of a Loki instant-vector answer.

    Args:
        answer: the decoded JSON answer of ``/loki/api/v1/query``.

    Raises:
        ValueError: the answer is not a vector.
    """
    data = answer["data"]
    if data["resultType"] != "vector":
        raise ValueError(f"expected a vector answer, got {data['resultType']!r}")
    return sum(int(float(sample["value"][1])) for sample in data["result"])


def ruler_firing(answer: dict, name: str, application: str) -> bool:
    """Whether the ruler answer holds a firing *name* alert for *application*.

    Args:
        answer: the decoded JSON answer of ``/prometheus/api/v1/alerts``.
        name: the alert name of the rule.
        application: the ``application`` label the alert must carry.
    """
    return any(
        alert["labels"].get("alertname") == name
        and alert["labels"].get("application") == application
        and alert["state"] == "firing"
        for alert in answer["data"]["alerts"]
    )


def alertmanager_active(answer: list, name: str, application: str) -> bool:
    """Whether the Alertmanager holds an active *name* alert for *application*.

    Args:
        answer: the decoded JSON answer of ``/api/v2/alerts``.
        name: the alert name of the rule.
        application: the ``application`` label the alert must carry.
    """
    return any(
        alert["labels"].get("alertname") == name
        and alert["labels"].get("application") == application
        and alert["status"]["state"] == "active"
        for alert in answer
    )


def _print_lines(answer: dict) -> int:
    for line in stored_lines(answer):
        print(line)
    return 0


def _print_count(answer: dict) -> int:
    print(stored_count(answer))
    return 0


def _firing(answer: dict, name: str, application: str) -> int:
    return 0 if ruler_firing(answer, name, application) else 1


def _delivered(answer: list, name: str, application: str) -> int:
    return 0 if alertmanager_active(answer, name, application) else 1


_ANSWER_COMMANDS = {
    "lines": (_print_lines, 0),
    "count": (_print_count, 0),
    "firing": (_firing, 2),
    "delivered": (_delivered, 2),
}


def main(argv: list[str]) -> int:
    """Run one command.

    Args:
        argv: the command and its arguments, without the program name.

    Returns:
        The exit status described in the module docstring.
    """
    if len(argv) == 2 and argv[0] == "alert-line":
        print(ALERT_LINE.format(run_id=argv[1]))
        return 0
    if len(argv) >= 2 and argv[0] == "url":
        try:
            print(query_url(argv[1], argv[2:]))
        except ValueError as error:
            print(f"loki_probe: url: {error}", file=sys.stderr)
            return 2
        return 0
    if not argv or argv[0] not in _ANSWER_COMMANDS:
        print(f"loki_probe: unknown command {argv[:1]!r}", file=sys.stderr)
        return 2
    handler, arity = _ANSWER_COMMANDS[argv[0]]
    if len(argv) - 1 != arity:
        print(
            f"loki_probe: {argv[0]} takes {arity} arguments, got {len(argv) - 1}",
            file=sys.stderr,
        )
        return 2
    try:
        return handler(json.load(sys.stdin), *argv[1:])
    except (ValueError, KeyError, TypeError, IndexError) as error:
        print(f"loki_probe: {argv[0]}: unexpected answer: {error!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
