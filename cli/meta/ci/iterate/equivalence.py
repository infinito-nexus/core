"""Whether an edit changes what a file means or only how it is written.

Python compares the parsed tree plus a leading ``#`` line (a shebang or a
coding cookie), so comments, blank lines, quotes and line wraps drop out
while a changed docstring or interpreter still counts. YAML and JSON compare
the loaded data with mapping order kept and every scalar tagged with its
type: a template that iterates a mapping renders its keys in file order, and
``1``, ``1.0`` and ``true`` load equal in Python but render differently. YAML
and JSON under a role's ``files/`` or ``templates/`` ship to a program whose
parser may read ``on``, ``1.10`` or a duplicate key otherwise, so only an
identical text is format-only there. The same holds for a text carrying a
comment a deploy or a deployed program reads (:data:`READ_COMMENTS`): dropping
comments would hide an edit of it. Those comments are a Python coding cookie
and the ``WANT_JSON`` marker Ansible reads in a module, the
``# variant-pin:`` of :mod:`utils.roles.applications.variant.pins` and the
``# nocheck:`` rules
whose reader is not a lint: ``inventory-open-subtree``
(:mod:`cli.administration.inventory.validate.open_subtrees`) and
``inventory-variable``
(:mod:`cli.administration.inventory.validate.variables`), which the inventory
validator of every dedicated deploy reads, and ``header-trust``
(:mod:`utils.roles.header_trust`) and ``license-declared``
(:mod:`utils.licensing.roles`), which the docs build of ``web-app-docs``
renders.
Every other file kind, an added or deleted file and a side that does not
parse count as a real change, which keeps the classifier from cutting what it
cannot read.

Any other lint directive (``# nocheck:``, ``# noqa``, ``# type: ignore`` and
the like) changes no meaning but does change what the lint suite reports;
:func:`directives_changed` tells the classifier to route such an edit there.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

import yaml

from utils.cache.yaml import load_yaml_all_str

PYTHON = (".py",)
YAML = (".yml", ".yaml")
JSON = (".json",)
SUFFIXES = PYTHON + YAML + JSON
SHIPPED = re.compile(r"^roles/[^/]+/(?:files|templates)/")
DEPLOY_READ_RULES = (
    "inventory-open-subtree",
    "inventory-variable",
    "header-trust",
    "license-declared",
)
READ_COMMENTS = re.compile(
    r"#\s*(?:variant-pin\b|(?:nocheck|noqa)\s*:\s*(?:[\w-]+\s*,\s*)*(?:"
    + "|".join(DEPLOY_READ_RULES)
    + r")(?![\w-]))"
    r"|\bWANT_JSON\b|^[ \t\f]*#.*?coding[:=]",
    re.IGNORECASE | re.MULTILINE,
)
DIRECTIVE = re.compile(
    r"#\s*(?:nocheck|noqa|nosec|type:\s*ignore|pragma|shellcheck|pylint|fmt:|ruff:"
    r"|yamllint|isort:|pyright:)[^\n]*"
)


def _ordered(data: Any) -> Any:
    if isinstance(data, dict):
        return (
            "mapping",
            tuple((_ordered(key), _ordered(value)) for key, value in data.items()),
        )
    if isinstance(data, list):
        return ("sequence", tuple(_ordered(item) for item in data))
    return (type(data).__name__, data)


def _meaning(path: str, text: str) -> Any:
    if path.endswith(PYTHON):
        first = text.split("\n", 1)[0]
        return (first if first.startswith("#") else "", ast.dump(ast.parse(text)))
    if path.endswith(YAML):
        return _ordered(load_yaml_all_str(text))
    return _ordered(json.loads(text))


def equivalent(path: str, old: str | None, new: str | None) -> bool:
    """Return True when *old* and *new* mean the same for *path*'s file kind.

    Args:
        path: repository-relative path; its suffix picks the parser.
        old: the content at the base, None for an added file.
        new: the content at the head, None for a deleted file.
    """
    if old is None or new is None or not path.endswith(SUFFIXES):
        return False
    if old == new:
        return True
    if path.endswith(YAML + JSON) and SHIPPED.match(path):
        return False
    if READ_COMMENTS.search(old) or READ_COMMENTS.search(new):
        return False
    try:
        return _meaning(path, old) == _meaning(path, new)
    except (SyntaxError, ValueError, yaml.YAMLError):
        return False


def directives_changed(old: str | None, new: str | None) -> bool:
    """Return True when the lint directives of two texts differ.

    Args:
        old: the content at the base, None for an added file.
        new: the content at the head, None for a deleted file.
    """
    found = [sorted(DIRECTIVE.findall(text or "")) for text in (old, new)]
    return found[0] != found[1]
