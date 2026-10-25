"""Ban ``-e NAME=VALUE`` in role files wherever VALUE is not a literal.

Rationale
=========
``container exec -e NAME=VALUE`` puts VALUE in the argv of the host-side
process, where ``ps`` shows it to every local account for as long as the call
runs. ``no_log`` does not help: it masks Ansible's output, not the process
table. A deployment rotates its credentials between the two passes of a
matrix-deploy round, so the values that travel this way are live secrets.

The safer form is ``-e NAME`` with no value. The engine then forwards the
variable from its own environment, which an Ansible task fills with a
task-level ``environment:`` mapping and a shell script with ``export``.

With ``ansible.builtin.script`` the value then reaches no argv; with
``shell`` and ``command`` it still appears once on the module wrapper's own
line, which ``Shell.env_prefix`` builds, so the exposure shrinks rather than
vanishes.

The check is on the flag, not on the command before it: associating an ``-e``
with its ``container exec`` is unreliable across a YAML block scalar, and
``docker run -e`` leaks the same way.

An ``argv:`` list spells the same thing across two entries, ``-e`` on one and
``NAME={{ … }}`` on the next, so a line-oriented scan never sees them
together. Those lists are therefore read from the parsed YAML as well.

A literal value cannot carry a secret, so ``-e RAILS_ENV=production`` passes.
Of the interpolated ones the rule takes those carrying a credential, by the
variable's name **or** by a credential source in the expression behind it.
The second signal is what keeps this from being a name denylist: a secret
passed as ``-e FOO={{ lookup('users', 'x').password }}`` is caught by its
source. One from a source this rule does not know, under a name that does not
say so, still slips through.

The same exposure applies to a secret written straight into the command line
of a ``container exec`` / ``docker exec`` task (``--password {{ pw }}``,
``-H "Authorization: Bearer {{ token }}"``, ``-p{{ pw }}``). The second rule
reads every ``shell``/``command`` task whose command runs an exec and rejects a
Jinja expression in it that draws on a credential source or whose name says
credential anywhere in it, also one var deep (a ``*_JSON_INFO`` carrying a
``secret``). A var whose value runs an exec, directly or through another one
(``{{ NEXTCLOUD_DOCKER_EXEC_OCC }}``), counts as the exec, and so does
``container run``. In a task that sets ``no_log`` the author has declared its
values sensitive, so there a neutral loop value (``item.value``,
``item.configvalue``), a ``b64encode`` payload or a ``*_b64`` var on the exec
line convicts too. A
fact or task var defined in the same file whose value holds a credential key
(``password:``) or source counts as a secret under any name. The first rule
also reads the Jinja-built ``-e {{ ('NAME=' ~ …) }}``. Hand such a value over on
the task's ``stdin:`` (``curl -H @-``, ``psql`` reading SQL) or as ``-e NAME``
plus ``environment:``.

Per-line opt-out
================
``# nocheck: container-exec-env-value -- <reason>`` on the same line or the
immediately preceding non-empty line. Reserved for a templated value that
provably carries no secret, such as a service or role name; state which.
``# nocheck: exec-argv-secret <reason>`` on the module key's line or the line
above it does the same for the second rule.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from .test_exec_requires_shell_module import _variable_values

_RULE = "container-exec-env-value"
_EXTENSIONS = (".yml", ".yaml", ".j2", ".sh")
_ENV_WITH_VALUE = re.compile(
    r"(?:^|\s)-e\s+(?:\{\{\s*\(*\s*['\"])?([A-Za-z_][A-Za-z0-9_]*)="
)
_INTERPOLATED = re.compile(r"\{\{|\$|`")
_SECRET_NAME = re.compile(r"PASS|PWD|SECRET|TOKEN|KEY|CRED", re.IGNORECASE)
_SECRET_SOURCE = re.compile(
    r"\.password\b"
    r"|secrets\.credentials\."
    r"|['\"]password['\"]"
    r"|\.secret\b"
    r"|[A-Za-z0-9_]*(?:PASSWORD|SECRET|TOKEN|_PW|_KEY)\b",
    re.IGNORECASE,
)


_NOT_A_SECRET_NAME = re.compile(
    r"(?:_NAME|_EMAIL|_USER|_USERNAME|_OWNER|_ID|_URL|_HOST|_PORT|_PATH|_DAYS)$",
    re.IGNORECASE,
)
_ARGV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_MODULE_KEYS = (
    "command",
    "ansible.builtin.command",
    "shell",
    "ansible.builtin.shell",
)


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and rel_path.endswith(_EXTENSIONS)


def _carries_credential(name: str, value: str) -> bool:
    """Decide whether an ``NAME=VALUE`` pair hands over a secret.

    Args:
        name: the variable name to the left of the ``=``.
        value: everything to its right, Jinja included.

    Returns:
        True when the name reads like a credential or the expression draws
        from a credential source. A name whose last segment is ``_NAME``,
        ``_OWNER``, ``_EMAIL`` or similar describes the credential rather
        than carrying it, so the name alone does not convict it; a
        credential source in the value still does.
    """
    by_name = bool(_SECRET_NAME.search(name)) and not _NOT_A_SECRET_NAME.search(name)
    return by_name or bool(_SECRET_SOURCE.search(value))


def _env_assignments(line: str):
    """Yield every ``-e NAME=VALUE`` a line passes, with an interpolated value.

    Args:
        line: one source line.

    Yields:
        ``(name, value)`` for ``-e NAME={{ … }}`` and for the Jinja-built
        ``-e {{ ('NAME=' ~ …) | quote }}``; a literal value is skipped.
    """
    matches = list(_ENV_WITH_VALUE.finditer(line))
    for position, match in enumerate(matches):
        following = matches[position + 1 :]
        stop = following[0].start() if following else len(line)
        value = line[match.end() : stop]
        if "{{" in match.group(0) or _INTERPOLATED.search(value):
            yield match.group(1), value


def _argv_lists(node):
    """Yield every ``argv:`` list a task hands to a command module.

    Args:
        node: a parsed YAML document, or any fragment of one.

    Yields:
        Each ``argv`` list found under a ``command``/``shell`` mapping.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _MODULE_KEYS and isinstance(value, dict):
                argv = value.get("argv")
                if isinstance(argv, list):
                    yield argv
            yield from _argv_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _argv_lists(item)


