"""Ban credentials bound in an ``environment:`` of a task, block or play.

Ansible starts every module of a task, block or play that sets
``environment:`` as ``/bin/sh -c 'NAME=value … python3 … && sleep 0'``
(``Shell.env_prefix``). That shell keeps the line in its argv for the whole
module run, so host ``ps`` shows the value to every local account, and over
ssh it also lands in the controller's ssh argv. ``no_log`` masks Ansible's
output, not the process table.

The safe form hands the value over on the module's ``stdin:``: to the program
itself (``curl -H @-``, SQL on ``psql``'s stdin) or to the calling shell, which
reads and exports it for ``container exec -e NAME``
(``IFS= read -r NAME || :; : "${NAME:?…}" && export NAME && container exec
-e NAME …``), one line per secret ahead of any payload.

An entry counts as a credential by its name or by its value, each on its own.
A name convicts when a credential keyword sits anywhere in it
(``*_PASSWORD``, ``*_SECRET_KEY``, ``*_API_KEY``, ``*_MASTER_KEY``, ``*_PWD``,
``*_BEARER``, ``*_JWT``, ``OC_PASS``, ``*_PASSPHRASE``, ``*_OTP``,
``*_ENCRYPTION_KEY``, ``*_HMAC_KEY``, ``*_SIGNING_KEY``, ``REDISCLI_AUTH``) unless a describing suffix follows it (``*_PASSWORD_FILE``,
``*_TOKEN_NAME``, ``*_KEY_ID``, an ``*_ACCESS_KEY`` without ``SECRET``); a name
that ends in the keyword convicts even when the value only names an attribute
(``API_KEY: "{{ x.key }}"``). A value convicts when its Jinja, string literals
included (``lookup('config', app, 'secrets.credentials.api_key')``), names a
credential that no describing suffix qualifies, or draws on an MCP filter or
lookup that emits a bearer (``mcp_authorization``, ``mcp_credential``,
``mcp_servers``, ``mcp_tool_server_connections``). The expression is followed
through the ``vars:``/``set_fact`` definitions of the role's task files, every
var of the roles' ``vars/`` and ``defaults/`` and of ``group_vars`` whatever its
type, and the role templates a ``lookup('template', …)`` renders. A nested key
that reads like a credential carries its name along, and a key path
(``OIDC.CLIENT.ID``) is followed to that key alone, also through a ``combine``
of mappings, so a neutral name such as ``*_SETTINGS``, ``*_PAYLOAD``,
``*_CONNECTIONS`` or ``*_DESIRED`` is judged by what it renders. A
``lookup('config', …)`` is not followed into the role's ``meta/``. Literal
text around the Jinja that says credential (``Bearer {{ x }}``) convicts too.
Where ``no_log`` is in force, set on the task or on a block or play around
it, the author has declared its values sensitive, so there a whole neutral
loop value (the loop var, ``.value``, ``.configvalue``, ``['value']``,
``.1``) convicts as well. A literal value never does, and a
``lookup('file', '<literal>')`` or ``lookup('path_absolute', '<literal>')``
counts for nothing while the rest of its expression is still judged.
``{{ … }}`` and ``{% … %}`` are both read, and mapping, list and scalar forms
of ``environment:`` and non-scalar entry values alike.

Per-entry opt-out: ``# nocheck: task-environment-secret <reason>`` on the
entry's line or the line above it.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content, read_text

from . import PROJECT_ROOT
from .test_task_argv_no_secret import _DESCRIBES_CREDENTIAL

_RULE = "task-environment-secret"
_FACT_KEYS = frozenset({"set_fact", "ansible.builtin.set_fact", "vars"})
_JINJA_SPAN = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.DOTALL)
_SECRET_NAME = re.compile(
    r"(?i)password|passwd|passphrase|secret|token|credential|bearer|jwt"
    r"|(?:^|_)(?:pass|pwd|pw|otp)(?:_|$)|(?:^|_)(?:auth|key)$"
    r"|(?:api|private|master|app)_?key"
)
_STRONG_SECRET_NAME = re.compile(
    r"(?i)(?:password|passwd|passphrase|secret|token|bearer|jwt"
    r"|(?:api|private|master|secret|app|encryption|hmac|signing|session|cookie)_?key"
    r"|(?:^|_)(?:pass|pwd|pw|otp))$"
)
_NOT_A_SECRET_NAME = re.compile(
    r"(?i)_(?:file|path|dir|id|ids|name|names|user|username|owner|email|hash"
    r"|length|days|description|url|uri|host|port|type|enabled|method|scope"
    r"|scopes|endpoint|header|label|login)$"
)
_PUBLIC_ACCESS_KEY = re.compile(r"(?i)^(?!.*secret).*access_?key$")
_VALUE_CREDENTIAL = re.compile(
    r"(?i)password|passwd|passphrase|secret|token|credential|bearer|jwt"
    r"|(?:api|private|master|app|encryption|hmac|signing|session|cookie)_?key"
    r"|(?:^|_)pwd(?![a-z])|_(?:pw|pass|otp)\b|\botp\b"
)
_LITERAL_CREDENTIAL = re.compile(
    r"(?i)\b(?:bearer|basic|token|authorization|password|secret)\b"
)
_DESCRIBES_A_FLAG = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|credential)\w*_(?:label|login)\b"
)
_NAMES_AN_ATTRIBUTE = re.compile(r"^\s*[\w.]+\.(?:key|name|id|username)\s*$")
_NOT_A_CREDENTIAL = re.compile(r"(?i)\bgetent_passwd\b|/etc/passwd\b")
_STATIC_REFERENCE = re.compile(
    r"lookup\(\s*['\"](?:ansible\.builtin\.)?(?:file|path_absolute)['\"]"
    r"\s*,\s*(['\"])[^'\"]*\1\s*\)"
)
_TEMPLATE_LOOKUP = re.compile(
    r"lookup\(\s*['\"](?:ansible\.builtin\.)?template['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
_TEMPLATE_ENTRY = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*)$"
)
_CREDENTIAL_SOURCE = re.compile(
    r"\bmcp_(?:authorization|credential|servers|tool_server_connections)\b"
)
_NEUTRAL_LOOP_VALUE = (
    r"\b{loop_var}(?:\.(?:value|configvalue|1)|\[\s*(?:(['\"])(?:value|configvalue)\1|1)\s*\])?"
    r"(?![\w.\[])"
)
_REFERENCE = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_DECLARED_VARS = ("roles/*/vars/*.yml", "roles/*/defaults/*.yml", "group_vars/**/*.yml")

Templates = Callable[[str], "str | None"]


def _spans(text: str) -> list[str]:
    return [
        expression or statement for expression, statement in _JINJA_SPAN.findall(text)
    ]


def _names_credential(name: str) -> bool:
    if _STRONG_SECRET_NAME.search(name):
        return True
    return bool(
        _SECRET_NAME.search(name)
        and not _NOT_A_SECRET_NAME.search(name)
        and not _PUBLIC_ACCESS_KEY.match(name)
    )


def _describes(expression: str) -> bool:
    return bool(
        _DESCRIBES_CREDENTIAL.search(expression)
        or _DESCRIBES_A_FLAG.search(expression)
        or _NAMES_AN_ATTRIBUTE.match(expression)
    )


def _keyed_scalars(
    node: yaml.Node, key: str | None
) -> Iterator[tuple[str | None, str]]:
    if isinstance(node, yaml.ScalarNode):
        yield key, node.value
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _keyed_scalars(item, key)
    elif isinstance(node, yaml.MappingNode):
        for name, item in node.value:
            inner = name.value if isinstance(name, yaml.ScalarNode) else None
            yield from _keyed_scalars(item, inner)


def _scalar_texts(node: yaml.Node) -> list[str]:
    return [text for _, text in _keyed_scalars(node, None)]


def _value_expressions(node: yaml.Node) -> list[str]:
    """Collect what a var's value renders, for the credential check.

    Args:
      node: the composed value of one var.

    Returns:
      Every Jinja expression found anywhere in the value, plus the name of
      each nested key that reads like a credential and holds Jinja, so a
      mapping such as ``{ldap_bind_password: "{{ x }}"}`` keeps its key's
      verdict when it is followed by name.
    """
    found: list[str] = []
    for key, text in _keyed_scalars(node, None):
        found.extend(_spans(text))
        if key is not None and _JINJA_SPAN.search(text) and _names_credential(key):
            found.append(key)
    return found


def _add_definition(found: dict[str, list[str]], name: str, node: yaml.Node) -> None:
    """Record what a var renders, as a whole and under every nested key path.

    Args:
      found: var name or dotted key path to what it renders; extended in place.
      name: the var's name.
      node: the composed value of the var.
    """
    found.setdefault(name, []).extend(_value_expressions(node))
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode):
                _add_definition(found, f"{name}.{key.value}", value)


def _definitions(node: yaml.Node) -> dict[str, list[str]]:
    """Map the facts and task vars of one file to what their values render.

    Args:
      node: a composed YAML document.

    Returns:
      every name a ``set_fact`` or ``vars:`` mapping defines, and every
      dotted key path inside it, with the ``_value_expressions`` of its value.
    """
    found: dict[str, list[str]] = {}
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, yaml.SequenceNode):
            stack.extend(current.value)
            continue
        if not isinstance(current, yaml.MappingNode):
            continue
        for key, value in current.value:
            if (
                isinstance(key, yaml.ScalarNode)
                and key.value in _FACT_KEYS
                and isinstance(value, yaml.MappingNode)
            ):
                for name, definition in value.value:
                    if isinstance(name, yaml.ScalarNode):
                        _add_definition(found, name.value, definition)
            stack.append(value)
    return found


@cache
def _declared_definitions() -> dict[str, list[str]]:
    """Map every var the roles and group_vars declare to what it renders.

    Returns:
      var name to the ``_value_expressions`` of each declaration in a role's
      ``vars/`` or ``defaults/`` or in ``group_vars``, whatever the type.
    """
    found: dict[str, list[str]] = {}
    for pattern in _DECLARED_VARS:
        for path in PROJECT_ROOT.glob(pattern):
            try:
                doc = yaml.compose(read_text(str(path)), Loader=yaml.SafeLoader)
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                continue
            if not isinstance(doc, yaml.MappingNode):
                continue
            for name, value in doc.value:
                if isinstance(name, yaml.ScalarNode):
                    _add_definition(found, name.value, value)
    return found


def _expression_carries_credential(expression: str) -> bool:
    """Tell whether one Jinja expression names a credential.

    Args:
      expression: the text between ``{{`` and ``}}``, string literals included.

    Returns:
      True when a credential keyword is left once every describing name
      (``*_PASSWORD_FILE``, ``*_TOKEN_NAME``, ``*_PASSWORD_LOGIN``) is taken
      out; a ``lookup('file')``/``lookup('path_absolute')`` never is one.
    """
    stripped = _NOT_A_CREDENTIAL.sub("", _STATIC_REFERENCE.sub("", expression))
    stripped = _DESCRIBES_A_FLAG.sub("", _DESCRIBES_CREDENTIAL.sub("", stripped))
    return bool(_VALUE_CREDENTIAL.search(stripped))


def _template_carries_credential(
    content: str,
    definitions: dict[str, list[str]],
    seen: set[str],
    templates: Templates | None,
) -> bool:
    for line in content.splitlines():
        entry = _TEMPLATE_ENTRY.match(line)
        if entry and _entry_carries_credential(
            entry.group(1), entry.group(2), definitions, templates
        ):
            return True
    return any(
        _renders_credential(span, definitions, seen, templates)
        for span in _spans(content)
    )


def _renders_credential(
    expression: str,
    definitions: dict[str, list[str]],
    seen: set[str],
    templates: Templates | None = None,
    attributes: tuple[str, ...] = (),
) -> bool:
    """Tell whether an expression renders a credential, following what it names.

    Args:
      expression: the text of one Jinja expression or statement.
      definitions: var name or dotted key path to what it renders.
      seen: references and templates already followed, so a cycle ends.
      templates: role template name to its text, or None when it cannot be
        read; None skips template lookups.
      attributes: the key path the caller reads from what this expression
        renders (``CLIENT.ID`` of ``OIDC.CLIENT.ID`` when ``OIDC`` is a
        ``combine`` of mappings), applied to every var it names.

    Returns:
      True when the expression, a var or key path it names or a role
      template it renders, followed to any depth, names a credential or a
      credential source.
    """
    if _expression_carries_credential(expression) or _CREDENTIAL_SOURCE.search(
        expression
    ):
        return True
    for template in _TEMPLATE_LOOKUP.findall(expression):
        key = f"template:{template}"
        if templates is None or key in seen:
            continue
        seen.add(key)
        content = templates(template)
        if content is not None and _template_carries_credential(
            content, definitions, seen, templates
        ):
            return True
    for reference in _REFERENCE.findall(expression):
        parts = [*reference.split("."), *attributes]
        depth = next(
            (
                depth
                for depth in range(len(parts), 0, -1)
                if ".".join(parts[:depth]) in definitions
            ),
            0,
        )
        key = ".".join(parts)
        if not depth or key in seen:
            continue
        seen.add(key)
        if any(
            _renders_credential(
                inner, definitions, seen, templates, tuple(parts[depth:])
            )
            for inner in definitions[".".join(parts[:depth])]
        ):
            return True
    return False


def _entry_carries_credential(
    name: str,
    value: str,
    definitions: dict[str, list[str]],
    templates: Templates | None = None,
    neutral: re.Pattern[str] | None = None,
) -> bool:
    """Tell whether one ``environment:`` entry binds a credential.

    Args:
      name: the environment variable's name, ``environment`` for a scalar.
      value: its value text, Jinja expressions and statements included.
      definitions: var name or dotted key path to what it renders.
      templates: role template name to its text; None skips template lookups.
      neutral: the pattern of a whole neutral loop value when ``no_log`` is
        in force for the entry, otherwise None.

    Returns:
      True for an interpolated value whose name ends in a credential keyword,
      whose name carries one and whose expressions do not all only describe
      a credential or name an attribute, whose literal text around the Jinja
      says credential (``Bearer {{ x }}``), whose Jinja renders one, or that
      is a whole neutral loop value under ``no_log``; a literal value never
      is one.
    """
    expressions = _spans(value)
    if not expressions:
        return False
    named = name != "environment" and _names_credential(name)
    if named and (
        _STRONG_SECRET_NAME.search(name) or not all(_describes(e) for e in expressions)
    ):
        return True
    if _LITERAL_CREDENTIAL.search(_JINJA_SPAN.sub(" ", value)):
        return True
    if neutral is not None and any(neutral.search(e) for e in expressions):
        return True
    return any(
        _renders_credential(e, definitions, set(), templates) for e in expressions
    )


def _environment_nodes(
    node: yaml.Node, no_log: bool = False
) -> Iterator[tuple[yaml.Node, yaml.Node, yaml.MappingNode, bool]]:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _environment_nodes(item, no_log)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    masked = no_log or _sets_no_log(node)
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode) and key.value == "environment":
            yield key, value, node, masked
        else:
            yield from _environment_nodes(value, masked)


def _loop_value_pattern(owner: yaml.MappingNode) -> re.Pattern[str]:
    loop_var = "item"
    control = _mapping_values(owner).get("loop_control")
    if isinstance(control, yaml.MappingNode):
        name = _mapping_values(control).get("loop_var")
        if isinstance(name, yaml.ScalarNode) and re.fullmatch(r"\w+", name.value):
            loop_var = name.value
    return re.compile(_NEUTRAL_LOOP_VALUE.format(loop_var=loop_var))


def _mapping_values(node: yaml.MappingNode) -> dict[str, yaml.Node]:
    return {
        key.value: value
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    }


def _entries(
    anchor: yaml.Node, value: yaml.Node
) -> Iterator[tuple[yaml.Node, str, str]]:
    if isinstance(value, yaml.ScalarNode):
        yield anchor, "environment", value.value
    elif isinstance(value, yaml.MappingNode):
        for name, item in value.value:
            if isinstance(name, yaml.ScalarNode):
                yield name, name.value, " ".join(_scalar_texts(item))
    elif isinstance(value, yaml.SequenceNode):
        for item in value.value:
            yield from _entries(item, item)


def _sets_no_log(mapping: yaml.MappingNode | None) -> bool:
    return mapping is not None and any(
        isinstance(key, yaml.ScalarNode) and key.value == "no_log"
        for key, _ in mapping.value
    )


def scan_environment(
    content: str,
    role_definitions: dict[str, list[str]] | None = None,
    templates: Templates | None = None,
) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for every credential bound in an ``environment:``.

    Args:
      content: text of one task or playbook file.
      role_definitions: var name to what its value renders, for the vars
        declared outside the file; the repository's role and group vars when
        omitted.
      templates: role template name to its text, for ``lookup('template')``;
        None skips template lookups.

    Returns:
      The 1-based line of each offending entry and its variable name, or
      ``environment`` for a templated scalar that renders a credential, in
      file order.
    """
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    outside = _declared_definitions() if role_definitions is None else role_definitions
    lines = content.splitlines()
    findings: list[tuple[int, str]] = []
    for doc in docs:
        if doc is None:
            continue
        definitions = {**outside, **_definitions(doc)}
        for key, value, owner, masked in _environment_nodes(doc):
            neutral = _loop_value_pattern(owner) if masked else None
            for anchor, name, text in _entries(key, value):
                offends = _entry_carries_credential(
                    name, text, definitions, templates, neutral
                )
                line_no = anchor.start_mark.line + 1
                if offends and not is_suppressed_at(
                    lines, line_no, _RULE, mode="same-or-above"
                ):
                    findings.append((line_no, name))
    return findings


