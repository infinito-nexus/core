from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, TemplateSyntaxError, nodes

from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.users import get_user_defaults
from utils.roles.applications import form_schema, forms, sso_fields
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_PLAYWRIGHT_SPEC,
    ROLE_FILE_VARS_MAIN,
)

from . import load_role_meta, role_dirs, role_files
from .test_sso_profile_lock import ROLE_SCRIPT, SHARED_RENDERER

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FORM_VALUES = re.compile(
    r"""lookup\(\s*['"]form_values['"]\s*,\s*application_id\s*,\s*['"]([^'"]+)['"]"""
)
ROLE_SOURCE_SUFFIXES = frozenset({".yml", ".yaml", ".j2"})
FORM_VALUES_LOOKUP = "form_values"
FORM_VALUES_TERM = "application_id"
SINK_FILTER_OPTIONS = {"combine": frozenset({"recursive", "list_merge"})}
JINJA = Environment(autoescape=True)
SCRIPT_DIRS = ("files", "templates")
SCRIPT_TEMPLATE_SUFFIX = ".j2"
SCRIPT_SKIPPED_DIR = ROLE_FILE_PLAYWRIGHT_SPEC.rsplit("/", 1)[0] + "/"
SCRIPT_SINK_FILTERS = frozenset({"bool", "int", "lower", "quote", "string", "to_json"})
SCRIPT_WRITES = {
    ".py": (
        r"""['"]{key}['"]\s*:\s*""",
        r"""\[\s*['"]{key}['"]\s*\]\s*=(?!=)\s*""",
        r"""\b{key}\s*=(?!=)\s*""",
    ),
    ".php": (
        r"""['"]{key}['"]\s*=>\s*""",
        r"""\[\s*['"]{key}['"]\s*\]\s*=(?!=)\s*""",
        r"""->{key}\s*=(?!=)\s*""",
        r"""\b(?:update_(?:site_)?option|set_config)\(\s*['"]{key}['"]\s*,\s*""",
    ),
    ".rb": (
        r"""['"]{key}['"]\s*=>\s*""",
        r"""\b{key}:(?!:)\s*""",
        r"""\.{key}\s*=(?!=)\s*""",
        r"""\[\s*:{key}\s*\]\s*=(?!=)\s*""",
        r"""\[\s*['"]{key}['"]\s*\]\s*=(?!=)\s*""",
    ),
    ".js": (
        r"""['"]{key}['"]\s*:\s*""",
        r"""\b{key}:\s*""",
        r"""\.{key}\s*=(?!=)\s*""",
        r"""\[\s*['"]{key}['"]\s*\]\s*=(?!=)\s*""",
    ),
    ".sh": (
        r"""\b{key}=""",
        r"""--{key}[= ]\s*""",
        r"""\boption update {key}\s+""",
    ),
}
_QUOTED = r"'(?:[^'\\\n]|\\.)*'|" + r'"(?:[^"$#\\\n]|\\.|#(?!\{))*"'
_SCALAR = (
    _QUOTED + r"|-?\d+(?:\.\d+)?\b"
    r"|(?:true|false|True|False|TRUE|FALSE|null|None|nil|NULL|undefined)\b"
)
_LIST = rf"\[\s*(?:(?:{_SCALAR})(?:\s*,\s*(?:{_SCALAR}))*\s*,?\s*)?\]"
_ARRAY = rf"array\(\s*(?:(?:{_SCALAR})(?:\s*,\s*(?:{_SCALAR}))*\s*,?\s*)?\)"
_BACKTICK = r"`[^`$\\\n]*`"
_EMPTY_MAP = r"\{\s*\}"
_END = r"(?=[ \t]*(?:$|[,;)\]}&|]|#|//|\b(?:if|unless)\b))"
SCRIPT_LITERALS = {
    language: re.compile(f"(?:{literal}){_END}", re.MULTILINE)
    for language, literal in {
        ".py": f"{_SCALAR}|{_LIST}|{_EMPTY_MAP}",
        ".php": f"{_SCALAR}|{_LIST}|{_ARRAY}",
        ".rb": f"{_SCALAR}|{_LIST}|{_EMPTY_MAP}",
        ".js": f"{_SCALAR}|{_BACKTICK}|{_LIST}|{_EMPTY_MAP}",
        ".sh": f"{_QUOTED}|[A-Za-z0-9_./:@%+,-]+",
    }.items()
}
SCRIPT_TEMPLATE_VALUE = re.compile(
    r"""(?P<quote>['"]?)\{\{(?P<expression>[^\n]*?)\}\}(?P=quote)""" + _END,
    re.MULTILINE,
)
SCRIPT_TEMPLATE_TEXT = re.compile(r"""\{[{%]|(['"])(?:(?!\1)[^\n])*?\{[{%]""")
SCRIPT_RULE = "forms-script"
SCRIPT_LITERAL = "writes a literal to the field {field!r}"
SCRIPT_UNSINKED = (
    "must write the field {field!r} as one expression of a sink its form names"
)
RENDERER_TEMPLATE = re.compile(r"""['"]/templates/([A-Za-z0-9_.-]+\.j2)['"]""")
RENDERER_SERVICE = "javascript"


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
        schema = form_schema.schema_errors(role.name, data)
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
        for path in role_files(role)
        if path.suffix in ROLE_SOURCE_SUFFIXES
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


def _spellings(field: str) -> set[str]:
    words = field.split("_")
    camel = words[0] + "".join(word.capitalize() for word in words[1:])
    return {field, camel, ".".join(words), "-".join(words)}