_ARGV_RULE = "exec-argv-secret"
_EXEC = re.compile(r"\b(?:container|docker)\s+(?:exec|run)\b")
_NEUTRAL_PAYLOAD = re.compile(
    r"\bitem\.(?:value|configvalue)\b|\b\w+_b64\b|\|\s*b64encode\b"
)
_FACT_KEYS = ("set_fact", "ansible.builtin.set_fact", "vars")
_LOG_SHOWN = {"false", "no", "off", "0"}
_JINJA_EXPR = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_ARGV_SECRET = re.compile(
    r"(?i)\w*(?:password|passwd|secret|bind_credential|token|bearer|jwt"
    r"|api_?key|private_?key|_pwd|_pw|_pass)\w*"
)
_ARGV_SOURCE = re.compile(
    r"(?i)secrets\.credentials\.|['\"]password['\"]|\.password\b|\.secret\b"
)
_NOT_A_SECRET_SUFFIX = re.compile(
    r"(?i)(?:_name|_names|_email|_user|_username|_owner|_id|_ids|_uuid|_uuids"
    r"|_url|_uri|_host|_port|_path|_file|_dir|_days|_length|_enabled|_type"
    r"|_header|_endpoint|_scope|_scopes|_description|_hash|_policy|_ttl)$"
)
_DESCRIBES_A_SECRET = re.compile(r"\|\s*(?:hash|password_hash)\b|\.(?:id|name)\b")
_LITERAL = re.compile(r"'(?!password')[^']*'|\"(?!password\")[^\"]*\"")


def _exec_wrappers(values: dict[str, str]) -> frozenset[str]:
    """Return the vars whose value runs a container exec, directly or nested.

    Args:
        values: var name to its declared string value.

    Returns:
        Every name whose value contains ``container exec`` / ``docker exec``
        or interpolates another such name, so ``{{ NEXTCLOUD_DOCKER_EXEC_OCC }}``
        counts as an exec through ``NEXTCLOUD_DOCKER_EXEC``.
    """
    wrappers = {name for name, value in values.items() if _EXEC.search(value)}
    while True:
        grown = {
            name
            for name, value in values.items()
            if name not in wrappers
            and any(
                re.search(r"\{\{\s*" + re.escape(w) + r"\b", value) for w in wrappers
            )
        }
        if not grown:
            return frozenset(wrappers)
        wrappers |= grown


