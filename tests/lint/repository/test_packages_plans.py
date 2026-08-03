"""Lint: every declaration produces an executable install plan.

A declaration can pass the shape and coverage lints and still blow up at
deploy time, because :func:`~utils.packages.plan.build_plan` reads keys a
repository definition may omit. This walks the real registry - every id,
every default distribution, both states - and requires a plan that names
only modules a deploy can actually resolve.
"""

from __future__ import annotations

import unittest

from utils.packages.calls import STATE_ABSENT, STATE_PRESENT
from utils.packages.plan import build_plan
from utils.packages.registry import build_registry, resolve
from utils.packages.schema import DISTRO_FAMILY

from . import PROJECT_ROOT

ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "ansible.builtin.command",
        "ansible.builtin.dnf",
        "ansible.builtin.lineinfile",
        "ansible.builtin.package",
        "ansible.builtin.replace",
        "ansible.builtin.user",
        "ansible.builtin.yum_repository",
        "community.general.copr",
        "community.general.pacman",
        "kewlfft.aur.aur",
    }
)
"""Modules a package install may invoke. Widening this set means a deploy
gains a new dependency, which is a decision, not a side effect: add the
collection to requirements/requirements.galaxy.yml in the same change."""


class TestPackagePlans(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_registry(PROJECT_ROOT)

    def _plans(self):
        for package_id, declaration in sorted(self.registry.items()):
            for distro in sorted(DISTRO_FAMILY):
                spec = resolve(declaration, distro)
                if spec is None:
                    continue
                for state in (STATE_PRESENT, STATE_ABSENT):
                    yield package_id, distro, state, spec

    def _buildable(self):
        """Plans that build, so only one test reports an unbuildable one."""
        for package_id, distro, state, spec in self._plans():
            try:
                plan = build_plan(spec, state)
            except Exception:
                continue
            yield package_id, distro, state, spec, plan

    def test_every_declaration_builds_a_plan(self) -> None:
        offenders: list[str] = []
        checked = 0
        for package_id, distro, state, spec in self._plans():
            checked += 1
            try:
                build_plan(spec, state)
            except Exception as exc:
                offenders.append(
                    f"{package_id} / {distro} / {state}: {type(exc).__name__}: {exc}"
                )

        self.assertGreater(checked, 0, "the registry resolved nothing to plan")
        if offenders:
            self.fail(
                f"{len(offenders)} of {checked} declaration(s) raise while their "
                "install plan is built, so the deploy would fail on them:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_plans_name_only_allowed_modules(self) -> None:
        offenders: list[str] = []
        for package_id, distro, state, _spec, plan in self._buildable():
            offenders.extend(
                f"{package_id} / {distro} / {state}: '{call.module}'"
                for call in plan
                if call.module not in ALLOWED_MODULES
            )

        if offenders:
            self.fail(
                f"{len(offenders)} plan step(s) name a module outside the "
                "allowed set. Declare the collection in "
                "requirements/requirements.galaxy.yml and add the module to "
                "ALLOWED_MODULES in the same change:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_a_present_plan_installs_the_declared_names(self) -> None:
        offenders: list[str] = []
        for package_id, distro, state, spec, plan in self._buildable():
            if state != STATE_PRESENT or not spec.names:
                continue
            installed: set[str] = set()
            for call in plan:
                name = call.args.get("name")
                installed.update(name if isinstance(name, list) else [])
            missing = sorted(set(spec.names) - installed)
            if missing:
                offenders.append(
                    f"{package_id} / {distro}: plan never installs {', '.join(missing)}"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} plan(s) drop a declared name on the way to "
                "the install call:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