class TestScanEnvironment(unittest.TestCase):
    def test_a_credential_by_name_or_by_source_is_flagged(self) -> None:
        content = (
            "- name: x\n"
            "  ansible.builtin.shell: container exec -e DB_PASSWORD c tool\n"
            "  environment:\n"
            '    DB_PASSWORD: "{{ X_DB_PASSWORD }}"\n'
            "    PGPASSWORD: \"{{ lookup('database', app, 'password') }}\"\n"
            "    MCP_DESIRED: \"{{ {'token': X_MCP_TOKEN} | to_json }}\"\n"
            '    REDISCLI_AUTH: "{{ X_REDIS }}"\n'
            '    X_API_KEY: "{{ X_KEY }}"\n'
        )
        self.assertEqual(
            scan_environment(content, {}),
            [
                (4, "DB_PASSWORD"),
                (5, "PGPASSWORD"),
                (6, "MCP_DESIRED"),
                (7, "REDISCLI_AUTH"),
                (8, "X_API_KEY"),
            ],
        )

    def test_block_and_scalar_environments_are_read_too(self) -> None:
        content = (
            "- block:\n"
            "    - ansible.builtin.command: tool\n"
            "  environment:\n"
            '    ADMIN_PASS: "{{ X_ADMIN_PASS }}"\n'
            "- ansible.builtin.command: tool\n"
            '  environment: "{{ X_SECRET_ENV }}"\n'
        )
        self.assertEqual(
            scan_environment(content, {}), [(4, "ADMIN_PASS"), (6, "environment")]
        )

    def test_stdin_literals_and_descriptions_pass(self) -> None:
        content = (
            "- ansible.builtin.shell:\n"
            "    cmd: >-\n"
            "      IFS= read -r DB_PASSWORD && export DB_PASSWORD &&\n"
            "      container exec -i -e DB_PASSWORD -e SITE c tool\n"
            '    stdin: "{{ X_DB_PASSWORD }}"\n'
            "  environment:\n"
            '    SITE: "{{ X_SITE_URL }}"\n'
            "    RAILS_ENV: production\n"
            "    PASSWORD_STORE_DIR: /etc/pass\n"
            '    PGPASSFILE: "{{ X_PGPASS_FILE }}"\n'
            '    X_TOKEN_NAME: "{{ X_MCP_TOKEN_NAME }}"\n'
            '    X_LIFETIME: "{{ X_MCP_TOKEN_LIFETIME_DAYS }}"\n'
            '    X_TOKEN_LABEL: "{{ X_MCP_TOKEN_LABEL }}"\n'
            '    X_LOCAL: "{{ X_LOCAL_PASSWORD_LOGIN | string | lower }}"\n'
            '    X_AI_CREDENTIAL: "{{ X_LITELLM_CREDENTIAL_NAME }}"\n'
            "    X_CA: \"{{ lookup('file', 'ca.pem') }}\"\n"
            '    X_UID: "{{ ansible_facts.getent_passwd.nixbld1[1] }}"\n'
        )
        self.assertEqual(scan_environment(content, {}), [])

    def test_a_marked_entry_is_skipped(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            f"    # nocheck: {_RULE} public demo value\n"
            '    DEMO_TOKEN: "{{ X_DEMO_TOKEN }}"\n'
        )
        self.assertEqual(scan_environment(content, {}), [])

    def test_key_and_otp_names_are_credentials_unless_they_identify(self) -> None:
        content = (
            "- ansible.builtin.command: php\n"
            "  environment:\n"
            '    APP_KEY: "{{ SNIPE_IT_APP_KEY }}"\n'
            '    BAO_OTP: "{{ x_root_otp.stdout | trim }}"\n'
            '    S3_ACCESS_KEY_ID: "{{ X_ID }}"\n'
            '    S3_ACCESS_KEY: "{{ X_ACCESS }}"\n'
            '    X_KEY_ID: "{{ X_KID }}"\n'
            '    X_KEY_NAME: "{{ X_KNAME }}"\n'
            '    CONFIG_KEY: "{{ item.key }}"\n'
        )
        self.assertEqual(
            scan_environment(content, {}), [(3, "APP_KEY"), (4, "BAO_OTP")]
        )

    def test_a_keyword_anywhere_in_the_name_convicts(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_SECRET_KEY: "{{ a }}"\n'
            '    X_MASTER_KEY: "{{ b }}"\n'
            '    X_PWD: "{{ c }}"\n'
            '    X_BEARER: "{{ d }}"\n'
            '    X_JWT: "{{ e }}"\n'
            '    OC_PASS: "{{ f }}"\n'
            '    AWS_SECRET_ACCESS_KEY: "{{ g }}"\n'
            '    BORG_PASSPHRASE: "{{ h }}"\n'
            '    API_KEY: "{{ x.key }}"\n'
        )
        self.assertEqual(
            [name for _, name in scan_environment(content, {})],
            [
                "X_SECRET_KEY",
                "X_MASTER_KEY",
                "X_PWD",
                "X_BEARER",
                "X_JWT",
                "OC_PASS",
                "AWS_SECRET_ACCESS_KEY",
                "BORG_PASSPHRASE",
                "API_KEY",
            ],
        )

    def test_a_secret_source_in_a_string_literal_convicts_any_name(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            "    X_VALUE: \"{{ lookup('config', app, 'secrets.credentials.api_key') }}\"\n"
            "    X_OTHER: \"{{ lookup('config', app, 'server.domains') }}\"\n"
        )
        self.assertEqual(scan_environment(content, {}), [(3, "X_VALUE")])

    def test_a_multi_line_expression_is_read_whole(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment: >-\n"
            "    {{ x_base | combine({\n"
            "         'ADMIN_PASSWORD': x_admin\n"
            "       }) }}\n"
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            "    ADMIN_PASSWORD: >-\n"
            "      {{ x_admin\n"
            "         | trim }}\n"
        )
        self.assertEqual(
            scan_environment(content, {}), [(2, "environment"), (8, "ADMIN_PASSWORD")]
        )

    def test_list_form_and_non_scalar_values_are_read(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    - X_TOKEN: "{{ a }}"\n'
            '    - "{{ x_secret_env }}"\n'
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            "    X_LIST:\n"
            '      - "{{ x_db_password }}"\n'
        )
        self.assertEqual(
            scan_environment(content, {}),
            [(3, "X_TOKEN"), (4, "environment"), (7, "X_LIST")],
        )

    def test_a_neutral_loop_value_convicts_under_no_log(self) -> None:
        masked = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_VALUE: "{{ item.configvalue }}"\n'
            '    X_OTHER: "{{ item.value | string }}"\n'
            '    X_USER: "{{ item.value.username }}"\n'
            '    X_PAYLOAD: "{{ x_policy | to_json | b64encode }}"\n'
            '  no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"\n'
        )
        plain = masked.replace(
            '  no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"\n', ""
        )
        self.assertEqual(scan_environment(masked, {}), [(3, "X_VALUE"), (4, "X_OTHER")])
        self.assertEqual(scan_environment(plain, {}), [])

    def test_a_key_path_is_judged_by_its_own_value(self) -> None:
        role_definitions: dict[str, list[str]] = {}
        _add_definition(
            role_definitions,
            "X_LDAP",
            yaml.compose(
                'SERVER: {HOST: "{{ x_host }}"}\nBIND_CREDENTIAL: "{{ x_bind }}"\n',
                Loader=yaml.SafeLoader,
            ),
        )
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_HOST: "{{ X_LDAP.SERVER.HOST }}"\n'
            '    X_ALL: "{{ X_LDAP | to_json }}"\n'
            '    X_BIND: "{{ X_LDAP.BIND_CREDENTIAL }}"\n'
        )
        self.assertEqual(
            scan_environment(content, role_definitions), [(4, "X_ALL"), (5, "X_BIND")]
        )

    def test_a_file_lookup_hides_nothing_else_in_its_expression(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            "    X_CERT: \"{{ lookup('file', 'ca.pem') }}\"\n"
            "    X_BUNDLE: \"{{ lookup('file', 'ca.pem') ~ x_db_password }}\"\n"
        )
        self.assertEqual(scan_environment(content, {}), [(4, "X_BUNDLE")])

    def test_a_statement_in_an_entry_value_is_read(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            "    X_VALUE: \"{% if on %}{{ 'a' }}{% else %}{{ x_api_key }}{% endif %}\"\n"
            '    X_CHOICE: "{% if x_secret %}on{% endif %}"\n'
            '    X_PLAIN: "{% if on %}a{% endif %}"\n'
        )
        self.assertEqual(
            scan_environment(content, {}), [(3, "X_VALUE"), (4, "X_CHOICE")]
        )

    def test_literal_text_around_the_jinja_can_say_credential(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_HEADER: "Bearer {{ x_access }}"\n'
            '    X_URL: "https://{{ x_host }}/api"\n'
        )
        self.assertEqual(scan_environment(content, {}), [(3, "X_HEADER")])

    def test_any_loop_value_shape_convicts_under_an_inherited_no_log(self) -> None:
        content = (
            '- no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"\n'
            "  block:\n"
            "    - ansible.builtin.command: tool\n"
            "      environment:\n"
            '        X_A: "{{ entry.value }}"\n'
            "        X_B: \"{{ entry['configvalue'] }}\"\n"
            '        X_C: "{{ entry.1 }}"\n'
            '        X_D: "{{ entry }}"\n'
            '        X_E: "{{ entry.value.name }}"\n'
            '        X_F: "{{ item.value }}"\n'
            "      loop: []\n"
            "      loop_control:\n"
            "        loop_var: entry\n"
        )
        unmasked = content.replace(
            '- no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"\n', "- name: x\n"
        )
        self.assertEqual(
            [name for _, name in scan_environment(content, {})],
            ["X_A", "X_B", "X_C", "X_D"],
        )
        self.assertEqual(scan_environment(unmasked, {}), [])

    def test_signing_material_counts_under_any_name(self) -> None:
        content = (
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_ONE: "{{ X_ENCRYPTION_KEY }}"\n'
            '    X_TWO: "{{ X_HMAC_KEY }}"\n'
            '    X_THREE: "{{ X_SIGNING_KEY }}"\n'
            '    X_SESSION_KEY: "{{ x_value }}"\n'
            '    X_CWD: "{{ ansible_env.PWD }}"\n'
            '    X_DB: "{{ X_DB_PWD }}"\n'
        )
        self.assertEqual(
            [name for _, name in scan_environment(content, {})],
            ["X_ONE", "X_TWO", "X_THREE", "X_SESSION_KEY", "X_DB"],
        )

    def test_a_neutral_name_is_judged_by_the_vars_and_facts_it_renders(
        self,
    ) -> None:
        content = (
            "- ansible.builtin.set_fact:\n"
            "    x_bundle: \"{{ {'pw': X_DB_PASSWORD} }}\"\n"
            "- ansible.builtin.command: tool\n"
            "  vars:\n"
            '    x_payload: "{{ x_bundle | to_json | b64encode }}"\n'
            "  environment:\n"
            '    X_PAYLOAD: "{{ x_payload }}"\n'
            '    X_PLAIN: "{{ x_plain }}"\n'
        )
        self.assertEqual(scan_environment(content, {}), [(7, "X_PAYLOAD")])

    def test_a_credential_key_inside_a_var_carries_its_name(self) -> None:
        content = (
            "- ansible.builtin.set_fact:\n"
            "    x_settings:\n"
            '      ldap_bind_password: "{{ x_bind }}"\n'
            '      title: "{{ x_title }}"\n'
            "- ansible.builtin.command: tool\n"
            "  environment:\n"
            '    X_SETTINGS: "{{ x_settings | to_json }}"\n'
        )
        self.assertEqual(scan_environment(content, {}), [(7, "X_SETTINGS")])

    def test_a_scalar_environment_resolves_through_its_definitions(self) -> None:
        content = (
            "- ansible.builtin.set_fact:\n"
            "    x_auth_env:\n"
            '      X_ADMIN: "{{ X_ADMIN_PASSWORD }}"\n'
            "- ansible.builtin.script: run.sh\n"
            "  environment: \"{{ x_auth_env | combine({'MODE': 'x'}) }}\"\n"
        )
        self.assertEqual(scan_environment(content, {}), [(5, "environment")])

    def test_role_vars_and_mcp_sources_count_as_credential_sources(self) -> None:
        role_definitions = {
            "X_MCP_DESIRED": [
                "- set _ = out.append({'id': s.id, 'auth': s | mcp_authorization}) -"
            ],
            "X_MCP_PLAIN": [" X_MCP_SERVERS | map(attribute='id') | list "],
            "X_DISCOVERY": [" lookup('mcp_servers') "],
            "X_PROVIDERS": [" X_DISCOVERY.selected if X_ON else [] "],
        }
        content = (
            "- ansible.builtin.shell: tool\n"
            "  environment:\n"
            '    X_DESIRED: "{{ X_MCP_DESIRED | to_json }}"\n'
            '    X_CONNECTIONS: "{{ X_MCP_SERVERS | mcp_tool_server_connections(G) | to_json }}"\n'
            '    X_IDS: "{{ X_MCP_PLAIN | to_json }}"\n'
            '    X_LIST: "{{ X_PROVIDERS | to_json }}"\n'
        )
        self.assertEqual(
            scan_environment(content, role_definitions),
            [(3, "X_DESIRED"), (4, "X_CONNECTIONS"), (6, "X_LIST")],
        )

    def test_the_repository_role_and_group_vars_are_followed(self) -> None:
        content = (
            "- ansible.builtin.shell: tool\n"
            "  environment:\n"
            '    FLOWISE_MCP_DESIRED: "{{ FLOWISE_MCP_DESIRED | to_json }}"\n'
            '    N8N_MCP_PROVIDERS: "{{ N8N_MCP_PROVIDERS | to_json }}"\n'
        )
        self.assertEqual(
            scan_environment(content),
            [(3, "FLOWISE_MCP_DESIRED"), (4, "N8N_MCP_PROVIDERS")],
        )

    def test_a_rendered_template_is_judged_by_its_content(self) -> None:
        content = (
            "- ansible.builtin.script: bootstrap.sh\n"
            "  environment: \"{{ lookup('template', 'environment/bootstrap.j2') | from_yaml }}\"\n"
        )
        secret = {
            "environment/bootstrap.j2": (
                "INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD: {{ X_ADMIN_PASSWORD | to_json }}\n"
                "INFINITO_CACHE_PACKAGE_PORT: {{ X_PORT | to_json }}\n"
            )
        }
        public = {"environment/bootstrap.j2": "X_PORT: {{ X_PORT | to_json }}\n"}
        self.assertEqual(
            scan_environment(content, {}, secret.get), [(2, "environment")]
        )
        self.assertEqual(scan_environment(content, {}, public.get), [])

    def test_a_play_level_environment_is_read(self) -> None:
        content = (
            "- hosts: all\n"
            "  environment:\n"
            '    CA_TRUST_NAME: "{{ CA_TRUST.trust_name }}"\n'
            '    X_TOKEN: "{{ x_token }}"\n'
            "  roles: [x]\n"
        )
        self.assertEqual(scan_environment(content, {}), [(4, "X_TOKEN")])

    def test_include_vars_from_a_sibling_file_are_followed(self) -> None:
        sibling = (
            "- ansible.builtin.include_tasks: auth.yml\n"
            "  vars:\n"
            "    x_auth_env_base:\n"
            '      X_ADMIN: "{{ X_ADMIN_PASSWORD }}"\n'
            '    x_auth_env: "{{ x_auth_env_base | combine({}) }}"\n'
        )
        content = (
            "- ansible.builtin.shell: run\n"
            "  environment: \"{{ x_auth_env | combine({'PHASE': 'x'}) }}\"\n"
        )
        per_role = _role_task_definitions(
            [("roles/x/tasks/setup.yml", sibling), ("roles/x/tasks/auth.yml", content)]
        )
        self.assertEqual(scan_environment(content, {}), [])
        self.assertEqual(scan_environment(content, per_role["x"]), [(2, "environment")])