def _expression_carries_secret(expr: str, values: dict[str, str], depth: int) -> bool:
    """Decide whether one Jinja expression on an exec line renders a secret.

    Args:
        expr: the text between ``{{`` and ``}}``.
        values: var name to its declared string value, for one level of
            indirection through a neutral name such as ``*_JSON_INFO``.
        depth: how many var values were already followed to reach ``expr``.

    Returns:
        True for a credential source (``secrets.credentials.…``,
        ``.password``), a name that says credential anywhere in it
        (``*_API_KEY``, ``*_PWD``) unless it only describes one (``*_ID``,
        ``*_NAME``, a hash), or a var whose value does either.
    """
    if _DESCRIBES_A_SECRET.search(expr):
        return False
    if _ARGV_SOURCE.search(expr):
        return True
    names = _IDENTIFIER.findall(_LITERAL.sub("''", expr))
    if any(
        _ARGV_SECRET.fullmatch(name) and not _NOT_A_SECRET_SUFFIX.search(name)
        for name in names
    ):
        return True
    if depth >= 2:
        return False
    return any(
        _expression_carries_secret(inner.group(1), values, depth + 1)
        for name in names
        if not _NOT_A_SECRET_SUFFIX.search(name)
        for inner in _JINJA_EXPR.finditer(values.get(name, ""))
    )


_VALUES = _variable_values()
_WRAPPERS = _exec_wrappers(_VALUES)
_WRAPPER_USE = re.compile(
    r"\{\{\s*(?:" + "|".join(map(re.escape, sorted(_WRAPPERS))) + r")\b"
    if _WRAPPERS
    else r"(?!)"
)


def _module_nodes(node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _module_nodes(item)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode) and key.value in _MODULE_KEYS:
            yield key, value, node
        else:
            yield from _module_nodes(value)


def _hides_log(task: yaml.MappingNode) -> bool:
    """Tell whether a task sets ``no_log`` to anything but a literal false.

    Args:
        task: the task mapping that holds the module key.

    Returns:
        True for ``no_log: true`` and for a templated value such as
        ``"{{ MASK_CREDENTIALS_IN_LOGS | bool }}"``.
    """
    return any(
        isinstance(key, yaml.ScalarNode)
        and key.value == "no_log"
        and isinstance(value, yaml.ScalarNode)
        and value.value.strip().lower() not in _LOG_SHOWN
        for key, value in task.value
    )


def _node_carries_secret(node: yaml.Node) -> bool:
    if isinstance(node, yaml.ScalarNode):
        return any(
            _expression_carries_secret(" ".join(m.group(1).split()), _VALUES, 1)
            for m in _JINJA_EXPR.finditer(node.value)
        )
    if isinstance(node, yaml.SequenceNode):
        return any(_node_carries_secret(item) for item in node.value)
    if isinstance(node, yaml.MappingNode):
        return any(
            (
                isinstance(key, yaml.ScalarNode)
                and _ARGV_SECRET.fullmatch(key.value)
                and not _NOT_A_SECRET_SUFFIX.search(key.value)
            )
            or _node_carries_secret(value)
            for key, value in node.value
        )
    return False


def _secret_facts(node: yaml.Node) -> frozenset[str]:
    """Return the facts and task vars of one file whose definition holds a secret.

    Args:
        node: a parsed YAML document.

    Returns:
        Every name a ``set_fact`` or ``vars:`` mapping defines with a value
        that carries a credential key (``password:``) or source.
    """
    names: set[str] = set()
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
                names.update(
                    fact.value
                    for fact, definition in value.value
                    if isinstance(fact, yaml.ScalarNode)
                    and not _NOT_A_SECRET_SUFFIX.search(fact.value)
                    and _node_carries_secret(definition)
                )
            stack.append(value)
    return frozenset(names)


def _command_text(value: yaml.Node) -> str:
    if isinstance(value, yaml.ScalarNode):
        return value.value
    if not isinstance(value, yaml.MappingNode):
        return ""
    parts: list[str] = []
    for key, item in value.value:
        if key.value == "cmd" and isinstance(item, yaml.ScalarNode):
            parts.append(item.value)
        elif key.value == "argv" and isinstance(item, yaml.SequenceNode):
            parts.extend(e.value for e in item.value if isinstance(e, yaml.ScalarNode))
    return " ".join(parts)


