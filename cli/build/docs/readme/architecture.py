"""Derive the per-role ARCHITECTURE sub-page from the role's own metadata.

Four sections, each a mermaid diagram over a different ``meta/`` file::

  Compose       the services `meta/services.yml` declares, with the image and
                the ports each one publishes.
  Swarm         what changes when the same role runs under swarm: the replica
                count and the placement constraint, both resolved per service
                rather than per role.
  Volumes       the decision chain `utils.storage.nfs.swarm_nfs_backed` walks,
                drawn rather than its outcome. Whether a volume is NFS-backed
                depends on the mode, the storage backend, the entry's own
                ``nfs:`` flag AND whether the role is manager-pinned, so a
                diagram that states only the outcome hides the coupling that
                makes a placement change move data silently.
  Dependencies  the cosmos graph, uncapped.

"""

from __future__ import annotations

from pathlib import Path

from cli.build.docs.readme.cosmos import derive_cosmos_mermaid
from cli.build.docs.readme.services import service_keys
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES
from utils.roles.meta_lookup import get_role_placement
from utils.symbol_glossary import to_emoji


def _node_id(raw: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in raw)


def _load(role_dir: Path, filename: str) -> dict:
    path = Path(role_dir) / filename
    if not path.is_file():
        return {}
    loaded = load_yaml_any(str(path), default_if_missing={})
    return loaded if isinstance(loaded, dict) else {}


def _services(role_dir: Path) -> dict:
    """The containers this role renders, each with its ``meta`` entry."""
    meta = _load(role_dir, ROLE_FILE_META_SERVICES)
    return {
        key: meta[key] if isinstance(meta.get(key), dict) else {}
        for key in service_keys(role_dir)
    }


def _ports(entry: dict) -> list[str]:
    internal = entry.get("ports", {})
    internal = internal.get("internal", {}) if isinstance(internal, dict) else {}
    if not isinstance(internal, dict):
        return []
    return [f"{name} {value}" for name, value in internal.items()]


def _compose_mermaid(role_dir: Path, role_name: str) -> str:
    services = _services(role_dir)
    if not services:
        return f'flowchart LR\n    none["{role_name} declares no service"]'

    lines = ["flowchart LR", f"    subgraph role [{role_name}]"]
    for key, entry in services.items():
        image = entry.get("image", "")
        version = entry.get("version", "")
        reference = f"{image}:{version}" if image and version else image or "built here"
        ports = _ports(entry)
        label = f"{key}<br>{reference}"
        if ports:
            label += "<br>" + " · ".join(ports)
        lines.append(f'        svc_{_node_id(key)}["{label}"]')
    lines.append("    end")
    return "\n".join(lines)


def _swarm_mermaid(role_dir: Path, role_name: str, role_placement: str) -> str:
    services = _services(role_dir)
    if not services:
        return f'flowchart LR\n    none["{role_name} declares no service"]'

    lines = ["flowchart LR"]
    for key, entry in services.items():
        replicas = entry.get("replicas")
        placement = entry.get("placement") or role_placement
        node = f"svc_{_node_id(key)}"
        lines.append(f'    {node}["{key}"]')
        count = "from the host group" if replicas is None else str(replicas)
        lines.append(f'    {node} --> rep_{_node_id(key)}["replicas: {count}"]')
        if placement:
            lines.append(
                f"    {node} --> plc_{_node_id(key)}"
                f'["node.role == {placement}"]:::pinned'
            )
    lines.append("    classDef pinned fill:#fef7e0,stroke:#b06000,color:#3d2600;")
    return "\n".join(lines)


