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

What that buys, stated exactly, because the reduction is real but partial:
with ``ansible.builtin.script`` the value reaches no argv at all, since the
script reads it from an inherited environment. With ``shell`` and ``command``
it still appears once, on the module wrapper's own command line: ansible-core
assembles ``NAME='value' /usr/bin/python …`` from ``Shell.env_prefix`` in
``build_module_command``. The window shrinks from the whole container call,
re-executed on every pass of an ``until:`` retry loop, to the module's own
runtime, and the value no longer repeats per retry. It does not vanish.

The check is on the flag, not on the command in front of it. Associating an
``-e`` with its ``container exec`` is unreliable across a YAML block scalar,
where the flag sits on its own line with no continuation marker, and it would
buy nothing: ``docker run -e`` and ``podman exec -e`` leak the value exactly
the same way.

A literal value cannot carry a secret, so ``-e RAILS_ENV=production`` and
``-e XDG_CONFIG_HOME=/tmp`` pass. Of the interpolated ones the rule takes
those that carry a credential, by either of two independent signals: the
variable's own name, or a credential source in the expression behind it
(``.password``, ``secrets.credentials.``, a ``'password'`` lookup key, a
``_SECRET``/``_TOKEN``/``_PW`` variable).

The second signal is what keeps this from being a name denylist, which would
be no protection on its own: a secret handed over as ``-e FOO={{
lookup('users', 'x').password }}`` is caught by its source even though its
name says nothing. What still slips through is a secret from a source this
rule does not know, under a name that does not say so. Ports, paths and model
names pass deliberately; they are not worth the churn of moving every
interpolated value in the repository.

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


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and rel_path.endswith(_EXTENSIONS)


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
                    if not (
                        _SECRET_NAME.search(name) or _SECRET_SOURCE.search(value)
                    ):
                        continue
                    line_no = idx + 1
                    if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                        continue
                    findings.append((rel, line_no, f"-e {name}={value.strip()[:60]}"))

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