def scan_exec_argv(content: str) -> list[tuple[int, str]]:
    """Return ``(line, expression)`` for every secret in an exec command line.

    Args:
        content: text of one task file.

    Returns:
        The module key's line and the offending Jinja expression, in file order.
    """
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    lines = content.splitlines()
    findings: list[tuple[int, str]] = []
    for doc in docs:
        if doc is None:
            continue
        facts = _secret_facts(doc)
        for key, value, task in _module_nodes(doc):
            text = _command_text(value)
            if not (_EXEC.search(text) or _WRAPPER_USE.search(text)):
                continue
            line_no = key.start_mark.line + 1
            if is_suppressed_at(lines, line_no, _ARGV_RULE, mode="same-or-above"):
                continue
            hidden = _hides_log(task)
            for match in _JINJA_EXPR.finditer(text):
                expr = " ".join(match.group(1).split())
                if (
                    _expression_carries_secret(expr, _VALUES, 0)
                    or (hidden and _NEUTRAL_PAYLOAD.search(expr))
                    or facts.intersection(_IDENTIFIER.findall(_LITERAL.sub("''", expr)))
                ):
                    findings.append((line_no, expr))
    return findings


class TestExecArgvSecret(unittest.TestCase):
    def test_scan_flags_secret_and_skips_env_and_stdin(self) -> None:
        flagged = (
            "- shell: >\n"
            "    container exec {{ CID }} tool --password {{ ADMIN_PASSWORD | quote }}\n"
        )
        env_passed = (
            "- shell: >\n"
            "    container exec -e ADMIN_PASSWORD {{ CID }} sh -c 'tool -p \"$ADMIN_PASSWORD\"'\n"
            "  environment:\n"
            '    ADMIN_PASSWORD: "{{ ADMIN_PASSWORD }}"\n'
        )
        stdin_passed = (
            "- shell:\n"
            "    cmd: container exec -i {{ CID }} curl -H @- {{ URL }}\n"
            '    stdin: "Authorization: Bearer {{ API_TOKEN }}"\n'
        )
        lookup_key = (
            "- shell: >\n"
            "    container exec {{ CID }} tool -p{{ lookup('database', app, 'password') }}\n"
        )
        self.assertEqual(scan_exec_argv(flagged), [(1, "ADMIN_PASSWORD | quote")])
        self.assertEqual(scan_exec_argv(env_passed), [])
        self.assertEqual(scan_exec_argv(stdin_passed), [])
        self.assertEqual(
            scan_exec_argv(lookup_key), [(1, "lookup('database', app, 'password')")]
        )

    def test_a_credential_word_inside_the_name_or_a_source_literal_is_a_secret(
        self,
    ) -> None:
        self.assertTrue(_expression_carries_secret("X_API_KEY | quote", {}, 0))
        self.assertTrue(_expression_carries_secret("X_DB_PWD", {}, 0))
        self.assertTrue(
            _expression_carries_secret(
                "lookup('config', app, 'secrets.credentials.api_key')", {}, 0
            )
        )

    def test_a_name_that_only_describes_a_secret_is_not_one(self) -> None:
        self.assertFalse(_expression_carries_secret("X_TOKEN_SCOPES | quote", {}, 0))
        self.assertFalse(_expression_carries_secret("existing_token.id", {}, 0))
        self.assertFalse(
            _expression_carries_secret("pw | password_hash('bcrypt')", {}, 0)
        )

    def test_a_neutral_var_carrying_a_secret_is_followed_one_level(self) -> None:
        values = {"X_JSON_INFO": "{{ {'secret': X_AGENT_SECRET} | to_json }}"}
        self.assertTrue(_expression_carries_secret("X_JSON_INFO", values, 0))

    def test_a_var_wrapping_an_exec_counts_as_the_exec(self) -> None:
        values = {"X_EXEC": "container exec -u www x", "X_OCC": "{{ X_EXEC }} occ"}
        self.assertEqual(_exec_wrappers(values), frozenset({"X_EXEC", "X_OCC"}))

    def test_a_neutral_payload_convicts_only_where_the_task_hides_its_log(
        self,
    ) -> None:
        task = (
            "- shell: >\n"
            "    container exec {{ CID }} occ config:app:set a k"
            " --value={{ item.value | quote }}\n"
        )
        self.assertEqual(
            scan_exec_argv(task + "  no_log: true\n"), [(1, "item.value | quote")]
        )
        self.assertEqual(
            scan_exec_argv(task + '  no_log: "{{ MASK | bool }}"\n'),
            [(1, "item.value | quote")],
        )
        self.assertEqual(scan_exec_argv(task), [])
        self.assertEqual(scan_exec_argv(task + "  no_log: false\n"), [])

    def test_container_run_counts_as_an_exec(self) -> None:
        self.assertEqual(
            scan_exec_argv(
                "- shell: >\n"
                "    docker run --rm img tool --password {{ ADMIN_PASSWORD }}\n"
            ),
            [(1, "ADMIN_PASSWORD")],
        )

    def test_a_fact_whose_definition_holds_a_secret_is_one_on_the_exec_line(
        self,
    ) -> None:
        facts = (
            "- set_fact:\n"
            "    user_payload:\n"
            '      password: "{{ consumer_pw }}"\n'
            '      roles: ["x"]\n'
            "    role_payload:\n"
            '      roles: ["x"]\n'
            "    stale_uuids: \"{{ app_passwords | map(attribute='uuid') }}\"\n"
            "- shell: >\n"
            "    container exec {{ CID }} curl -d {{ user_payload | to_json | quote }}\n"
            "- shell: >\n"
            "    container exec {{ CID }} curl -d {{ role_payload | to_json | quote }}\n"
            "- shell: >\n"
            "    container exec {{ CID }} wp delete {{ stale_uuids | join(' ') }}\n"
        )
        self.assertEqual(scan_exec_argv(facts), [(8, "user_payload | to_json | quote")])

    def test_no_secret_in_exec_argv(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"), exclude_tests=True
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/") or not (
                "/tasks/" in rel or "/handlers/" in rel
            ):
                continue
            findings.extend(
                f"- {rel}:{line}: {{{{ {expr} }}}}"
                for line, expr in scan_exec_argv(content)
            )
        if findings:
            self.fail(
                "Secrets on a `container exec` / `docker exec` command line reach "
                "the host process list and the daemon's exec_create event. Hand "
                "them over on the task's `stdin:` (`curl -H @-`, SQL on psql's "
                "stdin) or as `-e NAME` plus the task's `environment:`, or add "
                f"`# nocheck: {_ARGV_RULE} <reason>` above the module key.\n"
                + "\n".join(sorted(findings))
            )