def _role_task_definitions(
    files: list[tuple[str, str]],
) -> dict[str, dict[str, list[str]]]:
    """Collect the ``vars:``/``set_fact`` definitions of every task file per role.

    Args:
      files: ``(path relative to the project, content)`` of each task file.

    Returns:
      role name to var name to what its value renders, so an
      ``environment:`` built from include vars set in a sibling file is
      followed too; files outside ``roles/`` are left out.
    """
    found: dict[str, dict[str, list[str]]] = {}
    for rel, content in files:
        if not rel.startswith("roles/"):
            continue
        try:
            docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
        except yaml.YAMLError:
            continue
        role = found.setdefault(rel.split("/")[1], {})
        for doc in docs:
            if doc is None:
                continue
            for name, expressions in _definitions(doc).items():
                role.setdefault(name, []).extend(expressions)
    return found


def _is_scan_target(rel: str) -> bool:
    if rel.startswith("roles/"):
        return "/tasks/" in rel or "/handlers/" in rel
    return rel.startswith(("playbook", "playbooks/", "tasks/"))


def _role_templates(rel: str) -> Templates | None:
    if not rel.startswith("roles/"):
        return None
    templates_dir = PROJECT_ROOT / "roles" / rel.split("/")[1] / "templates"

    def read(name: str) -> str | None:
        path = templates_dir / name
        try:
            return read_text(str(path)) if path.is_file() else None
        except (OSError, UnicodeDecodeError):
            return None

    return read


