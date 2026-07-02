"""Every `lookup('env', 'INFINITO_*')` in the dev inventories MUST be forwarded
into the DiD via compose.yml's `infinito` service `environment:` block.

For compose deploys Ansible runs inside the `infinito` container; a key the
inventory references but compose.yml does not forward resolves to EMPTY in the
container (silent path divergence: the DIR_VAR_LIB / mailu no-reply-token bug).
Mark a genuinely host-only key (swarm path, never read in the DiD) with a
same-line `# nocheck: <reason>` in the inventory.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

_LOOKUP_ENV_RE = re.compile(
    r"""lookup\(\s*['"]env['"]\s*,\s*['"](?P<key>INFINITO_[A-Z0-9_]+)['"]"""
)
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")
_SERVICE = "infinito"


def _inventory_env_keys() -> dict[str, str]:
    found: dict[str, str] = {}
    inv_dir = PROJECT_ROOT / "inventories" / "development"
    for path in sorted(inv_dir.glob("*.yml")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for index, line in enumerate(read_text(str(path)).splitlines(), start=1):
            if _NOCHECK_RE.search(line):
                continue
            for match in _LOOKUP_ENV_RE.finditer(line):
                found.setdefault(match.group("key"), f"{rel}:{index}")
    return found


def _forwarded_env_keys() -> set[str]:
    data = load_yaml(str(PROJECT_ROOT / "compose.yml"))
    env = data["services"][_SERVICE].get("environment") or {}
    if isinstance(env, list):
        return {item.split("=", 1)[0].strip() for item in env}
    return set(env)


class TestInventoryEnvsForwardedInCompose(unittest.TestCase):
    def test_inventory_env_lookups_are_forwarded_into_the_did(self) -> None:
        referenced = _inventory_env_keys()
        self.assertTrue(
            referenced,
            "no lookup('env', 'INFINITO_*') found in inventories/development/*.yml",
        )

        forwarded = _forwarded_env_keys()
        self.assertTrue(
            forwarded, f"compose.yml '{_SERVICE}' service has no environment block"
        )

        missing = {k: loc for k, loc in referenced.items() if k not in forwarded}
        if not missing:
            return

        report = [
            f"{len(missing)} env key(s) referenced by the dev inventory via "
            "lookup('env', ...) are NOT forwarded into the DiD:",
            "",
            f"Ansible runs inside the '{_SERVICE}' container for compose deploys, so "
            "a key missing from compose.yml's environment block resolves to EMPTY "
            "there (silent path divergence; the DIR_VAR_LIB / mailu no-reply-token "
            f"bug). Forward it in compose.yml under the '{_SERVICE}' service as "
            "`KEY: ${KEY}`, or mark a genuinely host-only key with a same-line "
            "`# nocheck: <reason>` in the inventory.",
            "",
            "Missing:",
        ]
        report.extend(f"  {key}  ({loc})" for key, loc in sorted(missing.items()))
        self.fail("\n".join(report))


if __name__ == "__main__":
    unittest.main()
