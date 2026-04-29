#!/usr/bin/env python3
# cli/meta/applications/ressources/__main__.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from humanfriendly import format_size, parse_size  # noqa: E402

from utils.entity_name_utils import get_entity_name  # noqa: E402
from utils.service_registry import (  # noqa: E402
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)


ROLES_DIR = REPO_ROOT / "roles"


def _as_mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_mem_bytes(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(parse_size(text))
    except Exception:
        return None


def _parse_cpus(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_enabled(service_conf: Dict[str, Any], is_primary: bool) -> bool:
    if "enabled" not in service_conf:
        return is_primary
    raw = service_conf.get("enabled")
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("false", "0", "no", "off"):
        return False
    return True


def _is_shared(service_conf: Dict[str, Any]) -> bool:
    raw = service_conf.get("shared", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


_RESOURCE_KEYS = ("mem_reservation", "mem_limit", "pids_limit", "cpus")
_CONTAINER_KEYS = ("image", "name", "version", "container")


def _looks_like_container(service_conf: Dict[str, Any]) -> bool:
    return any(key in service_conf for key in _RESOURCE_KEYS + _CONTAINER_KEYS)


def _row_for_service(
    role_name: str,
    service_key: str,
    service_conf: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "role": role_name,
        "service": service_key,
        "mem_reservation_raw": service_conf.get("mem_reservation"),
        "mem_limit_raw": service_conf.get("mem_limit"),
        "pids_limit_raw": service_conf.get("pids_limit"),
        "cpus_raw": service_conf.get("cpus"),
        "mem_reservation_bytes": _parse_mem_bytes(service_conf.get("mem_reservation")),
        "mem_limit_bytes": _parse_mem_bytes(service_conf.get("mem_limit")),
        "pids_limit_int": _parse_int(service_conf.get("pids_limit")),
        "cpus_float": _parse_cpus(service_conf.get("cpus")),
    }


def collect_role_resources(
    role_name: str,
    applications: Dict[str, Dict[str, Any]],
    service_registry: Dict[str, Dict[str, Any]],
    visited: set,
    rows: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    if role_name in visited:
        return
    visited.add(role_name)

    if role_name not in applications:
        warnings.append(f"role '{role_name}' has no meta/services.yml; skipping")
        return

    config = _as_mapping(applications[role_name])
    services = _as_mapping(config.get("services"))
    entity_name = get_entity_name(role_name)

    if entity_name and entity_name in services:
        primary_conf = _as_mapping(services.get(entity_name))
        rows.append(_row_for_service(role_name, entity_name, primary_conf))
    else:
        warnings.append(
            f"role '{role_name}' has no services.{entity_name or '<entity>'} entry"
        )

    shared_dependencies: List[str] = []
    for service_key, service_conf in services.items():
        if service_key == entity_name:
            continue
        service_conf = _as_mapping(service_conf)
        if not service_conf:
            continue

        if not _is_enabled(service_conf, is_primary=False):
            continue

        if _is_shared(service_conf):
            provider = _as_mapping(service_registry.get(service_key))
            provider_role = provider.get("role") if provider else None
            if provider_role and provider_role != role_name:
                shared_dependencies.append(provider_role)
            elif not provider_role:
                warnings.append(
                    f"{role_name}: shared service '{service_key}' has no registered provider"
                )
        else:
            if not _looks_like_container(service_conf):
                continue
            rows.append(_row_for_service(role_name, service_key, service_conf))

    for provider_role in shared_dependencies:
        collect_role_resources(
            provider_role,
            applications,
            service_registry,
            visited,
            rows,
            warnings,
        )


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_mem_res = 0
    total_mem_lim = 0
    total_pids = 0
    max_cpus = 0.0
    any_mem_res = any_mem_lim = any_pids = any_cpus = False

    for row in rows:
        if row["mem_reservation_bytes"] is not None:
            total_mem_res += row["mem_reservation_bytes"]
            any_mem_res = True
        if row["mem_limit_bytes"] is not None:
            total_mem_lim += row["mem_limit_bytes"]
            any_mem_lim = True
        if row["pids_limit_int"] is not None:
            total_pids += row["pids_limit_int"]
            any_pids = True
        if row["cpus_float"] is not None:
            max_cpus = max(max_cpus, row["cpus_float"])
            any_cpus = True

    return {
        "mem_reservation_bytes": total_mem_res if any_mem_res else None,
        "mem_limit_bytes": total_mem_lim if any_mem_lim else None,
        "pids_limit_int": total_pids if any_pids else None,
        "cpus_float": max_cpus if any_cpus else None,
    }


def _fmt_mem(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return format_size(value, binary=False)


def _fmt_int(value: Optional[int]) -> str:
    return "-" if value is None else str(value)


def _fmt_float(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def render_text(
    role_name: str,
    rows: List[Dict[str, Any]],
    totals: Dict[str, Any],
    warnings: List[str],
) -> str:
    headers = ["service", "role", "mem_reservation", "mem_limit", "pids_limit", "cpus"]
    table_rows: List[Tuple[str, ...]] = []

    for row in sorted(rows, key=lambda r: (r["service"], r["role"])):
        table_rows.append(
            (
                row["service"],
                row["role"],
                _fmt_mem(row["mem_reservation_bytes"]),
                _fmt_mem(row["mem_limit_bytes"]),
                _fmt_int(row["pids_limit_int"]),
                _fmt_float(row["cpus_float"]),
            )
        )

    total_label = "TOTAL (mem=SUM, pids=SUM max-provisioned, cpus=MAX)"
    total_row = (
        total_label,
        "",
        _fmt_mem(totals["mem_reservation_bytes"]),
        _fmt_mem(totals["mem_limit_bytes"]),
        _fmt_int(totals["pids_limit_int"]),
        _fmt_float(totals["cpus_float"]),
    )

    widths = [len(h) for h in headers]
    for r in table_rows + [total_row]:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: Tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    sep = "  ".join("-" * w for w in widths)
    lines = [
        f"# Resources for role: {role_name}",
        "",
        fmt_row(tuple(headers)),
        sep,
    ]
    lines.extend(fmt_row(r) for r in table_rows)
    lines.append(sep)
    lines.append(fmt_row(total_row))

    if warnings:
        lines.append("")
        lines.append("# Warnings")
        for w in warnings:
            lines.append(f"! {w}")

    return "\n".join(lines)


def render_json(
    role_name: str,
    rows: List[Dict[str, Any]],
    totals: Dict[str, Any],
    warnings: List[str],
) -> str:
    def _row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "role": row["role"],
            "service": row["service"],
            "mem_reservation": {
                "raw": row["mem_reservation_raw"],
                "bytes": row["mem_reservation_bytes"],
                "human": _fmt_mem(row["mem_reservation_bytes"]),
            },
            "mem_limit": {
                "raw": row["mem_limit_raw"],
                "bytes": row["mem_limit_bytes"],
                "human": _fmt_mem(row["mem_limit_bytes"]),
            },
            "pids_limit": {
                "raw": row["pids_limit_raw"],
                "value": row["pids_limit_int"],
            },
            "cpus": {
                "raw": row["cpus_raw"],
                "value": row["cpus_float"],
            },
        }

    payload = {
        "role": role_name,
        "services": [_row(r) for r in rows],
        "totals": {
            "mem_reservation": {
                "bytes": totals["mem_reservation_bytes"],
                "human": _fmt_mem(totals["mem_reservation_bytes"]),
            },
            "mem_limit": {
                "bytes": totals["mem_limit_bytes"],
                "human": _fmt_mem(totals["mem_limit_bytes"]),
            },
            "pids_limit": {"value": totals["pids_limit_int"]},
            "cpus": {"value": totals["cpus_float"]},
            "aggregation": {
                "mem_reservation": "sum",
                "mem_limit": "sum",
                "pids_limit": "sum (max-provisioned; per-container cap, not shared load)",
                "cpus": "max",
            },
        },
        "warnings": warnings,
    }
    return json.dumps(payload, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute aggregated container resources (mem_reservation, mem_limit, "
            "pids_limit, cpus) for an Ansible role. Follows enabled shared services "
            "recursively via the service registry. mem_reservation/mem_limit are "
            "summed; pids_limit is summed as a max-provisioned host-pid budget "
            "(per-container cap, not actual shared load); cpus is max (shared "
            "across containers, not additive)."
        )
    )
    parser.add_argument(
        "--role",
        required=True,
        help="Role name (directory under roles/), e.g. web-app-peertube",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    applications = load_applications_from_roles_dir(ROLES_DIR)
    service_registry = build_service_registry_from_applications(applications)

    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    collect_role_resources(
        role_name=args.role,
        applications=applications,
        service_registry=service_registry,
        visited=set(),
        rows=rows,
        warnings=warnings,
    )

    totals = aggregate(rows)

    if args.format == "json":
        print(render_json(args.role, rows, totals, warnings))
    else:
        print(render_text(args.role, rows, totals, warnings))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
