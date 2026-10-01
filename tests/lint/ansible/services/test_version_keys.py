"""A version only lives behind a key that says it is one.

``version`` is the tag of the entity's own image, ``<what>_version`` any other
upstream version it pins, and ``ref`` the git ref of the repository updater.
A semver behind ``release``, ``tag`` or a name invented once is invisible to
the three updaters and to everyone reading the file, which is how pins go
stale unnoticed.

``update:`` blocks are checked too: a block naming a key the entity does not
carry, or a type the resolver does not know, resolves nothing and says nothing.

Keys that hold a dotted number without naming a version are listed in
``_NOT_VERSIONS``: the container's ``cpus`` and ``bond`` shares and the
``upstream_host`` address.

Per-line opt-out: ``# nocheck: version-key`` above the pin, with a reason.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import is_semver
from utils.update.source import invalid_declarations

from . import PROJECT_ROOT

_RULE = "version-key"
_VALID_KEY = re.compile(r"^(version|[a-z0-9_]+_version|ref)$")
_NOT_VERSIONS = frozenset({"cpus", "bond", "upstream_host"})


def _findings() -> list[str]:
    findings: list[str] = []
    for config_path in sorted(
        (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
    ):
        role = config_path.parts[-3]
        lines = read_text(str(config_path)).splitlines()
        for entity, config in (load_yaml(str(config_path)) or {}).items():
            if not isinstance(config, dict):
                continue
            for key, value in config.items():
                name, text = str(key), str(value)
                if name in _NOT_VERSIONS or _VALID_KEY.match(name):
                    continue
                if "." not in text or not is_semver(text):
                    continue
                number = next(
                    (
                        index
                        for index, line in enumerate(lines, start=1)
                        if re.match(rf"^\s+{re.escape(name)}\s*:", line)
                    ),
                    0,
                )
                if number and is_suppressed_at(lines, number, _RULE):
                    continue
                findings.append(f"- {role}/{entity}.{name} = {text}")
    return sorted(set(findings))


class TestVersionKeys(unittest.TestCase):
    def test_a_version_sits_behind_version_or_its_suffix(self) -> None:
        findings = _findings()
        self.assertEqual(
            findings,
            [],
            "These values look like a version but their key does not say so. "
            "Name the key `version` for the entity's own image tag, "
            "`<what>_version` for any other upstream version, `<what>_tag` for "
            f"a locally built image, or mark it `# nocheck: {_RULE}` with a "
            "reason:\n" + "\n".join(findings),
        )

    def test_every_declared_update_source_resolves_a_key_it_knows(self) -> None:
        problems = invalid_declarations(PROJECT_ROOT)
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