class TestEnvAssignments(unittest.TestCase):
    def test_a_jinja_built_assignment_is_read_like_a_plain_one(self) -> None:
        built = "-e {{ ('DB=' ~ lookup('database', app, 'password')) | quote }} x"
        [(name, value)] = list(_env_assignments(built))
        self.assertEqual(name, "DB")
        self.assertTrue(_carries_credential(name, value))

    def test_a_literal_or_a_plain_neutral_value_passes(self) -> None:
        self.assertEqual(list(_env_assignments("-e RAILS_ENV=production x")), [])
        [(name, value)] = list(_env_assignments("-e SITE_URL={{ BASE_URL }} x"))
        self.assertFalse(_carries_credential(name, value))


class TestContainerExecEnvPassesNoValue(unittest.TestCase):
    def test_container_exec_env_flags_carry_no_value(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_EXTENSIONS
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if line.lstrip().startswith("#"):
                    continue
                for name, value in _env_assignments(line):
                    if not _carries_credential(name, value):
                        continue
                    line_no = idx + 1
                    if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                        continue
                    findings.append((rel, line_no, f"-e {name}={value.strip()[:60]}"))

            if not rel.endswith((".yml", ".yaml")):
                continue
            try:
                doc = load_yaml_any(path_str)
            except Exception:  # pragma: no cover - malformed YAML is another rule's
                continue
            for argv in _argv_lists(doc):
                for element in argv:
                    if not isinstance(element, str):
                        continue
                    assignment = _ARGV_ASSIGNMENT.match(element)
                    if not assignment:
                        continue
                    name, value = assignment.group(1), assignment.group(2)
                    if not _INTERPOLATED.search(value):
                        continue
                    if not _carries_credential(name, value):
                        continue
                    line_no = next(
                        (
                            number
                            for number, line in enumerate(lines, 1)
                            if f"{name}=" in line
                        ),
                        1,
                    )
                    if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                        continue
                    findings.append((rel, line_no, f"argv {name}={value.strip()[:52]}"))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {snip}"
                for p, ln, snip in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                f"Found {len(set(findings))} `-e NAME=VALUE` flags carrying an "
                "interpolated value. The value lands in the argv of the "
                "host-side container call, where `ps` shows it to every local "
                "account while the call runs, and `no_log` cannot mask a "
                "process table.\n\n"
                "Fix one of:\n"
                "  - pass the name alone, `-e NAME`, and supply the value "
                "through the task's `environment:` mapping (Ansible) or an "
                "`export NAME=...` in the script (shell). With `script` the "
                "value then reaches no argv; with `shell` and `command` it "
                "appears once on the module wrapper's line instead of on "
                "every container call;\n"
                "  - for a templated value that provably carries no secret, "
                "add `# nocheck: container-exec-env-value -- <reason>` on the "
                "same line or the line above, naming what the value is.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
