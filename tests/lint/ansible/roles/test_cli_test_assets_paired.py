"""Lint: a role's two CLI-test assets are all-or-nothing.

``test-e2e-cli`` needs both halves and reads them from fixed paths::

    roles/<role>/templates/test.env.j2   # discovery + env for the script
    roles/<role>/files/test/test.sh      # the script itself

``discover_cli_roles`` enumerates roles by globbing ``templates/test.env.j2``
alone, then ``run_one.yml`` asserts both assets exist and fails the play when
one is missing. So the two failure modes differ sharply:

* env template without script -> the play fails loudly at deploy time.
* script without env template -> nothing discovers the role, the test never
  runs, and the silence reads exactly like a passing test.
"""

from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

from . import PROJECT_ROOT

_ENV_TEMPLATE = "templates/test.env.j2"
_SCRIPT = "files/test/test.sh"
_STRAY_SCRIPT = "files/test.sh"


def _role_dirs():
    roles_dir = PROJECT_ROOT / "roles"
    if not roles_dir.is_dir():
        return
    for role_dir in sorted(roles_dir.iterdir()):
        if role_dir.is_dir():
            yield role_dir


class TestCliTestAssetsPaired(unittest.TestCase):
    def test_harness_resets_leaked_compose_mode_before_role_vars(self) -> None:
        harness = read_text(str(PROJECT_ROOT / "roles/test-e2e-cli/tasks/run_one.yml"))
        reset = f"roles/sys-svc-compose/{ROLE_FILE_DEFAULTS_MAIN}"
        role_vars = "roles', application_id, 'vars/main.yml"

        self.assertIn(reset, harness)
        self.assertLess(harness.index(reset), harness.index(role_vars))

    def test_env_template_and_script_come_as_a_pair(self) -> None:
        offenders: dict[str, str] = {}
        for role_dir in _role_dirs():
            has_env = (role_dir / _ENV_TEMPLATE).is_file()
            has_script = (role_dir / _SCRIPT).is_file()
            if has_env and not has_script:
                offenders[role_dir.name] = f"has {_ENV_TEMPLATE}, missing {_SCRIPT}"
            elif has_script and not has_env:
                offenders[role_dir.name] = f"has {_SCRIPT}, missing {_ENV_TEMPLATE}"

        if not offenders:
            return

        lines = [
            f"{len(offenders)} role(s) ship only half of the CLI test assets:",
        ]
        lines.extend(f"  - {name}: {why}" for name, why in sorted(offenders.items()))
        lines.append("")
        lines.append(
            f"Add the missing half. A role with only {_SCRIPT} is never "
            "discovered, so its test silently never runs."
        )
        self.fail("\n".join(lines))

    def test_no_test_script_outside_the_discovered_path(self) -> None:
        offenders = [
            role_dir.name
            for role_dir in _role_dirs()
            if (role_dir / _STRAY_SCRIPT).is_file()
        ]

        if not offenders:
            return

        lines = [
            (
                f"{len(offenders)} role(s) keep a test script at "
                f"{_STRAY_SCRIPT}, which no harness reads:"
            ),
        ]
        lines.extend(f"  - {name}" for name in sorted(offenders))
        lines.append("")
        lines.append(f"Move it to {_SCRIPT} and add {_ENV_TEMPLATE}.")
        self.fail("\n".join(lines))
