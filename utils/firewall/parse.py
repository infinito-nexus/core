"""Parse one agent-firewall rule.

A rule is ``Kind(target):actions``:

- ``Kind`` is one of channel, app, mcp, account, egress.
- ``target`` is ``name`` or ``name/resource``; it may hold ``${VAR}``
  deploy-variable references, letters, digits, ``-_.`` and ``*``.
- ``actions`` is ``crud`` (all four), ``none``, or a ``+``-joined subset of
  create, read, update, delete. ``egress`` carries no actions (``none``).

Evaluation of a rule set is deny over ask over allow, and an unmatched request
is denied; that lives in the compiler, not here. This module only parses and
validates one rule and exposes the ``${VAR}`` names it references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("channel", "app", "mcp", "account", "egress")
ACTIONS = ("create", "read", "update", "delete")
BUILTIN_PROVIDERS = ("github", "gitea", "gitlab")
_RULE = re.compile(
    r"^(?P<kind>[a-z]+)\((?P<target>[^()]+)\)(?::(?P<actions>[a-z+]+))?$"
)
_TARGET = re.compile(r"^(?:\$\{[A-Z][A-Z0-9_]*\}|[A-Za-z0-9_.*/:-])+$")
_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


@dataclass(frozen=True)
class Rule:
    kind: str
    target: str
    actions: frozenset[str]
    raw: str

    @property
    def variables(self) -> set[str]:
        return set(_VAR.findall(self.target))


def parse_rule(raw: str) -> Rule:
    """Parse ``raw`` into a :class:`Rule`, or raise ``ValueError``.

    Args:
        raw: a single rule string, e.g. ``account(github/maintainer):read``.
    """
    match = _RULE.match(raw.strip())
    if not match:
        raise ValueError(f"unparsable rule {raw!r}")
    kind = match["kind"]
    if kind not in KINDS:
        raise ValueError(f"rule {raw!r}: unknown kind {kind!r}")
    if not _TARGET.match(match["target"]):
        raise ValueError(f"rule {raw!r}: bad target {match['target']!r}")
    actions_text = match["actions"]
    if kind == "egress":
        if actions_text not in (None, "none"):
            raise ValueError(f"rule {raw!r}: egress takes no actions")
        actions: frozenset[str] = frozenset()
    elif actions_text in (None, "none"):
        actions = frozenset()
    elif actions_text == "crud":
        actions = frozenset(ACTIONS)
    else:
        parts = actions_text.split("+")
        bad = [p for p in parts if p not in ACTIONS]
        if bad:
            raise ValueError(f"rule {raw!r}: unknown actions {bad}")
        actions = frozenset(parts)
    return Rule(kind=kind, target=match["target"], actions=actions, raw=raw.strip())


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    _expect(parse_rule("egress(github.com)").kind == "egress", "egress kind not parsed")
    _expect(
        parse_rule("egress(api.github.com):none").actions == frozenset(),
        "none actions not empty",
    )
    _expect(
        parse_rule("account(github/maintainer):read").target == "github/maintainer",
        "target not parsed",
    )
    _expect(
        parse_rule("app(web-app-openproject/work_packages):crud").actions
        == frozenset(ACTIONS),
        "crud not expanded",
    )
    _expect(
        parse_rule("channel(web-app-matrix/team):create+read").actions
        == {"create", "read"},
        "action subset not parsed",
    )
    _expect(
        parse_rule("egress(${INFINITO_MATRIX_HOST})").variables
        == {
            "INFINITO_MATRIX_HOST"  # nocheck: firewall-rule example in the parser self-check, not a consumed env key
        },
        "variable not extracted",
    )
    _expect(
        parse_rule("egress(*.${INFINITO_PRIMARY_DOMAIN})").variables
        == {
            "INFINITO_PRIMARY_DOMAIN"  # nocheck: firewall-rule example in the parser self-check, not a consumed env key
        },
        "wildcard variable not extracted",
    )
    hostport = parse_rule(
        "egress(${INFINITO_BIND_IP}:${INFINITO_TOOLS_LIBRETRANSLATE_PORT})"
    )
    _expect(
        hostport.variables
        == {"INFINITO_BIND_IP", "INFINITO_TOOLS_LIBRETRANSLATE_PORT"},
        hostport,
    )
    for bad in (
        "app():read",
        "wizard(x):read",
        "app(x):fly",
        "egress(h):read",
        "app(x y):read",
    ):
        try:
            parse_rule(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected {bad!r} to fail")
    print("firewall parse self-check ok")


if __name__ == "__main__":
    _demo()
