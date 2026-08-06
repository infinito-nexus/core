"""Recover a manual CI run's inputs from its run name.

``entry-manual.yml`` declares a ``run-name:`` that interpolates the dispatch
inputs. Once a run has started, that title is the only record of them: the
REST API answers ``inputs: null`` for a workflow_dispatch run. Anything that
wants to know what a run was dispatched with therefore parses the title — and
parsing it against a hand-copied format would drift the moment the workflow
changes, silently and without a failing test.

So the format is read from the workflow itself. Every input renders as one
segment, ``<head><value> ``, where the head is the emoji the workflow's own
``format('🐧{0} ', …)`` prefixes the value with. An input holding its default
renders no segment at all, so a title carries only what deviates — and an
absent input means "the workflow's default", which is exactly what a
retrigger should leave alone.
"""

from __future__ import annotations

import re

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "entry-manual.yml"

VALUE_GLYPHS = {"是": "true", "否": "false", "序": "serial", "并": "parallel"}

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_QUOTED = re.compile(r"'([^']*)'")
_COMPARED = re.compile(r"[!=]=\s*'([^']*)'")
_INPUT = re.compile(r"inputs\.([A-Za-z_][A-Za-z0-9_]*)")
_PLACEHOLDER = "{0}"


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


def segments(tpl: str | None = None) -> list[tuple[str, str, bool]]:
    """``(input name, opening literal, is_marker)`` per rendered segment, in
    template order.

    A value segment interpolates its input through a ``format()``
    placeholder and opens with the format string up to ``{0}``. A marker
    segment carries no value at all: its literal shows only that the input
    was set, and its absence is the other state.
    """
    tpl = template() if tpl is None else tpl
    _literals, expressions = _split(tpl)
    out: list[tuple[str, str, bool]] = []
    for expression in expressions:
        names = set(_INPUT.findall(expression))
        if len(names) != 1:
            continue
        quoted = _QUOTED.findall(expression)
        placeholder = next((q for q in quoted if _PLACEHOLDER in q), None)
        if placeholder is not None:
            out.append((names.pop(), placeholder.split(_PLACEHOLDER, 1)[0], False))
            continue
        compared = set(_COMPARED.findall(expression))
        literal = next(
            (q.strip() for q in quoted if q.strip() and q not in compared), ""
        )
        if literal:
            out.append((names.pop(), literal, True))
    return out


def heads(tpl: str | None = None) -> dict[str, str]:
    """Input name -> the literal its value segment opens with, template order."""
    return {name: literal for name, literal, marker in segments(tpl) if not marker}


def markers(tpl: str | None = None) -> dict[str, str]:
    """Input name -> the literal its marker segment renders when set."""
    return {name: literal for name, literal, marker in segments(tpl) if marker}


def openings(tpl: str | None = None) -> set[str]:
    """Every literal a rendered segment can start with, so any of them ends
    the value before it.

    Comparison operands (``inputs.workspace != 'auto'``) and the glyphs a
    value renders as are excluded: they are what the template tests and emits,
    never what a segment opens with.
    """
    tpl = template() if tpl is None else tpl
    literals, expressions = _split(tpl)
    found: set[str] = {literal.strip() for literal in literals}
    for expression in expressions:
        compared = set(_COMPARED.findall(expression))
        for quoted in _QUOTED.findall(expression):
            if quoted in compared or quoted in VALUE_GLYPHS:
                continue
            found.add(quoted.split(_PLACEHOLDER, 1)[0].strip())
    return {opening for opening in found if opening}


def value_from_title(title: str, input_name: str, tpl: str | None = None) -> str:
    """Value ``input_name`` held when the run named *title* was dispatched.

    Returns an empty string when the title carries no segment for the input —
    it was dispatched with the workflow's default, or the title comes from
    another entry point entirely and records nothing at all.

    Raises:
        ValueError: the run name renders no segment for this input, so no
            title could ever carry its value.
    """
    tpl = template() if tpl is None else tpl
    all_heads = heads(tpl)
    if input_name not in all_heads:
        raise ValueError(f"inputs.{input_name} renders no segment in: {tpl}")
    head = all_heads[input_name]
    start = title.find(head)
    if start == -1:
        return ""
    rest = title[start + len(head) :]
    cuts = [
        found
        for found in (
            rest.find(opening) for opening in openings(tpl) - {head} if opening
        )
        if found != -1
    ]
    if cuts:
        rest = rest[: min(cuts)]
    value = " ".join(rest.split())
    return VALUE_GLYPHS.get(value, value)


def values_from_title(title: str, tpl: str | None = None) -> dict[str, str]:
    """Every input the run named *title* records, keyed by input name.

    Value inputs left on their default render no segment and are absent. A
    marker input is always reported, ``'true'`` or ``'false'`` by the
    marker's presence — which is why a title that does not open with the run
    name's own prefix yields nothing at all rather than a title-wide 'false'.
    """
    tpl = template() if tpl is None else tpl
    literals, _expressions = _split(tpl)
    if not title.startswith(literals[0].strip()):
        return {}
    found = {name: value_from_title(title, name, tpl) for name in heads(tpl)}
    found = {name: value for name, value in found.items() if value}
    found.update(
        {
            name: "true" if literal in title else "false"
            for name, literal in markers(tpl).items()
        }
    )
    return found
