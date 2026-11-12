"""Lint guard: every ``meta/forms.yml`` follows the managed-field schema.

Each form names its admin page ``path`` and its ``fields``; each field names
its inventory ``source``, its ``mode`` (``enforced`` or ``seeded``) and its
input ``selector``, optionally ``when``, ``label``, ``type``, ``enum``,
``validation`` and ``description``. A ``source`` or ``when`` resolves against
the role's ``applications.<role>`` defaults or a credential its
``meta/secrets.yml`` declares; a path under ``users`` must be exactly
``users.<key>.<attr>`` with an attr other than ``tokens``, and resolves
against the global user defaults; ``sso.<claim>`` names a claim of
``OIDC.ATTRIBUTES`` on an ``enforced`` field without ``when``. The schema lives
in ``utils.roles.applications.forms`` and ``utils.roles.applications.sso_fields``.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, TemplateSyntaxError, nodes

from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.users import get_user_defaults
from utils.roles.applications import forms, sso_fields
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_VARS_MAIN,
)

from . import load_role_meta, role_dirs

if TYPE_CHECKING:
    from pathlib import Path

FORM_VALUES = re.compile(
    r"""lookup\(\s*['"]form_values['"]\s*,\s*application_id\s*,\s*['"]([^'"]+)['"]"""
)
ROLE_SOURCE_SUFFIXES = frozenset({".yml", ".yaml", ".j2"})
FORM_VALUES_LOOKUP = "form_values"
FORM_VALUES_TERM = "application_id"
SINK_FILTER_OPTIONS = {"combine": frozenset({"recursive", "list_merge"})}
JINJA = Environment(autoescape=True)


def _credentials(role: Path) -> dict[str, Any]:
    secrets = load_role_meta(role / ROLE_FILE_META_SECRETS)
    credentials = secrets.get("credentials") if isinstance(secrets, dict) else None
    return credentials if isinstance(credentials, dict) else {}


def findings(
    roles: list[Path], defaults: dict[str, Any], users: dict[str, Any]
) -> list[str]:
    """Return every schema and resolution finding of the roles' forms files.

    Args:
        roles: role directories to check; a role without the file is skipped.
        defaults: ``applications`` defaults keyed by role.
        users: the global user defaults.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        schema = forms.schema_errors(role.name, data)
        errors.extend(schema)
        if isinstance(data, dict):
            errors.extend(
                forms.source_errors(
                    role.name,
                    data,
                    defaults.get(role.name, {}),
                    users,
                    _credentials(role),
                )
            )
            errors.extend(sso_fields.errors(role.name, data))
    return errors


def _converged_forms(role: Path) -> set[str]:
    return {
        form
        for path in sorted(role.rglob("*"))
        if path.suffix in ROLE_SOURCE_SUFFIXES and path.is_file()
        for form in FORM_VALUES.findall(read_text(str(path)))
    }


def convergence_findings(roles: list[Path]) -> list[str]:
    """Return every form a role declares but does not converge, or converges undeclared.

    Args:
        roles: role directories to check; a form of ``sso.<claim>`` fields
            only needs no converge.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        declared = (
            {form for form, block in data.items() if not sso_fields.only_sso(block)}
            if isinstance(data, dict)
            else set()
        )
        converged = _converged_forms(role)
        errors.extend(
            f"{role.name}: {ROLE_FILE_META_FORMS} declares the form {form!r}, but no "
            f"lookup('form_values', application_id, '{form}') converges it"
            for form in sorted(declared - converged)
        )
        errors.extend(
            f"{role.name}: lookup('form_values', application_id, '{form}') converges "
            f"a form {ROLE_FILE_META_FORMS} does not declare"
            for form in sorted(converged - declared)
        )
    return errors


@dataclass
class _Sink:
    name: str
    naming: frozenset[str]
    definitions: dict[str, Any]
    read: set[str] = field(default_factory=set)


def _sinks_by_name(data: dict[str, Any]) -> dict[str, list[str]]:
    named: dict[str, list[str]] = {}
    for form, block in data.items():
        sinks = block.get("sinks") if isinstance(block, dict) else None
        for sink in sinks if isinstance(sinks, list) else []:
            if isinstance(sink, str):
                named.setdefault(sink, []).append(str(form))
    return named


def _lookup_findings(sink: _Sink, where: str, call: nodes.Call) -> list[str]:
    plugin = (
        call.args[0].value
        if call.args and isinstance(call.args[0], nodes.Const)
        else None
    )
    if plugin != FORM_VALUES_LOOKUP:
        named = (
            f"lookup({plugin!r})"
            if isinstance(plugin, str)
            else "a lookup named by an expression"
        )
        return [f"{where} reads {named}"]
    terms = call.args[1:]
    if (
        len(terms) != 2
        or not (isinstance(terms[0], nodes.Name) and terms[0].name == FORM_VALUES_TERM)
        or not (isinstance(terms[1], nodes.Const) and isinstance(terms[1].value, str))
        or call.dyn_args is not None
        or call.dyn_kwargs is not None
        or any(
            keyword.key != "mode"
            or not isinstance(keyword.value, nodes.Const)
            or keyword.value.value not in forms.MODES
            for keyword in call.kwargs
        )
    ):
        return [f"{where} must read lookup('form_values', application_id, '<form>')"]
    form = terms[1].value
    sink.read.add(form)
    if form not in sink.naming:
        return [f"{where} reads the form {form!r}, whose sinks do not name {sink.name}"]
    return []


def _filter_findings(
    sink: _Sink, where: str, node: nodes.Filter, chain: tuple[str, ...]
) -> list[str]:
    options = SINK_FILTER_OPTIONS.get(node.name)
    if options is None or node.node is None:
        return [f"{where} applies the filter {node.name!r}"]
    if (
        node.dyn_args is not None
        or node.dyn_kwargs is not None
        or any(
            keyword.key not in options or not isinstance(keyword.value, nodes.Const)
            for keyword in node.kwargs
        )
    ):
        return [f"{where} passes {node.name} an option it does not take"]
    findings = _value_findings(sink, where, node.node, chain)
    for argument in node.args:
        findings.extend(_value_findings(sink, where, argument, chain))
    return findings


def _value_findings(
    sink: _Sink, where: str, node: nodes.Node, chain: tuple[str, ...]
) -> list[str]:
    if (
        isinstance(node, nodes.Call)
        and isinstance(node.node, nodes.Name)
        and node.node.name == "lookup"
    ):
        return _lookup_findings(sink, where, node)
    if isinstance(node, nodes.Filter):
        return _filter_findings(sink, where, node, chain)
    if isinstance(node, nodes.Getattr) or (
        isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const)
    ):
        return _value_findings(sink, where, node.node, chain)
    if isinstance(node, nodes.Name):
        if node.name in chain:
            return [f"{where} reads {node.name} in a cycle"]
        if node.name not in sink.definitions:
            return [
                f"{where} reads {node.name}, which {ROLE_FILE_VARS_MAIN} does not define"
            ]
        return _template_findings(
            sink,
            f"{where} through {node.name}",
            sink.definitions[node.name],
            (*chain, node.name),
        )
    if isinstance(node, nodes.Dict):
        keys = [
            str(item.key.value)
            for item in node.items
            if isinstance(item.key, nodes.Const)
        ]
        return [
            f"{where} writes a literal" + (f" to {', '.join(keys)}" if keys else "")
        ]
    if isinstance(node, (nodes.Literal, nodes.TemplateData)):
        return [f"{where} writes a literal"]
    return [f"{where} computes a {type(node).__name__} expression"]


def _template_findings(
    sink: _Sink, where: str, definition: Any, chain: tuple[str, ...]
) -> list[str]:
    if not isinstance(definition, str):
        return [f"{where} writes a literal"]
    try:
        tree = JINJA.parse(definition)
    except TemplateSyntaxError:
        return [f"{where} is no valid Jinja"]
    if any(not isinstance(node, nodes.Output) for node in tree.body):
        return [f"{where} holds a statement"]
    parts = [part for output in tree.body for part in output.nodes]
    expressions = [part for part in parts if not isinstance(part, nodes.TemplateData)]
    if not expressions:
        return [f"{where} writes a literal"]
    if len(expressions) > 1 or any(
        isinstance(part, nodes.TemplateData) and part.data.strip() for part in parts
    ):
        return [f"{where} must be exactly one expression"]
    return _value_findings(sink, where, expressions[0], chain)


def sink_findings(roles: list[Path]) -> list[str]:
    """Return every sink value no ``lookup('form_values', ...)`` reads, and every form no sink converges.

    Args:
        roles: role directories to check; a form of ``sso.<claim>`` fields
            only names no sink.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        if not isinstance(data, dict):
            continue
        definitions = load_role_meta(role / ROLE_FILE_VARS_MAIN)
        definitions = definitions if isinstance(definitions, dict) else {}
        errors.extend(
            f"{role.name}: the form {form!r} names no sinks"
            for form, block in data.items()
            if isinstance(block, dict)
            and "sinks" not in block
            and not sso_fields.only_sso(block)
        )
        for name, naming in _sinks_by_name(data).items():
            where = f"{role.name}: sink {name}"
            if name not in definitions:
                errors.append(f"{where} is not defined in {ROLE_FILE_VARS_MAIN}")
                continue
            sink = _Sink(name, frozenset(naming), definitions)
            found = _template_findings(sink, where, definitions[name], (name,))
            errors.extend(found)
            errors.extend(
                f"{where} never reads the form {form!r}, which names it"
                for form in naming
                if not found and form not in sink.read
            )
    return errors


class TestForms(unittest.TestCase):
    def _roles(self) -> list[Path]:
        roles = [
            role for role in role_dirs() if (role / ROLE_FILE_META_FORMS).is_file()
        ]
        if not roles:
            self.skipTest(f"no role ships {ROLE_FILE_META_FORMS} yet")
        return roles

    def test_every_forms_file_follows_the_schema_and_resolves(self) -> None:
        self.assertEqual(
            [],
            findings(self._roles(), get_application_defaults(), get_user_defaults()),
        )

    def test_every_role_converges_exactly_the_forms_it_declares(self) -> None:
        self.assertEqual([], convergence_findings(self._roles()))

    def test_every_sink_takes_its_values_only_from_its_forms(self) -> None:
        self.assertEqual([], sink_findings(self._roles()))


if __name__ == "__main__":
    unittest.main()
