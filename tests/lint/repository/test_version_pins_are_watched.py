"""Every pinned version in a role is watched by something.

Three updaters bump pins: the Docker updater (``image`` plus ``version``), the
repository updater (``repository`` plus ``ref``) and the version-source
resolver (an ``update:`` block naming the upstream). A pin outside all three is
frozen silently, and nothing tells the next reader whether that was a decision
or an oversight.

Scope: every ``roles/*/meta/services.yml`` value whose key names a version and
whose content is a semver. Moving tags (``latest``, ``stable``, a branch name)
are not pins and are ignored.

Per-line opt-out: ``# nocheck: unwatched-version`` above the pin, with a
reason, for a version that must stay where it is. An existing
``# nocheck: docker-version`` or ``# nocheck: repository-version`` counts as
the same statement: it already says this pin is not to be bumped.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import is_semver
from utils.update.docker import collect_entries as docker_entries
from utils.update.repository import collect_entries as repository_entries
from utils.update.source import collect_entries as source_entries

from . import PROJECT_ROOT

_RULE = "unwatched-version"
_VERSION_KEY = re.compile(r"(^|_)(version|release|ref|tag)$")


def _watched() -> set[tuple[str, str, str]]:
    """Return ``(role, entity, key)`` of every pin an updater already bumps."""
    watched = {(e.role, e.service, "version") for e in docker_entries(PROJECT_ROOT)}
    watched |= {
        (e.role, e.entity_path[-1] if e.entity_path else "", "ref")
        for e in repository_entries(PROJECT_ROOT)
    }
    watched |= {(e.role, e.entity, e.key) for e in source_entries(PROJECT_ROOT)}
    return watched


def _findings() -> list[str]:
    watched = _watched()
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
                text = str(value)
                if not _VERSION_KEY.search(str(key)) or not is_semver(text):
                    continue
                if (role, str(entity), str(key)) in watched:
                    continue
                number = next(
                    (
                        index
                        for index, line in enumerate(lines, start=1)
                        if re.match(
                            rf"^\s+{re.escape(str(key))}\s*:\s*[\"']?{re.escape(text)}",
                            line,
                        )
                    ),
                    0,
                )
                if number and any(
                    is_suppressed_at(lines, number, rule)
                    for rule in (_RULE, "docker-version", "repository-version")
                ):
                    continue
                findings.append(f"- {role}/{entity}.{key} = {text}")
    return sorted(set(findings))


class TestVersionPinsAreWatched(unittest.TestCase):
    def test_every_semver_pin_is_watched_or_opted_out(self) -> None:
        findings = _findings()
        self.assertEqual(
            findings,
            [],
            "These versions are pinned but nothing bumps them. Declare the "
            "upstream next to the pin:\n\n"
            "    update:\n"
            "      key: <the pinned key, omit for version>\n"
            "      type: git_tags | registry_tags | npm | http_regex | script\n"
            "      ...\n\n"
            f"or mark the pin with `# nocheck: {_RULE}` and a reason.\n\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
