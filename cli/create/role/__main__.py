#!/usr/bin/env python3
"""Scaffold a new role into ``roles/<role>/``.

Per req-009 this command auto-fills the per-role subnet via
``cli meta networks suggest`` and the per-entity port slots via
``cli meta ports suggest``. The contributor MAY override either
suggestion interactively (`--no-interactive` accepts every default).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from ruamel.yaml import YAML

from cli.meta.networks.suggest.__main__ import (
    capacity_for,
    suggest_subnets,
)
from cli.meta.ports.suggest.__main__ import (
    suggest_relay_ranges,
    suggest_single_ports,
)
from utils.entity_name_utils import get_entity_name


REPO_ROOT = Path(__file__).resolve().parents[3]
ROLE_TEMPLATE_DIR = REPO_ROOT / "templates" / "roles" / "web-app"
ROLES_DIR = REPO_ROOT / "roles"

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def _load_yaml(path: Path):
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.load(f)


def _dump_yaml(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)


def _prompt_conflict(dst_file: Path) -> str:
    print(f"Conflict detected: {dst_file}")
    print("[1] overwrite, [2] skip, [3] merge")
    choice = None
    while choice not in ("1", "2", "3"):
        choice = input("Enter 1, 2, or 3: ").strip()
    return choice


def render_templates(src_dir: Path, dst_dir: Path, context: dict) -> None:
    env = Environment(
        loader=FileSystemLoader(str(src_dir)),
        keep_trailing_newline=True,
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["bool"] = bool
    env.filters["get_entity_name"] = get_entity_name

    for root, _, files in os.walk(src_dir):
        rel = os.path.relpath(root, str(src_dir))
        target = dst_dir / rel
        target.mkdir(parents=True, exist_ok=True)
        for fn in files:
            tpl = env.get_template(os.path.join(rel, fn))
            rendered = tpl.render(**context)
            out = fn[:-3] if fn.endswith(".j2") else fn
            dst_file = target / out

            if dst_file.exists():
                choice = _prompt_conflict(dst_file)
                if choice == "2":
                    print(f"Skipping {dst_file}")
                    continue
                if choice == "3":
                    old_lines = dst_file.read_text(encoding="utf-8").splitlines(
                        keepends=True
                    )
                    new_lines = rendered.splitlines(keepends=True)
                    additions = [line for line in new_lines if line not in old_lines]
                    if additions:
                        with dst_file.open("a", encoding="utf-8") as f:
                            f.writelines(additions)
                        print(f"Merged {len(additions)} lines into {dst_file}")
                    else:
                        print(f"No new lines to merge into {dst_file}")
                    continue
                print(f"Overwriting {dst_file}")
                dst_file.write_text(rendered, encoding="utf-8")
            else:
                dst_file.write_text(rendered, encoding="utf-8")


# Map well-known port categories to the scope they live under. Per req-009
# `local` holds host-bound listeners on 127.0.0.1; `public` holds ports
# bound to the internet-facing interface.
_CATEGORY_SCOPE = {
    "http": "local",
    "websocket": "local",
    "oauth2": "local",
    "database": "local",
    "ldap": "local",
    "ssh": "public",
    "stun_turn": "public",
    "stun_turn_tls": "public",
    "federation": "public",
    "ldaps": "public",
    "relay": "public",
}


def _scope_for_category(category: str) -> str:
    if category not in _CATEGORY_SCOPE:
        raise SystemExit(
            f"Unknown port category {category!r}. Known categories: "
            f"{sorted(_CATEGORY_SCOPE)}."
        )
    return _CATEGORY_SCOPE[category]


def _allocate_subnet(clients: int):
    """Return the suggested subnet CIDR for ``--clients`` size."""
    suggestions, _gaps = suggest_subnets(clients=clients, count=1, explicit_block=None)
    return suggestions[0]


def _write_subnet(role_dir: Path, subnet) -> None:
    server_path = role_dir / "meta" / "server.yml"
    server_data = _load_yaml(server_path) or {}
    networks = server_data.get("networks") or {}
    local = networks.get("local") if isinstance(networks, dict) else None
    if not isinstance(local, dict):
        local = {}
    local["subnet"] = str(subnet)
    networks["local"] = local
    server_data["networks"] = networks
    _dump_yaml(server_data, server_path)


def _allocate_port(scope: str, category: str) -> int:
    suggestions, _gaps = suggest_single_ports(
        scope=scope, category=category, count=1, explicit_range=None
    )
    return suggestions[0]


def _allocate_relay_range(length: int):
    suggestions, _gaps = suggest_relay_ranges(
        length=length, count=1, explicit_range=None
    )
    return suggestions[0]


def _write_port(
    role_dir: Path, entity: str, scope: str, category: str, port_value
) -> None:
    services_path = role_dir / "meta" / "services.yml"
    services = _load_yaml(services_path) or {}
    if not isinstance(services, dict):
        services = {}
    entity_entry = services.get(entity)
    if not isinstance(entity_entry, dict):
        entity_entry = {}
    ports = entity_entry.get("ports")
    if not isinstance(ports, dict):
        ports = {}
    scope_block = ports.get(scope)
    if not isinstance(scope_block, dict):
        scope_block = {}
    scope_block[category] = port_value
    ports[scope] = scope_block
    entity_entry["ports"] = ports
    services[entity] = entity_entry
    _dump_yaml(services, services_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a new Ansible role; auto-allocate its subnet via "
            "`cli meta networks suggest` and its per-entity port slots via "
            "`cli meta ports suggest`."
        ),
    )
    parser.add_argument(
        "-a",
        "--application-id",
        required=True,
        help="Unique application id (the role suffix; the role becomes web-app-<id>).",
    )
    parser.add_argument(
        "-c",
        "--clients",
        type=int,
        default=14,
        help="Number of usable client IPs the role's subnet must fit "
        "(default: 14, fits a /28).",
    )
    parser.add_argument(
        "-p",
        "--ports",
        nargs="*",
        default=[],
        choices=sorted(c for c in _CATEGORY_SCOPE if c != "relay"),
        help="Port categories to assign for the primary entity.",
    )
    parser.add_argument(
        "--relay-length",
        type=int,
        help="If set, allocate a `public.relay` range of this many "
        "consecutive ports for the primary entity.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Accept every suggested allocation without prompting.",
    )
    args = parser.parse_args()

    app = args.application_id
    role = f"web-app-{app}"
    role_dir = ROLES_DIR / role

    if role_dir.exists():
        if (
            not args.no_interactive
            and input(f"Role {role} exists. Continue? [y/N]: ").strip().lower() != "y"
        ):
            print("Aborting.")
            return 1
    else:
        role_dir.mkdir(parents=True)

    render_templates(
        ROLE_TEMPLATE_DIR,
        role_dir,
        {"application_id": app, "role_name": role, "database_type": 0},
    )
    print(f"→ Templates applied to {role_dir}")

    primary_entity = get_entity_name(role) or role

    # Subnet
    subnet = _allocate_subnet(args.clients)
    if not args.no_interactive:
        override = input(
            f"Suggested subnet (capacity={capacity_for(subnet)}): "
            f"{subnet}. Press Enter to accept or type CIDR: "
        ).strip()
        if override:
            import ipaddress

            subnet = ipaddress.IPv4Network(override)
    _write_subnet(role_dir, subnet)
    print(f"→ Wrote subnet {subnet} to {role_dir}/meta/server.yml")

    # Single-int ports
    for category in args.ports:
        scope = _scope_for_category(category)
        port_value = _allocate_port(scope, category)
        if not args.no_interactive:
            override = input(
                f"Suggested {scope}.{category} port: {port_value}. "
                "Press Enter to accept or type a number: "
            ).strip()
            if override:
                port_value = int(override)
        _write_port(role_dir, primary_entity, scope, category, port_value)
        print(
            f"→ Wrote {primary_entity}.ports.{scope}.{category} = "
            f"{port_value} to {role_dir}/meta/services.yml"
        )

    # Optional relay range
    if args.relay_length:
        start, end = _allocate_relay_range(args.relay_length)
        if not args.no_interactive:
            override = input(
                f"Suggested public.relay range: {start}-{end}. "
                "Press Enter to accept or type 'start-end': "
            ).strip()
            if override:
                a, b = override.split("-", 1)
                start, end = int(a), int(b)
        services_path = role_dir / "meta" / "services.yml"
        services = _load_yaml(services_path) or {}
        if not isinstance(services, dict):
            services = {}
        entry = services.get(primary_entity)
        if not isinstance(entry, dict):
            entry = {}
        ports = entry.get("ports")
        if not isinstance(ports, dict):
            ports = {}
        public = ports.get("public")
        if not isinstance(public, dict):
            public = {}
        public["relay"] = {"start": start, "end": end}
        ports["public"] = public
        entry["ports"] = ports
        services[primary_entity] = entry
        _dump_yaml(services, services_path)
        print(
            f"→ Wrote {primary_entity}.ports.public.relay = "
            f"{{start: {start}, end: {end}}} to "
            f"{role_dir}/meta/services.yml"
        )

    print(f"\n✓ Role {role} scaffolded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
