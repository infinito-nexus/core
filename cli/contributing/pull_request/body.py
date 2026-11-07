from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jinja2 import Environment, StrictUndefined, meta, nodes, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATE = PROJECT_ROOT / ".github" / "pull_request_template.md.j2"
DEFAULT = PROJECT_ROOT / ".github" / "pull_request_template.md"
AREA_DIR = PROJECT_ROOT / ".github" / "PULL_REQUEST_TEMPLATE"
AUDIENCES = ("agent", "human")
INTENTS = ("feature", "fix")
SEMVERS = ("major", "minor", "patch")
TEXTS = ("title", "summary", "details", "evidence", "notes", "score_table")
LISTS = (
    "closes",
    "components",
    "roles",
    "checks",
    "review_focus",
    "integrations",
    "files",
)
_SEPARATOR = re.compile(r"\|(?: *:?-{3,}:? *\|)+")
_PIPE = re.compile(r"(?<!\\)\|")

HUMAN_VALUES = {
    "audience": "human",
    "scope": "general",
    "title": None,
    "summary": None,
    "closes": [],
    "intent": None,
    "components": [],
    "integrations": [],
    "files": [],
    "roles": [],
    "semver": None,
    "details": None,
    "checks": [],
    "evidence": None,
    "security_impact": None,
    "security_notes": None,
    "review_focus": [],
    "score_table": None,
    "dod": False,
    "notes": None,
}


class TemplateError(ValueError):
    """The values do not satisfy the template contract."""


def environment() -> Environment:
    """Return the Jinja environment the contract fixes for this template."""
    return Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=select_autoescape(["html", "xml"], default_for_string=False),
    )


def _source(template: Path) -> str:
    return read_text(str(template))


def variables(template: Path = TEMPLATE) -> frozenset[str]:
    """Return every variable the template reads, the full contract set."""
    return frozenset(
        meta.find_undeclared_variables(environment().parse(_source(template)))
    )


def areas(template: Path = TEMPLATE) -> dict:
    """Return the template's ``AREAS`` mapping as plain Python data."""
    for assign in environment().parse(_source(template)).find_all(nodes.Assign):
        if isinstance(assign.target, nodes.Name) and assign.target.name == "AREAS":
            return assign.node.as_const()
    raise TemplateError(f"{template} defines no AREAS mapping")


def markdown_table(text: str) -> list[list[str]]:
    """Return the cell rows of a Markdown table, header first.

    Raises:
        TemplateError: ``text`` is not one header row, one separator row and at
            least one data row of the same width.
    """
    lines = text.strip("\n").split("\n")
    if len(lines) < 3:
        raise TemplateError(
            f"a Markdown table needs a header, a separator and a row, got {len(lines)} line(s)"
        )
    if not all(line.startswith("|") and line.endswith("|") for line in lines):
        raise TemplateError("every Markdown table line must start and end with '|'")
    if not _SEPARATOR.fullmatch(lines[1]):
        raise TemplateError(f"line 2 is not a Markdown table separator: {lines[1]!r}")
    cells = [[cell.strip() for cell in _PIPE.split(line)[1:-1]] for line in lines]
    widths = sorted({len(row) for row in cells})
    if len(widths) != 1:
        raise TemplateError(f"Markdown table rows differ in width: {widths}")
    return [cells[0], *cells[2:]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TemplateError(message)


def validate(values: dict, template: Path = TEMPLATE) -> None:
    """Check ``values`` against the contract before rendering.

    Args:
        values: one entry per template variable, see the contract table in
            ``docs/contributing/artefact/git/pull-request.md``.
        template: the template whose variables and ``AREAS`` apply.

    Raises:
        TemplateError: a variable is missing or unknown, or a value breaks the
            contract of its audience.
    """
    expected = variables(template)
    missing = sorted(expected - values.keys())
    unknown = sorted(values.keys() - expected)
    _require(not missing, f"missing template variable(s): {', '.join(missing)}")
    _require(not unknown, f"unknown template variable(s): {', '.join(unknown)}")
    _require(values["audience"] in AUDIENCES, f"audience must be one of {AUDIENCES}")
    known = areas(template)
    _require(values["scope"] in known, f"scope must be one of {tuple(known)}")
    for name in LISTS:
        _require(isinstance(values[name], list), f"{name} must be a list")
    _require(
        all(isinstance(n, int) and n > 0 for n in values["closes"]),
        "closes must hold issue numbers",
    )
    _require(isinstance(values["dod"], bool), "dod must be true or false")
    area = known[values["scope"]]
    _subset(values, "checks", [row[0] for row in area["checks"]])
    _subset(values, "integrations", area["integrations"])
    _subset(values, "files", [row[0] for row in area["files"] + area["registered"]])
    _require(
        not values["roles"] or area["subset"] is not None,
        f"scope {values['scope']} has no subset roles block",
    )
    if values["audience"] == "agent":
        _agent(values)
    if values["score_table"] is not None:
        markdown_table(values["score_table"])


def _subset(values: dict, name: str, allowed: list[str]) -> None:
    stray = sorted(set(values[name]) - set(allowed))
    _require(
        not stray,
        f"{name} of scope {values['scope']} has no {', '.join(stray)}; allowed: {', '.join(allowed)}",
    )


def _agent(values: dict) -> None:
    for name in TEXTS:
        text = values[name]
        _require(
            isinstance(text, str) and text.strip() != "",
            f"{name} is required for the agent audience",
        )
    _require(
        values["components"] != [], "components is required for the agent audience"
    )
    _require(values["intent"] in INTENTS, f"intent must be one of {INTENTS}")
    _require(values["semver"] in SEMVERS, f"semver must be one of {SEMVERS}")
    impact = values["security_impact"]
    _require(isinstance(impact, bool), "security_impact must be true or false")
    notes = values["security_notes"]
    if impact:
        _require(
            isinstance(notes, str) and notes.strip() != "",
            "security_notes is required when security_impact is true",
        )
    else:
        _require(
            notes is None, "security_notes must be null when security_impact is false"
        )


def render(values: dict, template: Path = TEMPLATE) -> str:
    """Validate ``values`` and return the rendered pull request body."""
    validate(values, template)
    return environment().from_string(_source(template)).render(**values)


def generated(template: Path = TEMPLATE) -> dict[Path, str]:
    """Return every GitHub web template rendered for the human audience."""
    files = {}
    for scope in areas(template):
        path = DEFAULT if scope == "general" else AREA_DIR / f"{scope}.md"
        files[path] = render({**HUMAN_VALUES, "scope": scope}, template)
    return files


def stale(expected: dict[Path, str] | None = None) -> list[str]:
    """Return why each generated file differs from its render, empty when all are current.

    Args:
        expected: generated path to rendered text; ``generated()`` when omitted.
    """
    reasons = []
    for path, text in (generated() if expected is None else expected).items():
        if not path.is_file():
            reasons.append(f"{path} is missing")
        elif read_text(str(path)) != text:
            reasons.append(f"{path} is not the current render of {TEMPLATE}")
    return reasons