def _volumes_mermaid(role_dir: Path, role_name: str, role_placement: str) -> str:
    volumes = _load(role_dir, ROLE_FILE_META_VOLUMES)
    entries = {
        key: entry
        for key, entry in volumes.items()
        if isinstance(entry, dict) and entry.get("type", "volume") == "volume"
    }
    if not entries:
        return f'flowchart LR\n    none["{role_name} declares no volume"]'

    pinned = role_placement == "manager"
    lines = ["flowchart LR"]
    for key, entry in entries.items():
        node = f"vol_{_node_id(key)}"
        opted_out = entry.get("nfs") is False
        label = entry.get("name", key)
        lines.append(f'    {node}["{label}"]')
        if opted_out:
            lines.append(
                f'    {node} -->|"nfs: false"| local_{_node_id(key)}'
                f'["node-local on every node"]:::local'
            )
        elif pinned:
            lines.append(
                f'    {node} -->|"role is manager-pinned"| local_{_node_id(key)}'
                f'["node-local on the manager"]:::local'
            )
        else:
            lines.append(
                f'    {node} -->|"swarm + storage.backend nfs"| nfs_{_node_id(key)}'
                f'["shared over NFS"]:::shared'
            )
            lines.append(
                f'    {node} -->|"compose, or backend local"| cl_{_node_id(key)}'
                f'["node-local"]:::local'
            )
    lines.append("    classDef shared fill:#e6f4ea,stroke:#137333,color:#0b2e13;")
    lines.append("    classDef local fill:#fef7e0,stroke:#b06000,color:#3d2600;")
    return "\n".join(lines)


def _volumes_legend() -> list[str]:
    return [
        "| Condition | Effect |",
        "| --- | --- |",
        "| swarm, `storage.backend: nfs`, no `nfs: false`, role not pinned "
        "| shared over NFS |",
        "| any one of those missing | node-local |",
        "",
        "All four conditions must hold, so pinning a role takes every one of "
        "its volumes node-local. Only the role's primary entry counts as "
        "pinned here: a `placement` on any other service pins that service "
        "alone and leaves the backing of every volume unchanged. The chain is "
        "drawn rather than its result, because that coupling is what makes a "
        "placement change move data without saying so.",
    ]


def _dependencies_legend() -> list[str]:
    return [
        "| Symbol | Meaning |",
        "| --- | --- |",
        "| `1:1` solid | fixed relationship |",
        "| `0..1` dashed | conditional, enabled only in matching deployments |",
        "| `0..0` red | declared but turned off in this role |",
        f"| {to_emoji('host')} | deploys to the host |",
        f"| {to_emoji('compose')} | deploys under compose |",
        f"| {to_emoji('swarm')} | deploys under swarm |",
        f"| {to_emoji('disabled')} | service explicitly turned off |",
        f"| {to_emoji('role_dependency')} | Ansible role dependency from "
        "`meta/main.yml` |",
        "",
        "Every dependency and dependent is listed; the graph is not truncated.",
    ]


def derive_architecture_page(role_dir, role_name: str, app_name: str = "") -> str:
    """Return the ARCHITECTURE.md body for one role, fences included.

    Args:
        role_dir: the role directory.
        role_name: the role identifier.
        app_name: title the README gives the application; the page is titled
            after it so both documents name the application the same way.
    """
    role_dir = Path(role_dir)
    role_placement = (
        get_role_placement(role_dir, role_name=role_name) or ""
    ).strip()
    sections = [
        f"# {app_name or role_name} Architecture",
        "",
        f"## Compose {to_emoji('compose')}",
        "",
        "```mermaid",
        _compose_mermaid(role_dir, role_name),
        "```",
        "",
        f"## Swarm {to_emoji('swarm')}",
        "",
        "```mermaid",
        _swarm_mermaid(role_dir, role_name, role_placement),
        "```",
        "",
        "## Volumes",
        "",
        "```mermaid",
        _volumes_mermaid(role_dir, role_name, role_placement),
        "```",
        "",
        *_volumes_legend(),
        "",
        "## Dependencies",
        "",
        "```mermaid",
        derive_cosmos_mermaid(role_dir, role_name),
        "```",
        "",
        *_dependencies_legend(),
        "",
    ]
    return "\n".join(sections)
