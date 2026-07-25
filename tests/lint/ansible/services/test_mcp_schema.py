"""Schema lint for the ``services.mcp`` block in ``roles/*/meta/services.yml``.

A role with an MCP surface declares one ``mcp:`` service entry whose
vocabulary lives in ``utils/roles/applications/services/mcp.py``. This is a
hard lint: a malformed block fails the test. It rejects:

* an unknown key inside the ``mcp`` block,
* a missing or invalid ``direction``,
* a templated value on any MCP-specific field (only ``enabled``/``shared``
  may carry Jinja),
* an invalid ``transport`` / ``exposure`` / ``auth`` / ``auth_subject`` /
  ``implementation``,
* a server-capable block (``direction: server|both``) missing ``auth``,
* ``auth: none`` combined with an ``exposure`` other than ``internal``,
* ``auth_subject: service_account|administrator`` combined with
  ``tools.mutating_tools_enabled: true``,
* a server-capable block missing ``endpoint`` or one of its required keys
  (``service_key``/``path``/``port_key``),
* an ``endpoint.service_key`` that names no service in the same file,
* an ``endpoint.port_key`` that resolves under neither
  ``ports.local`` nor ``ports.internal`` of the referenced service,
* an unknown key under ``endpoint`` or ``tools``,
* a non-boolean value under ``tools``.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-schema`` in the head of a ``meta/services.yml`` file
  exempts the whole file.
* ``# nocheck: mcp-schema`` on (or directly above) the offending line
  exempts that single finding.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from functools import partial

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.mcp import (
    MCP_AUTH_SUBJECTS,
    MCP_AUTHS,
    MCP_DIRECTIONS,
    MCP_ENDPOINT_KEYS,
    MCP_EXPOSURES,
    MCP_IMPLEMENTATIONS,
    MCP_KEYS,
    MCP_PRIVILEGED_AUTH_SUBJECTS,
    MCP_REQUIRED_ENDPOINT_KEYS,
    MCP_SERVER_DIRECTIONS,
    MCP_TOOLS_KEYS,
    MCP_TRANSPORTS,
    value_is_templated,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "mcp-schema"

_ENUMS: tuple[tuple[str, frozenset[str]], ...] = (
    ("direction", MCP_DIRECTIONS),
    ("transport", MCP_TRANSPORTS),
    ("exposure", MCP_EXPOSURES),
    ("auth", MCP_AUTHS),
    ("auth_subject", MCP_AUTH_SUBJECTS),
    ("implementation", MCP_IMPLEMENTATIONS),
)


def _flag(
    errors: list[str], lines: list[str], rel: str, key: str, message: str
) -> None:
    line_no = _locate_line(lines, key)
    if line_no is not None and is_suppressed_at(lines, line_no, _RULE):
        return
    errors.append(f"{message} ({rel})")


def _locate_line(lines: list[str], key: str) -> int | None:
    needle = f"{key}:"
    in_mcp = False
    mcp_indent = 0
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if stripped.startswith("mcp:"):
            in_mcp = True
            mcp_indent = indent
            continue
        if in_mcp:
            if stripped and indent <= mcp_indent and not raw.lstrip().startswith("#"):
                in_mcp = False
                continue
            if stripped.startswith(needle):
                return idx
    return None


class TestMcpSchema(unittest.TestCase):
    """Hard lint: every ``services.mcp`` block obeys the MCP schema."""

    def test_mcp_schema(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        errors: list[str] = []

        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            services_path = role_dir / ROLE_FILE_META_SERVICES
            if not services_path.is_file():
                continue
            role = role_dir.name
            rel = services_path.relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(str(services_path)).splitlines()

            if is_suppressed_in_head(lines, _RULE):
                continue

            try:
                services = load_yaml_any(str(services_path), default_if_missing={})
            except Exception:
                continue
            if not isinstance(services, Mapping):
                continue
            mcp = services.get("mcp")
            if mcp is None:
                continue

            prefix = f"{role}: services.mcp"

            flag = partial(_flag, errors, lines, rel)

            if not isinstance(mcp, Mapping):
                errors.append(f"{prefix} MUST be a mapping. ({rel})")
                continue

            unknown = set(mcp) - MCP_KEYS
            if unknown:
                flag(
                    min(unknown),
                    f"{prefix} has unknown key(s) {sorted(unknown)}",
                )

            for key, allowed in _ENUMS:
                if key not in mcp:
                    continue
                value = mcp.get(key)
                if value_is_templated(value):
                    flag(key, f"{prefix}.{key} MUST be a literal, not Jinja")
                elif value not in allowed:
                    flag(
                        key,
                        f"{prefix}.{key} has invalid value {value!r}; "
                        f"allowed: {sorted(allowed)}",
                    )

            direction = mcp.get("direction")
            if "direction" not in mcp:
                flag("direction", f"{prefix} is missing required 'direction'")

            server_capable = direction in MCP_SERVER_DIRECTIONS

            if server_capable and "auth" not in mcp:
                flag("auth", f"{prefix} server-capable block is missing 'auth'")

            if mcp.get("auth") == "none" and mcp.get("exposure") != "internal":
                flag(
                    "auth",
                    f"{prefix} 'auth: none' requires 'exposure: internal'",
                )

            tools = mcp.get("tools")
            tools = tools if isinstance(tools, Mapping) else {}
            if "tools" in mcp and not isinstance(mcp.get("tools"), Mapping):
                flag("tools", f"{prefix}.tools MUST be a mapping")
            unknown_tools = set(tools) - MCP_TOOLS_KEYS
            if unknown_tools:
                flag(
                    "tools",
                    f"{prefix}.tools has unknown key(s) {sorted(unknown_tools)}",
                )
            for tool_key in MCP_TOOLS_KEYS & set(tools):
                if not isinstance(tools.get(tool_key), bool):
                    flag(
                        tool_key,
                        f"{prefix}.tools.{tool_key} MUST be a boolean",
                    )

            if (
                mcp.get("auth_subject") in MCP_PRIVILEGED_AUTH_SUBJECTS
                and tools.get("mutating_tools_enabled") is True
            ):
                flag(
                    "auth_subject",
                    f"{prefix} '{mcp.get('auth_subject')}' subject requires "
                    "tools.mutating_tools_enabled: false",
                )

            endpoint = mcp.get("endpoint")
            if server_capable:
                if not isinstance(endpoint, Mapping):
                    flag(
                        "endpoint",
                        f"{prefix} server-capable block is missing 'endpoint'",
                    )
                    continue
                missing = MCP_REQUIRED_ENDPOINT_KEYS - set(endpoint)
                if missing:
                    flag(
                        "endpoint",
                        f"{prefix}.endpoint is missing key(s) {sorted(missing)}",
                    )
                unknown_ep = set(endpoint) - MCP_ENDPOINT_KEYS
                if unknown_ep:
                    flag(
                        "endpoint",
                        f"{prefix}.endpoint has unknown key(s) {sorted(unknown_ep)}",
                    )
                service_key = endpoint.get("service_key")
                if service_key is not None:
                    target = services.get(str(service_key))
                    if not isinstance(target, Mapping):
                        flag(
                            "service_key",
                            f"{prefix}.endpoint.service_key {service_key!r} "
                            "names no service in this file",
                        )
                    else:
                        ports = target.get("ports")
                        ports = ports if isinstance(ports, Mapping) else {}
                        port_key = endpoint.get("port_key")
                        if port_key is not None and not any(
                            isinstance(ports.get(ns), Mapping) and port_key in ports[ns]
                            for ns in ("local", "internal")
                        ):
                            flag(
                                "port_key",
                                f"{prefix}.endpoint.port_key {port_key!r} resolves "
                                f"under neither ports.local nor ports.internal "
                                f"of service {service_key!r}",
                            )

        if errors:
            self.fail(
                f"services.mcp schema violations ({len(errors)}):\n"
                + "\n".join(sorted(errors))
            )


if __name__ == "__main__":
    unittest.main()
