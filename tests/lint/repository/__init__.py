import re
import shlex
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

_CONTINUATION = re.compile(r"\\\n")
_CONTROL_OPERATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")"})


def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Args:
        text: a Dockerfile.

    Returns:
        ``(keyword, arguments)`` of every instruction, comment lines dropped and
        backslash continuations joined.
    """
    kept = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    instructions: list[tuple[str, str]] = []
    for line in _CONTINUATION.sub(" ", kept).splitlines():
        keyword, _, arguments = line.strip().partition(" ")
        if keyword:
            instructions.append((keyword.upper(), arguments.strip()))
    return instructions


def shell_commands(script: str) -> list[list[str]]:
    """Args:
        script: shell source.

    Returns:
        The argv of every simple command, split at control operators and line
        ends, backslash continuations joined and comments dropped.
    """
    commands: list[list[str]] = []
    for line in _CONTINUATION.sub(" ", script).splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        for token in [*lexer, ";"]:
            if token not in _CONTROL_OPERATORS:
                current.append(token)
            elif current:
                commands.append(current)
                current = []
    return commands


def dockerfile_commands(text: str) -> list[list[str]]:
    """Args:
        text: a Dockerfile.

    Returns:
        The argv of every simple command its ``RUN`` instructions execute.
    """
    return [
        argv
        for keyword, arguments in dockerfile_instructions(text)
        if keyword == "RUN"
        for argv in shell_commands(arguments)
    ]


__all__ = [
    "PROJECT_ROOT",
    "dockerfile_commands",
    "dockerfile_instructions",
    "shell_commands",
]