def _script_fields(data: dict[str, Any]) -> dict[str, frozenset[str]]:
    sinks: dict[str, set[str]] = {}
    for form, name, spec in forms.iter_fields(data):
        if forms.is_sso_source(spec.get("source")):
            continue
        named = data.get(form, {}).get("sinks")
        sinks.setdefault(name, set()).update(
            sink
            for sink in (named if isinstance(named, list) else [])
            if isinstance(sink, str)
        )
    return {name: frozenset(named) for name, named in sinks.items()}


def _role_scripts(role: Path) -> Iterator[tuple[str, str, bool]]:
    for directory in SCRIPT_DIRS:
        for path in role_files(role):
            script = path.relative_to(role).as_posix()
            if not script.startswith(f"{directory}/"):
                continue
            template = path.suffix == SCRIPT_TEMPLATE_SUFFIX
            language = (path.with_suffix("") if template else path).suffix
            if language in SCRIPT_WRITES and not script.startswith(SCRIPT_SKIPPED_DIR):
                yield script, language, template


def _reads_a_sink(expression: str, sinks: frozenset[str]) -> bool:
    try:
        (output,) = JINJA.parse("{{" + expression + "}}").body
    except (TemplateSyntaxError, ValueError):
        return False
    node = output.nodes[0]
    while (
        isinstance(node, nodes.Filter)
        and node.name in SCRIPT_SINK_FILTERS
        and not node.args
        and not node.kwargs
        and node.dyn_args is None
        and node.dyn_kwargs is None
    ):
        node = node.node
    while isinstance(node, nodes.Getattr) or (
        isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const)
    ):
        node = node.node
    return isinstance(node, nodes.Name) and node.name in sinks


def _value_finding(
    text: str, start: int, language: str, template: bool, sinks: frozenset[str]
) -> str | None:
    if template:
        value = SCRIPT_TEMPLATE_VALUE.match(text, start)
        if value and _reads_a_sink(value["expression"], sinks):
            return None
        if value or SCRIPT_TEMPLATE_TEXT.match(text, start):
            return SCRIPT_UNSINKED
    return SCRIPT_LITERAL if SCRIPT_LITERALS[language].match(text, start) else None


def script_findings(roles: list[Path]) -> list[str]:
    """Return every write of a declared field that a role's scripts take from anywhere but their input.

    Args:
        roles: role directories to check; only fields whose source is no
            ``sso.<claim>`` count, the Playwright specs are skipped, and so
            is a write on a line that carries ``nocheck: forms-script``.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        fields = _script_fields(data) if isinstance(data, dict) else {}
        if not fields:
            continue
        spelled = {spelling: name for name in fields for spelling in _spellings(name)}
        keys = "|".join(map(re.escape, sorted(spelled, key=lambda s: (-len(s), s))))
        for script, language, template in _role_scripts(role):
            text = read_text(str(role / script))
            lines = text.splitlines()
            found = set()
            for pattern in SCRIPT_WRITES[language]:
                write = pattern.replace("{key}", f"(?P<key>{keys})")
                for match in re.finditer(write, text):
                    name = spelled[match["key"]]
                    message = _value_finding(
                        text, match.end(), language, template, fields[name]
                    )
                    line = text.count("\n", 0, match.start()) + 1
                    if message and not is_suppressed_at(
                        lines, line, SCRIPT_RULE, mode="same-line"
                    ):
                        found.add((line, message.format(field=name)))
            errors.extend(
                f"{role.name}: {script}:{line} {message}"
                for line, message in sorted(found)
            )
    return errors


def _locked_forms(data: dict[str, Any]) -> list[str]:
    return sorted(
        {
            form
            for form, _field, spec in forms.iter_fields(data)
            if spec.get("mode") == "enforced"
            and not forms.is_sso_source(spec.get("source"))
            and forms.renders_lock(data[form])
        }
    )


def _loads_renderer(role: Path) -> bool:
    loader = role / ROLE_SCRIPT
    if not loader.is_file():
        return False
    text = read_text(str(loader))
    loaded = [role / "templates" / name for name in RENDERER_TEMPLATE.findall(text)]
    return any(
        SHARED_RENDERER in read_text(str(path))
        for path in [loader, *loaded]
        if path.is_file()
    )


def renderer_findings(roles: list[Path], defaults: dict[str, Any]) -> list[str]:
    """Return every role whose managed fields the shared renderer cannot lock.

    Args:
        roles: role directories to check; only a form with an ``enforced``
            field whose source is no ``sso.<claim>`` counts, unless it is
            ``native`` and the application locks it itself, or it is
            ``lock: pending`` with the ``issue`` that tracks the missing lock.
        defaults: ``applications`` defaults keyed by role.
    """
    errors = []
    for role in roles:
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        locked = _locked_forms(data) if isinstance(data, dict) else []
        if not locked:
            continue
        services = defaults.get(role.name, {}).get("services", {})
        if services.get(RENDERER_SERVICE, {}).get("enabled") is not True:
            errors.append(
                f"{role.name}: the forms {locked} hold enforced fields, so "
                f"services.{RENDERER_SERVICE}.enabled must be true"
            )
        if not _loads_renderer(role):
            errors.append(
                f"{role.name}: the forms {locked} hold enforced fields, so "
                f"{ROLE_SCRIPT} must load {SHARED_RENDERER}"
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

    def test_every_script_writes_its_declared_fields_only_from_its_input(self) -> None:
        self.assertEqual([], script_findings(self._roles()))

    def test_every_enforced_field_is_locked_wherever_its_form_applies(self) -> None:
        self.assertEqual(
            [], renderer_findings(self._roles(), get_application_defaults())
        )


if __name__ == "__main__":
    unittest.main()
