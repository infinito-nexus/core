"""Enforce the Compose network-include convention.

Each role's ``templates/compose.yml.j2`` MUST attach networks via the shared
Jinja includes so the shared LDAP/DB/Ollama networks stay consistent across
every role:

* Per service block ->
  ``{% include 'roles/sys-svc-container/templates/networks.yml.j2' %}``
* Once at the end (top-level ``networks:`` block) ->
  ``{% include 'roles/sys-svc-compose/templates/networks.yml.j2' %}``

Writing a literal ``networks:`` mapping key by hand is forbidden -- the
includes already derive the correct network name from the service registry
and the role's ``services.*.shared`` flags.

Templates whose only service uses host networking (``network_mode: host``)
are exempt from the top-level include requirement because no Docker
``networks:`` block applies in that case.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

NETWORKS_KEY_RE = re.compile(r"^[ \t]*networks\s*:\s*(#.*)?$")
NETWORK_MODE_RE = re.compile(r"^[ \t]*network_mode\s*:")
JINJA_TAG_RE = re.compile(r"^\s*\{%")
COMMENT_RE = re.compile(r"^\s*#")
BLANK_RE = re.compile(r"^\s*$")

CONTAINER_INCLUDE = "{% include 'roles/sys-svc-container/templates/networks.yml.j2' %}"
COMPOSE_INCLUDE = "{% include 'roles/sys-svc-compose/templates/networks.yml.j2' %}"


def _scan(path) -> tuple[list[int], int, int, bool]:
    """Return (literal-line-numbers, compose-include-count,
    container-include-count, has-network-mode)."""
    text = read_text(str(path))
    literal: list[int] = []
    compose_count = 0
    container_count = 0
    has_network_mode = False

    for idx, line in enumerate(text.splitlines(), start=1):
        if BLANK_RE.match(line) or COMMENT_RE.match(line):
            continue
        if NETWORK_MODE_RE.match(line):
            has_network_mode = True
        if COMPOSE_INCLUDE in line:
            compose_count += 1
            continue
        if CONTAINER_INCLUDE in line:
            container_count += 1
            continue
        if JINJA_TAG_RE.match(line):
            continue
        if NETWORKS_KEY_RE.match(line):
            literal.append(idx)

    return literal, compose_count, container_count, has_network_mode


def _compose_templates() -> list:
    return sorted((PROJECT_ROOT / "roles").glob("*/templates/compose.yml.j2"))


class TestComposeNetworkIncludes(unittest.TestCase):
    def test_no_literal_networks_key(self) -> None:
        offenders: list[str] = []
        for path in _compose_templates():
            literal, *_ = _scan(path)
            if literal:
                rel = path.relative_to(PROJECT_ROOT)
                lines = ", ".join(str(n) for n in literal)
                offenders.append(f"- {rel} (line(s) {lines})")

        if offenders:
            self.fail(
                "Compose templates contain a literal `networks:` mapping key.\n"
                "Each service block MUST attach networks via\n"
                f"  {CONTAINER_INCLUDE}\n"
                "and the top-level `networks:` block MUST be rendered via\n"
                f"  {COMPOSE_INCLUDE}\n"
                "Offenders:\n" + "\n".join(offenders)
            )

    def test_top_level_compose_networks_include_present_once(self) -> None:
        offenders: list[str] = []
        for path in _compose_templates():
            _, compose_count, _, host_mode = _scan(path)
            if host_mode and compose_count == 0:
                continue
            if compose_count != 1:
                rel = path.relative_to(PROJECT_ROOT)
                offenders.append(
                    f"- {rel} (found {compose_count} include(s); expected exactly 1)"
                )

        if offenders:
            self.fail(
                "Each compose.yml.j2 MUST contain exactly one\n"
                f"  {COMPOSE_INCLUDE}\n"
                "to render the top-level `networks:` block (templates whose\n"
                "only service uses `network_mode:` are exempt). Offenders:\n"
                + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
