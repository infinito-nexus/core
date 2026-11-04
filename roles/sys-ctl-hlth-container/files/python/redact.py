"""Redact secrets from log text with the shared LOG_REDACTION_RULES.

Usage::

    redact.py RULES_JSON < log.txt > redacted.txt
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def load_rules(document: dict) -> tuple[str, list[re.Pattern[str]]]:
    """Compile the rules of a rendered rules document.

    Args:
        document: mapping with ``replacement`` (str) and ``rules`` (list of
            ``{name, pattern}``).

    Returns:
        The replacement text and the compiled patterns, in document order;
        group 1 of each pattern is the secret.

    Raises:
        ValueError: a pattern does not hold exactly one capture group.
    """
    replacement = document["replacement"]
    rules = []
    for entry in document["rules"]:
        pattern = re.compile(entry["pattern"])
        if pattern.groups != 1:
            raise ValueError(
                f"redaction rule {entry['name']!r} must hold exactly one "
                f"capture group, it holds {pattern.groups}"
            )
        rules.append(pattern)
    return replacement, rules


def redact(text: str, replacement: str, rules: list[re.Pattern[str]]) -> str:
    """Replace the secret group of every rule match in *text*.

    Args:
        text: the log text.
        replacement: the text written over each secret.
        rules: the compiled patterns, applied in order.

    Returns:
        *text* with every secret replaced.
    """

    def mask(match: re.Match[str]) -> str:
        whole = match.group(0)
        start = match.start(1) - match.start(0)
        end = match.end(1) - match.start(0)
        return whole[:start] + replacement + whole[end:]

    for pattern in rules:
        text = pattern.sub(mask, text)
    return text


def main(argv: list[str]) -> int:
    """Filter stdin to stdout.

    Args:
        argv: ``[program, rules_json_path]``.
    """
    if len(argv) != 2:
        print("usage: redact.py RULES_JSON", file=sys.stderr)
        return 2
    replacement, rules = load_rules(json.loads(Path(argv[1]).read_text()))
    for line in sys.stdin:
        sys.stdout.write(redact(line, replacement, rules))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
