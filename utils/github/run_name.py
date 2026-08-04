"""Recover a manual CI run's inputs from its run name.

``entry-manual.yml`` declares a ``run-name:`` that interpolates the dispatch
inputs. Once a run has started, that title is the only record of them: the
REST API answers ``inputs: null`` for a workflow_dispatch run. Anything that
wants to know what a run was dispatched with therefore parses the title — and
parsing it against a hand-copied format would drift the moment the workflow
changes, silently and without a failing test.

So the format is read from the workflow itself and the literals that frame an
input are derived, never spelled out here.
"""

from __future__ import annotations

import re

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "entry-manual.yml"

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


def template() -> str:
    """The raw ``run-name:`` string declared by the manual CI workflow."""
    declared = load_yaml(str(WORKFLOW)).get("run-name")
    if not declared:
        raise ValueError(f"{WORKFLOW} declares no run-name")
    return str(declared)


def _split(tpl: str) -> tuple[list[str], list[str]]:
    """Alternating pieces of a run-name template.

    Args:
        tpl: run-name template text.

    Returns:
        ``(literals, expressions)`` with ``len(literals) ==
        len(expressions) + 1``; ``literals[i]`` precedes ``expressions[i]``.
    """
    cursor = 0
    literals: list[str] = []
    expressions: list[str] = []
    for match in _EXPRESSION.finditer(tpl):
        literals.append(tpl[cursor : match.start()])
        expressions.append(match.group(1).strip())
        cursor = match.end()
    literals.append(tpl[cursor:])
    return literals, expressions


def _openings_after(
    literals: list[str], expressions: list[str], index: int
) -> list[str]:
    """Literal texts any later segment can start with.

    Args:
        literals: template literals from :func:`_split`.
        expressions: template expressions from :func:`_split`.
        index: expression position after which segments are inspected.

    Returns:
        Every non-empty rendering a later segment can open with: the leading
        literal of each quoted string inside later expressions (format
        placeholders stripped) and each later inter-expression literal.
    """
    openings: list[str] = []
    for j in range(index + 1, len(expressions)):
        for quoted in re.findall(r"'([^']*)'", expressions[j]):
            head = quoted.split("{", 1)[0].strip()
            if head:
                openings.append(head)
        trailing = literals[j + 1].strip()
        if trailing:
            openings.append(trailing)
    return openings


def frame(input_name: str, tpl: str | None = None) -> tuple[str, str]:
    """Literal text surrounding ``inputs.<input_name>`` in the run name.

    Args:
        input_name: dispatch input interpolated on its own, e.g. ``distros``.
        tpl: run-name to read; defaults to the declared one.

    Returns:
        ``(before, after)``. Either side is empty when the expression sits at
        a boundary of the template.

    Raises:
        ValueError: the input is not interpolated bare anywhere in the run
            name, so no literal frame identifies its value.
    """
    tpl = template() if tpl is None else tpl
    literals, expressions = _split(tpl)
    wanted = f"inputs.{input_name}"
    for index, expression in enumerate(expressions):
        if expression == wanted:
            return literals[index], literals[index + 1]
    raise ValueError(f"{wanted} is not interpolated on its own in: {tpl}")


def title_with(
    input_name: str, value: str, tail: str = "", tpl: str | None = None
) -> str:
    """A run name in which *input_name* holds *value*.

    Args:
        input_name: dispatch input to place.
        value: what it held.
        tail: whatever the workflow renders after this input's own separator.
        tpl: run-name to read; defaults to the declared one.
    """
    before, after = frame(input_name, tpl)
    return f"{before}{value}{after}{tail}"


def value_from_title(title: str, input_name: str, tpl: str | None = None) -> str:
    """Value ``input_name`` held when the run named *title* was dispatched.

    Returns an empty string when *title* does not follow the run name at all —
    a run from another entry point carries an unrelated title, and guessing a
    value for it would be worse than admitting ignorance.

    The value's end is the literal that follows it in the template; when that
    literal is only whitespace, the earliest opening any later segment can
    render (:func:`_openings_after`) terminates the value instead.
    """
    tpl = template() if tpl is None else tpl
    literals, expressions = _split(tpl)
    wanted = f"inputs.{input_name}"
    try:
        index = expressions.index(wanted)
    except ValueError:
        raise ValueError(f"{wanted} is not interpolated on its own in: {tpl}") from None
    before, after = literals[index], literals[index + 1]
    if not title.startswith(before):
        return ""
    rest = title[len(before) :]
    if after.strip():
        rest = rest.split(after, 1)[0]
    else:
        cuts = [
            found
            for found in (
                rest.find(opening)
                for opening in _openings_after(literals, expressions, index)
            )
            if found != -1
        ]
        if cuts:
            rest = rest[: min(cuts)]
    return " ".join(rest.split())
