"""Lint: a credential does not belong in a volume declared non-secret.

``meta/volumes.yml`` distinguishes ``type: secret`` from ``type: config``, and
the distinction is load-bearing for anyone reading a role: a config volume is
the thing you may show someone, copy into a bug report, or mount read-only for
every process in the container. A template that renders a live client secret or
an account password into one makes that reading false, and the mode these
volumes carry is usually ``0444``, so every process in the container can read
it.

The scan derives the credential vocabulary from how the repository actually
writes secrets rather than from a guess: the ``secrets.credentials`` config
path, the OIDC client secret, a resolved user's password, and the MCP
credential lookup.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: config-volume-secret`` in the head of the role's
  ``meta/volumes.yml``, naming why the credential has to travel this way.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "config-volume-secret"
_NON_SECRET_TYPES = frozenset({"config"})

_SOURCE_FILE = re.compile(r"'([^']+)'\s*\]\s*\|\s*path_join")

_CREDENTIALS = (
    re.compile(r"secrets\.credentials\.[A-Za-z0-9_]+"),
    re.compile(r"OIDC\.CLIENT\.SECRET"),
    re.compile(r"lookup\(\s*'users'[^)]*\)\s*\.\s*password"),
)


def rendered_credentials(text: str) -> list[str]:
    """Return the credential expressions a template renders, deduplicated.

    Args:
        text: the template's contents.
    """
    found = set()
    for pattern in _CREDENTIALS:
        found.update(pattern.findall(text))
    return sorted(found)


def _source_file(entry: Mapping) -> str:
    """Return the file name a volume's source expression names, or "".

    Args:
        entry: one ``meta/volumes.yml`` entry.
    """
    match = _SOURCE_FILE.search(str(entry.get("source") or ""))
    return match[1] if match else ""


def _non_secret_config_volumes() -> list[tuple[str, str, str, str]]:
    """Return ``(role, volume, template path, mode)`` per rendered config volume."""
    found = []
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}")):
        role = path.parent.parent.name
        if is_suppressed_in_head(read_text(str(path)).splitlines(), _RULE):
            continue
        declared = load_yaml_any(str(path), default_if_missing={})
        if not isinstance(declared, Mapping):
            continue
        for name, entry in declared.items():
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("type") or "") not in _NON_SECRET_TYPES:
                continue
            source = _source_file(entry)
            if not source:
                continue
            template = PROJECT_ROOT / "roles" / role / "templates" / f"{source}.j2"
            if template.is_file():
                found.append((role, name, str(template), str(entry.get("mode") or "")))
    return found


class TestConfigVolumeSecrets(unittest.TestCase):
    def test_no_config_volume_renders_a_credential(self) -> None:
        leaking = []
        for role, volume, template, mode in _non_secret_config_volumes():
            rendered = rendered_credentials(read_text(template))
            if rendered:
                leaking.append(
                    f"{role}: volume {volume!r} is declared type config"
                    f"{f' with mode {mode}' if mode else ''} yet its template "
                    f"renders {rendered}"
                )
        self.assertEqual(
            [],
            leaking,
            f"credential(s) rendered into a non-secret volume ({len(leaking)}):\n"
            + "\n".join(f"  - {v}" for v in leaking),
        )

    def test_the_scan_finds_rendered_config_volumes(self) -> None:
        self.assertTrue(
            _non_secret_config_volumes(),
            "no config volume resolves to a template, so this rule would pass "
            "vacuously; check that the source expression is still parsed",
        )

    def test_the_credential_vocabulary_still_matches_the_repository(self) -> None:
        for pattern in _CREDENTIALS:
            hits = [
                path
                for path in (PROJECT_ROOT / "roles").glob("*/templates/*.j2")
                if pattern.search(read_text(str(path)))
            ]
            self.assertTrue(
                hits,
                f"nothing in the repository matches {pattern.pattern!r} any "
                f"more, so that half of the vocabulary silently checks nothing",
            )


if __name__ == "__main__":
    unittest.main()
