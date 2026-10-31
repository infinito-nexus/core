"""Hard-fail when a `required_by` block in meta/services.yml uses the flat
`{categories, roles}` form instead of scoping to deploy modes.

Every `required_by` MUST nest its spec under `compose:` and/or `swarm:` so the
deploy-coverage verifier (cli.meta.roles.services.called) can enforce the
requirement per deploy mode. A flat block is ambiguous across modes and is
rejected; each present mode block must carry `categories` and/or `roles`.

`runtimes:` may sit beside the mode blocks as a list of RUNTIME values. It
narrows the requirement to those runtimes, which is orthogonal to the deploy
mode: a role the playbook only includes in a test runtime must not be demanded
of a production deploy.

Mirror to both modes to preserve the previous (mode-agnostic) behavior; declare
a single mode only when the role genuinely applies to that mode (e.g.
sys-ctl-rpr-container-* repair compose compositions and are compose-only).
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
_MODE_KEYS = {"compose", "swarm"}
_SCOPE_KEYS = _MODE_KEYS | {"runtimes"}
_SPEC_KEYS = {"categories", "roles"}


class TestRequiredByModeKeys(unittest.TestCase):
    def test_required_by_scopes_to_deploy_modes(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            services_yml = role_dir / ROLE_FILE_META_SERVICES
            if not services_yml.is_file():
                continue
            data = load_yaml_any(str(services_yml), default_if_missing={})
            if not isinstance(data, dict):
                continue
            rel = services_yml.relative_to(PROJECT_ROOT).as_posix()
            for entity, spec in data.items():
                if not isinstance(spec, dict):
                    continue
                rb = spec.get("required_by")
                if not isinstance(rb, dict):
                    continue
                keys = set(rb.keys())
                if not (keys & _MODE_KEYS) or not keys <= _SCOPE_KEYS:
                    offenders.append(
                        f"{rel} [{entity}]: required_by keys {sorted(keys)} "
                        "(expected 'compose' and/or 'swarm', optionally 'runtimes')"
                    )
                    continue
                runtimes = rb.get("runtimes")
                if "runtimes" in keys and not (
                    isinstance(runtimes, list)
                    and runtimes
                    and all(isinstance(r, str) for r in runtimes)
                ):
                    offenders.append(
                        f"{rel} [{entity}].required_by.runtimes: expected a "
                        "non-empty list of RUNTIME names"
                    )
                for mode in sorted(keys & _MODE_KEYS):
                    sub = rb[mode]
                    if not isinstance(sub, dict) or not (set(sub) & _SPEC_KEYS):
                        offenders.append(
                            f"{rel} [{entity}].required_by.{mode}: expected a "
                            "mapping with 'categories' and/or 'roles'"
                        )

        if not offenders:
            return
        body = "\n".join(f"  - {o}" for o in offenders)
        self.fail(
            f"\n{len(offenders)} required_by block(s) not scoped to deploy "
            f"modes:\n{body}\n\n"
            "Fix: nest the spec under `compose:` and/or `swarm:`, e.g.\n"
            "  required_by:\n"
            "    compose: {categories: [web]}\n"
            "    swarm: {categories: [web]}\n"
            "Mirror to both modes to keep the previous behavior; use a single "
            "mode only when the role genuinely applies to that mode. Add "
            "`runtimes: [dev, act, github]` beside them to narrow the "
            "requirement to those RUNTIME values."
        )


if __name__ == "__main__":
    unittest.main()
