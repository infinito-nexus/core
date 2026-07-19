"""Flag any raw port-publish mapping in ``*compose.yml.j2`` templates.

The canonical, schema-driven way to publish container ports in this
codebase is the ``container_ports`` lookup, which builds the whole
``ports:`` block from ``[service_name, protocol]`` pairs and reads the
declared ``ports.local`` / ``ports.public`` (host) and ``ports.internal``
(container) values, so the published and container ports stay one source
of truth:

    {{ lookup('container_ports', ['gitea', 'http'], ['gitea', 'ssh'],
              ip=DOCKER_BIND_HOST) | indent(4) }}

Hand-writing the mapping
``- "{{ ... }}:{{ lookup('config', ..., 'services.<e>.ports.local.<k>') }}:..."``
is the repetitive, drift-prone pattern this rule eliminates. A migrated
``ports:`` block carries the ``container_ports`` call form, which never
contains a literal ``services.<e>.ports.<local|public>.<k>`` reference in
a ``- "..."`` list item, so the token only survives in un-migrated source.

Per-line opt-out: ``# nocheck: compose-ports-must-use-container-ports`` on
the offending line or the immediately preceding non-empty line. Use it
only when the mapping genuinely cannot route through the lookup.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

_RULE = "compose-ports-must-use-container-ports"

# One `:`-delimited segment of a port mapping: a Jinja expression, a numeric
# host/port or dotted IP, or a numeric port with a /tcp|/udp suffix. A volume
# path (`/data`) or healthcheck command word never matches across all segments.
_PORT_SEGMENT = re.compile(r"\A(?:\{\{.*\}\}|[\d.]+|\d+/(?:tcp|udp))\Z")

# The quoted payload of a `- "..."` compose list item.
_LIST_ITEM = re.compile(r'-\s*"([^"]*)"')

# A `['service_name', 'protocol']` pair inside a container_ports lookup call.
_PAIR = re.compile(r"\[\s*'([\w-]+)'\s*,\s*'([\w-]+)'\s*\]")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/") or "/templates/" not in rel_path:
        return False
    name = Path(rel_path).name
    return name.endswith(".yml.j2") and "compose" in name


def _is_raw_port_mapping(line: str) -> bool:
    match = _LIST_ITEM.match(line.strip())
    if match is None:
        return False
    inner = match.group(1)
    if "=" in inner:  # `- "KEY=value"` environment entry, not a port mapping
        return False
    segments = inner.split(":")
    return len(segments) >= 2 and all(
        _PORT_SEGMENT.match(segment.strip()) for segment in segments
    )


class TestComposePortsUseContainerPortsLookup(unittest.TestCase):
    def test_no_raw_port_mapping_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            in_ports_block = False
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("- "):
                    if (
                        in_ports_block
                        and _is_raw_port_mapping(line)
                        and not is_suppressed_at(
                            lines, idx + 1, _RULE, mode="same-or-above"
                        )
                    ):
                        findings.append((rel, idx + 1, stripped))
                    continue
                # Track the enclosing block: a `ports:` key or a container_ports
                # lookup opens it; any other key or lookup (extra_hosts, networks,
                # environment, container_volumes, ...) closes it. This keeps
                # host:ip extra_hosts entries from looking like port mappings.
                if stripped.startswith("{{"):
                    in_ports_block = "container_ports" in stripped
                    continue
                key = re.match(r"[\w-]+:", stripped)
                if key:
                    in_ports_block = key.group(0) == "ports:"

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found raw port-publish mappings in `*compose.yml.j2` templates. "
                "Build the `ports:` block with the container_ports lookup instead, "
                "so the published (local/public) and container (internal) ports stay "
                "a single declared source of truth:\n\n"
                "    {{ lookup('container_ports', ['<svc>', '<proto>'],\n"
                "              ip=DOCKER_BIND_HOST) | indent(4) }}\n\n"
                "One ['<svc>', '<proto>'] pair per published port; the lookup reads "
                "ports.local/public for the host side and ports.internal for the "
                "container side. Mark with "
                "`# nocheck: compose-ports-must-use-container-ports` only when the "
                "mapping genuinely cannot route through the lookup.\n\n"
                f"Offending lines:\n{formatted}"
            )

    def test_container_ports_pairs_declare_internal(self) -> None:
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            compose = role_dir / ROLE_FILE_TEMPL_COMPOSE
            services = role_dir / ROLE_FILE_META_SERVICES
            if not compose.is_file() or not services.is_file():
                continue
            text = read_text(str(compose))
            if "container_ports" not in text:
                continue
            pairs: set[tuple[str, str]] = set()
            for line in text.splitlines():
                if "container_ports" in line:
                    pairs.update(_PAIR.findall(line))
            if not pairs:
                continue
            data = load_yaml_any(str(services), default_if_missing={}) or {}
            for service, protocol in sorted(pairs):
                cfg = data.get(service) if isinstance(data, dict) else None
                internal = (
                    cfg["ports"].get("internal")
                    if isinstance(cfg, dict) and isinstance(cfg.get("ports"), dict)
                    else None
                )
                if not (isinstance(internal, dict) and protocol in internal):
                    findings.append(
                        f"- {role_dir.name}: services.{service}.ports.internal.{protocol}"
                    )
        if findings:
            self.fail(
                "container_ports(['<svc>', '<proto>']) references a port whose "
                "ports.internal.<proto> is not declared in meta/services.yml. The "
                "lookup reads ports.internal.<proto> for the container side and "
                "raises at render when it is missing. Declare it.\n\n"
                "Missing declarations:\n" + "\n".join(sorted(set(findings)))
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
