"""Every role whose ``templates/compose.yml.j2`` publishes a port mapping
(``services.<entity>.ports.<local|public>.<kind>``) must declare the matching
``ports.internal.<kind>`` for that entity in ``meta/services.yml``.

The swarm ``resolve_upstream`` (``utils/networks/proxy.py``) reads
``services.<entity>.ports.internal.http`` and **hard-fails** (ValueError) when it
is absent. The lint extends that requirement to every published kind
(http, websocket, ssh, ...): each compose mapping has a container-side port, and
declaring it under ``ports.internal`` keeps the role's port surface complete and
consistent for the swarm path (and ready should another kind become proxied).
Compose ignores ``ports.internal``, so the gap stays invisible until a swarm
deploy.

The internal value is the container-side port of the compose mapping (the last
segment of ``- "<host>:<published>:<container_port>"``; literal or Jinja).

Per-role opt-out: ``# nocheck: swarm-internal-port`` in the services.yml head.
"""

from __future__ import annotations

import re
import unittest

import yaml

from utils.annotations.suppress import is_suppressed_in_head

from . import PROJECT_ROOT

_RULE = "swarm-internal-port"
# `services.<entity>.ports.<local|public>.<kind>` reference inside a mapping.
_PUBLISHED_REF = re.compile(r"services\.([\w-]+)\.ports\.(?:local|public)\.(\w+)")


def _entity_internal_kinds(data: object, entity: str) -> set[str]:
    if not isinstance(data, dict):
        return set()
    cfg = data.get(entity)
    if isinstance(cfg, dict) and isinstance(cfg.get("ports"), dict):
        internal = cfg["ports"].get("internal")
        if isinstance(internal, dict):
            return {str(k) for k in internal}
    return set()


def _published(compose_text: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for line in compose_text.splitlines():
        stripped = line.strip()
        # A `- "<host>:<published>:<container>"` publish mapping; `- "KEY=..."`
        # env / command list entries carry `=` and are excluded.
        if stripped.startswith('- "') and "ports." in stripped and "=" not in stripped:
            out.update(_PUBLISHED_REF.findall(stripped))
    return out


class TestSwarmInternalPorts(unittest.TestCase):
    def test_published_ports_declare_internal(self) -> None:
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            compose = role_dir / "templates" / "compose.yml.j2"
            services = role_dir / "meta" / "services.yml"
            if not compose.is_file() or not services.is_file():
                continue

            published = _published(compose.read_text())
            if not published:
                continue

            services_lines = services.read_text().splitlines()
            if is_suppressed_in_head(services_lines, _RULE):
                continue

            data = yaml.safe_load("\n".join(services_lines)) or {}
            for entity, kind in sorted(published):
                if kind not in _entity_internal_kinds(data, entity):
                    findings.append(
                        f"- {role_dir.name}: services.{entity}.ports.internal.{kind}"
                    )

        if findings:
            self.fail(
                "Roles publish a port mapping (services.<entity>.ports.<local|"
                "public>.<kind>) in compose.yml.j2 but do not declare the matching "
                "`ports.internal.<kind>` in meta/services.yml. The swarm "
                "resolve_upstream (utils/networks/proxy.py) hard-fails for the http "
                "upstream, and every published kind needs its container-side port "
                "declared for a complete, swarm-consistent port surface.\n\nAdd "
                "`ports.internal.<kind>: <container_port>` (the container-side port "
                "of the compose mapping) on that entity. Suppress with "
                "`# nocheck: swarm-internal-port` in the services.yml head only when "
                "the kind is genuinely never reached in swarm.\n\nMissing "
                "declarations:\n" + "\n".join(sorted(set(findings)))
            )

    def test_published_mapping_container_comes_from_internal(self) -> None:
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            compose = role_dir / "templates" / "compose.yml.j2"
            services = role_dir / "meta" / "services.yml"
            if not compose.is_file() or not services.is_file():
                continue
            if is_suppressed_in_head(services.read_text().splitlines(), _RULE):
                continue
            for raw in compose.read_text().splitlines():
                stripped = raw.strip()
                if not (
                    stripped.startswith('- "')
                    and "ports." in stripped
                    and "=" not in stripped
                    and _PUBLISHED_REF.search(stripped)
                ):
                    continue
                inner = re.match(r'-\s*"(.*)"', stripped)
                if not inner:
                    continue
                # container port = last ':'-segment of the mapping, minus protocol.
                container = inner.group(1).rsplit(":", 1)[-1].split("/")[0].strip()
                # It must come from ports.internal via a lookup (or a variable that
                # references that lookup), never a hardcoded literal, so the
                # published (local/public) and container (internal) ports stay one
                # declared source of truth.
                if "{{" not in container:
                    findings.append(f"- {role_dir.name}: {stripped}")
        if findings:
            self.fail(
                "compose.yml.j2 port mappings hardcode the container port as a "
                "literal. It must come from ports.internal via a lookup (or a "
                "variable that references it):\n"
                "  {{ lookup('config', application_id, "
                "'services.<entity>.ports.internal.<kind>') }}\n"
                "so the published (local/public) port and the container (internal) "
                "port stay a single declared source of truth.\n\n"
                "Offending mappings:\n" + "\n".join(sorted(set(findings)))
            )


if __name__ == "__main__":
    unittest.main()
