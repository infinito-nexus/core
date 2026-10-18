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

Per-line opt-out
================
``# nocheck: container-exec-env-value -- <reason>`` on the same line or the
immediately preceding non-empty line. Reserved for a templated value that
provably carries no secret, such as a service or role name; state which.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "container-exec-env-value"
_EXTENSIONS = (".yml", ".yaml", ".j2", ".sh")
_ENV_WITH_VALUE = re.compile(r"(?:^|\s)-e\s+([A-Za-z_][A-Za-z0-9_]*)=")
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
                matches = list(_ENV_WITH_VALUE.finditer(line))
                for position, match in enumerate(matches):
                    following = matches[position + 1 :]
                    stop = following[0].start() if following else len(line)
                    name = match.group(1)
                    value = line[match.end() : stop]
                    if not _INTERPOLATED.search(value):
                        continue
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
