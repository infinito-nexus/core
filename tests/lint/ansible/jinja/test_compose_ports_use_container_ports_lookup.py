"""Flag any raw port-publish mapping in ``*compose.yml.j2`` templates.

The canonical, schema-driven way to publish container ports in this
codebase is the ``container_ports`` lookup, which builds the whole
``ports:`` block from ``[service_name, protocol]`` pairs and reads the
declared ``ports.local`` / ``ports.public`` (host) and ``ports.internal``
(container) values, so the published and container ports stay one source
of truth:

    {{ lookup('container_ports', ['gitea', 'http', DOCKER_BIND_HOST],
              ['gitea', 'ssh']) | indent(4) }}

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

_PORT_SEGMENT = re.compile(
    r"\A(?:\{\{.*\}\}|\$\{[^}]*\}|[\d.]+|[\d-]+)(?:/(?:tcp|udp))?\Z",
)

_LIST_ITEM = re.compile(r"""-\s*["']?(.*?)["']?\s*(?:\#.*)?\Z""")

_LONG_SYNTAX_KEY = re.compile(r"\A-?\s*(?:target|published|mode|protocol):")

_BLOCK_KEY = re.compile(r"\A(ports|expose):\s*(.*)\Z")

_PAIR = re.compile(r"\[\s*'([\w-]+)'\s*,\s*'([\w-]+)'\s*\]")


def _is_scan_target(rel_path: str) -> bool:
    """Every role template that can carry a compose ``ports:`` block.

    ``compose.yml.j2`` and its ``compose.<flavor>.yml.j2`` siblings, plus the
    ``*.yml.j2`` fragments they include: a mapping hand-written in an included
    file publishes exactly the same port as one written inline.
    """
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith(".yml.j2")
    )


def _is_raw_port_mapping(line: str, *, mapping_only: bool = False) -> bool:
    """Whether *line* publishes a port by hand, quoted or not.

    ``mapping_only`` drops the single-segment form. Under ``expose:`` that form
    names a container port for documentation and publishes nothing, so only a
    ``host:container`` mapping there is a publication.
    """
    match = _LIST_ITEM.match(line.strip())
    if match is None:
        return False
    inner = match.group(1).strip()
    if not inner or "=" in inner:
        return False
    segments = [segment.strip() for segment in inner.split(":")]
    if not all(_PORT_SEGMENT.match(segment) for segment in segments):
        return False
    if len(segments) >= 2:
        return True
    return not mapping_only and bool(_PORT_SEGMENT.match(inner))


def _raw_port_lines(lines: list[str]) -> list[int]:
    """1-based line numbers that publish a port by hand.

    The block is tracked by the indentation of its ``ports:`` / ``expose:`` key
    rather than by the next key seen. Keying on the next line closed the block
    on anything shaped like a key, which the long-syntax members ``target:``,
    ``published:``, ``protocol:`` and ``mode:`` are, so the block could never
    end while it was being read; blank, comment and ``{% %}`` lines equally have
    no say in where a YAML block ends.
    """
    found: list[int] = []
    block_indent: int | None = None
    mapping_only = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "{%")):
            continue
        indent = len(line) - len(line.rstrip("\n").lstrip())
        if (
            block_indent is not None
            and indent <= block_indent
            and not stripped.startswith("- ")
        ):
            block_indent = None
        if block_indent is None:
            opener = _BLOCK_KEY.match(stripped)
            if opener:
                block_indent = indent
                mapping_only = opener.group(1) == "expose"
                inline = opener.group(2).strip().strip("[]")
                if inline and _is_raw_port_mapping(
                    "- " + inline, mapping_only=mapping_only
                ):
                    found.append(number)
            continue
        if _LONG_SYNTAX_KEY.match(stripped) or _is_raw_port_mapping(
            line, mapping_only=mapping_only
        ):
            found.append(number)
    return found


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
            findings.extend(
                (rel, number, lines[number - 1].strip())
                for number in _raw_port_lines(lines)
                if not is_suppressed_at(lines, number, _RULE, mode="same-or-above")
            )

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
                "    {{ lookup('container_ports',\n"
                "              ['<svc>', '<proto>', DOCKER_BIND_HOST]) | indent(4) }}\n\n"
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