class TestScanTargets(unittest.TestCase):
    def test_role_tasks_handlers_playbooks_and_top_level_tasks_are_scanned(
        self,
    ) -> None:
        scanned = [
            "roles/x/tasks/utils/setup.yml",
            "roles/x/handlers/restart.yml",
            "playbook.yml",
            "playbook-sync.yml",
            "playbooks/x.yml",
            "tasks/x.yml",
        ]
        skipped = [
            "roles/x/vars/extra.yml",
            "roles/x/templates/app.conf.j2",
            "docs/x.yml",
            "group_vars/all/x.yml",
        ]
        self.assertEqual([_is_scan_target(rel) for rel in scanned], [True] * 6)
        self.assertEqual([_is_scan_target(rel) for rel in skipped], [False] * 4)


class TestTaskEnvironmentNoSecret(unittest.TestCase):
    def test_task_environment_binds_no_credential(self) -> None:
        files = [
            (rel, content)
            for path_str, content in iter_project_files_with_content(
                extensions=(".yml", ".yaml"),
                exclude_tests=True,
            )
            for rel in [Path(path_str).relative_to(PROJECT_ROOT).as_posix()]
            if _is_scan_target(rel)
        ]
        per_role = _role_task_definitions(files)
        findings: list[str] = []
        for rel, content in files:
            role = rel.split("/")[1] if rel.startswith("roles/") else ""
            outside = {**_declared_definitions(), **per_role.get(role, {})}
            findings.extend(
                f"- {rel}:{line_no}: {name}"
                for line_no, name in scan_environment(
                    content, outside, _role_templates(rel)
                )
            )

        self.assertFalse(
            findings,
            "A credential is bound in an `environment:` of a task, block or "
            "play. Ansible starts the module as `/bin/sh -c 'NAME=value …'`, "
            "where the host's `ps` shows it to every local account for the "
            "whole module run and `no_log` cannot mask it. Hand it over on the "
            "module's `stdin:` instead: to the program itself, or to the "
            'calling shell (`IFS= read -r NAME || :; : "${NAME:?…}" && '
            "export NAME && container exec -e NAME …`). Mark a deliberate "
            "exception with "
            f"`# nocheck: {_RULE} <reason>`.\n\nOffenders:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
