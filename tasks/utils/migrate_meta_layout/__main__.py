"""Entry point: ``python3 -m tasks.utils.migrate_meta_layout``."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROLES_DIR = REPO_ROOT / "roles"
NETWORKS_FILE = REPO_ROOT / "group_vars" / "all" / "08_networks.yml"
PORTS_FILE = REPO_ROOT / "group_vars" / "all" / "09_ports.yml"

sys.path.insert(0, str(REPO_ROOT))

from . import yaml_io  # noqa: E402
from .indices import build_network_index, build_port_index  # noqa: E402
from .role_builder import build as build_role_meta  # noqa: E402


_PORT_BANDS = {
    "local": {
        "http": {"start": 8001, "end": 8099},
        "websocket": {"start": 4001, "end": 4099},
        "oauth2": {"start": 16480, "end": 16499},
        "database": {"start": 3306, "end": 5432},
        "ldap": {"start": 389, "end": 389},
    },
    "public": {
        "ssh": {"start": 2201, "end": 2299},
        "stun_turn": {"start": 3478, "end": 3499},
        "stun_turn_tls": {"start": 5349, "end": 5399},
        "federation": {"start": 8448, "end": 8499},
        "ldaps": {"start": 636, "end": 636},
        "relay": {"start": 20000, "end": 59999},
    },
}


def _role_needs_migration(
    role_dir: Path,
    networks: dict,
    ports_for_role: dict,
    relays_for_role: dict,
) -> bool:
    legacy_dirs = any(
        (role_dir / sub).is_dir() for sub in ("config", "schema", "users")
    )
    meta_main_path = role_dir / "meta" / "main.yml"
    meta_main = yaml_io.load(meta_main_path) if meta_main_path.is_file() else None
    galaxy_info = meta_main.get("galaxy_info") if isinstance(meta_main, dict) else None
    galaxy_info = galaxy_info if isinstance(galaxy_info, dict) else {}
    legacy_galaxy = "run_after" in galaxy_info or "lifecycle" in galaxy_info
    has_centralised = (
        role_dir.name in networks
        or role_dir.name in ports_for_role
        or role_dir.name in relays_for_role
    )
    return legacy_dirs or legacy_galaxy or has_centralised


def _strip_centralised_files() -> None:
    networks_doc = yaml_io.load(NETWORKS_FILE) or {}
    if isinstance(networks_doc, dict):
        defaults = networks_doc.get("defaults_networks")
        if isinstance(defaults, dict) and "local" in defaults:
            defaults.pop("local", None)
            if defaults:
                networks_doc["defaults_networks"] = defaults
            else:
                networks_doc.pop("defaults_networks", None)
        networks_doc["PORT_BANDS"] = _PORT_BANDS
        yaml_io.dump(NETWORKS_FILE, networks_doc)
    if PORTS_FILE.is_file():
        PORTS_FILE.unlink()


def main() -> int:
    if not ROLES_DIR.is_dir():
        print(f"roles directory not found at {ROLES_DIR}", file=sys.stderr)
        return 1

    networks = build_network_index(NETWORKS_FILE)
    ports_for_role, relays_for_role = build_port_index(PORTS_FILE, ROLES_DIR)

    touched = 0
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        if not _role_needs_migration(
            role_dir, networks, ports_for_role, relays_for_role
        ):
            continue
        build_role_meta(
            role_dir,
            networks.get(role_dir.name),
            ports_for_role.get(role_dir.name, {}),
            relays_for_role.get(role_dir.name, {}),
        )
        touched += 1

    print(f"migrated {touched} roles", file=sys.stderr)
    _strip_centralised_files()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
