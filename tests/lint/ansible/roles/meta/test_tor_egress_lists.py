"""Lint guard for every ``tor.egress`` block a role ships.

The block lives in ``meta/services.yml`` and may be overridden per variant in
``meta/variants.yml``. Each one must name a known route, parse, keep ``.onion``
out of ``direct.include`` (an onion name only exists inside Tor), leave both
lists empty under ``none``, and write no entry literally into both includes:
the overlap is legal and takes Tor, but it always means one of the two lines
says something the deploy will not do.

A list given as a Jinja string is derived at deploy time, so it is replaced by
an empty list here; the deploy-time assertion in ``tasks/00_core.yml`` checks
the rendered value.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from utils.networks.tor_egress import LISTS, PARTS, literal_overlaps, violations
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT, load_role_meta, role_dirs


def _literal(egress: Mapping[str, Any]) -> dict[str, Any]:
    literal: dict[str, Any] = dict(egress)
    for list_name in LISTS:
        block = egress.get(list_name)
        block = block if isinstance(block, Mapping) else {}
        literal[list_name] = {
            part: (
                []
                if isinstance(block.get(part), str) and "{{" in block[part]
                else block.get(part)
            )
            for part in PARTS
        }
    return literal


def findings(egress: Mapping[str, Any], route: Any) -> list[str]:
    """Every lint finding for one egress block.

    Args:
        egress: the ``tor.egress`` mapping as the file holds it.
        route: the route the block resolves to.
    """
    literal = _literal(egress)
    found = violations(literal, str(route), False)
    if found:
        return found
    return [
        f"{raw!r} is in both tor.include and direct.include"
        for raw in literal_overlaps(literal)
    ]


def _blocks() -> Iterator[tuple[str, Mapping[str, Any], Any]]:
    for role in role_dirs():
        services = load_role_meta(role / ROLE_FILE_META_SERVICES)
        base = (services or {}).get("tor", {}) if isinstance(services, Mapping) else {}
        egress = base.get("egress") if isinstance(base, Mapping) else None
        if not isinstance(egress, Mapping):
            continue
        rel = Path(role / ROLE_FILE_META_SERVICES).relative_to(PROJECT_ROOT).as_posix()
        yield rel, egress, egress.get("route")
        variants = load_role_meta(role / ROLE_FILE_META_VARIANTS)
        for index, variant in enumerate(variants if isinstance(variants, list) else []):
            override = (
                ((variant or {}).get("services") or {}).get("tor", {}).get("egress")
            )
            if not isinstance(override, Mapping):
                continue
            merged = {**egress, **override}
            rel_variant = (
                Path(role / ROLE_FILE_META_VARIANTS)
                .relative_to(PROJECT_ROOT)
                .as_posix()
            )
            yield f"{rel_variant}[{index}]", merged, merged.get("route")


class TestTorEgressLists(unittest.TestCase):
    def test_at_least_the_provider_declares_a_block(self) -> None:  # nocheck: test.text-presence -- vacuity guard on the parsed egress blocks  # fmt: skip
        """Otherwise the check below passes over nothing."""
        self.assertTrue(
            any(source.startswith("roles/svc-net-tor/") for source, _, _ in _blocks())
        )

    def test_every_shipped_block_is_clean(self) -> None:
        for source, egress, route in _blocks():
            with self.subTest(source=source):
                self.assertEqual(findings(egress, route), [], source)

    def test_the_lint_catches_what_it_guards(self) -> None:
        """Negative controls: each guarded mistake produces a finding.

        Every case starts from a block the lint passes, so a finding names the
        one mistake the case adds and not a missing key.
        """
        infrastructure = {
            "mirrors": [],
            "ntp": [],
            "registry_blob_hosts": {},
            "acme": [],
        }

        def block(tor=(), direct=(), **extra):
            return {
                "tor": {"include": list(tor), "except": []},
                "direct": {"include": list(direct), "except": []},
                "infrastructure": dict(infrastructure),
                **extra,
            }

        self.assertEqual(
            findings(block(), "all"), [], "the base of the controls must be clean"
        )
        derived = block()
        derived["direct"]["include"] = "{{ lookup('tor_egress_infrastructure') }}"
        self.assertEqual(
            findings(derived, "none"), [], "a derived list is checked at deploy time"
        )
        cases = {
            "onion-direct": (block(direct=["abc.onion"]), "all"),
            "overlap": (block(tor=["Example.org"], direct=["*.example.org"]), "all"),
            "none-with-lists": (block(tor=["10.0.0.1"]), "none"),
            "unknown-route": (block(), "everything"),
            "removed-enabled": (block(enabled=True), "onion"),
            "unknown-key": (block(routes="all"), "onion"),
            "host-bits": (block(direct=["192.0.2.7/24"]), "all"),
        }
        broken = block()
        broken["infrastructure"] = {**infrastructure, "ntp": "pool.ntp.org"}
        cases["infrastructure-shape"] = (broken, "all")
        for name, (egress, route) in cases.items():
            with self.subTest(case=name):
                self.assertTrue(findings(egress, route), name)


if __name__ == "__main__":
    unittest.main()
