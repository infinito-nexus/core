"""Compare a rendered stack service with the running Swarm service."""

from __future__ import annotations

import re
from collections.abc import Mapping

_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
_SIZE = re.compile(r"^\s*([0-9.]+)\s*([bkmgt]?)i?b?\s*$", re.IGNORECASE)
_DIGEST = re.compile(r"@sha256:[0-9a-f]+$")


class SwarmDriftError(ValueError):
    pass


def _bytes(value) -> int | None:
    if value in (None, ""):
        return None
    match = _SIZE.match(str(value))
    if not match:
        raise SwarmDriftError(f"swarm_drift: unreadable size '{value}'")
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def _nano_cpus(value) -> int | None:
    if value in (None, ""):
        return None
    return round(float(value) * 1_000_000_000)


def _image(value) -> str:
    return _DIGEST.sub("", str(value or ""))


def _env(value) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(k): "" if v is None else str(v) for k, v in value.items()}
    pairs = (str(item).split("=", 1) for item in value or [])
    return {p[0]: p[1] if len(p) > 1 else "" for p in pairs}


def _list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _resources(limits: Mapping, reservations: Mapping) -> dict:
    return {
        "memory": _bytes(limits.get("memory")),
        "cpus": _nano_cpus(limits.get("cpus")),
        "pids": limits.get("pids") or None,
        "reserved_memory": _bytes(reservations.get("memory")),
    }


def _rendered_files(entries, top: Mapping, stack: str) -> set[tuple[str, str]]:
    out = set()
    for entry in entries or []:
        source = entry["source"] if isinstance(entry, Mapping) else str(entry)
        target = entry.get("target", source) if isinstance(entry, Mapping) else source
        name = (top.get(source) or {}).get("name") or f"{stack}_{source}"
        out.add((name, target.rsplit("/", 1)[-1]))
    return out


def _running_files(entries, kind: str) -> set[tuple[str, str]]:
    return {
        (e[f"{kind}Name"], ((e.get("File") or {}).get("Name") or "").rsplit("/", 1)[-1])
        for e in entries or []
    }


def _binds(entries) -> set[tuple[str, str, bool]]:
    out = set()
    for entry in entries or []:
        if (entry.get("type") or entry.get("Type")) != "bind":
            continue
        out.add(
            (
                str(entry.get("source") or entry.get("Source")),
                str(entry.get("target") or entry.get("Target")),
                bool(entry.get("read_only") or entry.get("ReadOnly")),
            )
        )
    return out


def rendered_view(service: Mapping, config: Mapping, stack: str) -> dict:
    """Return the comparable fields of one service of ``docker stack config``.

    Args:
        service: the service's entry under ``services``.
        config: the whole ``docker stack config`` document.
        stack: swarm stack name, the prefix of unnamed secrets and configs.
    """
    deploy = service.get("deploy") or {}
    resources = deploy.get("resources") or {}
    return {
        "image": _image(service.get("image")),
        "command": _list(service.get("entrypoint")),
        "args": _list(service.get("command")),
        "env": _env(service.get("environment")),
        "resources": _resources(
            resources.get("limits") or {}, resources.get("reservations") or {}
        ),
        "constraints": sorted((deploy.get("placement") or {}).get("constraints") or []),
        "secrets": _rendered_files(
            service.get("secrets"), config.get("secrets") or {}, stack
        ),
        "configs": _rendered_files(
            service.get("configs"), config.get("configs") or {}, stack
        ),
        "binds": _binds(service.get("volumes")),
    }


def running_view(spec: Mapping) -> dict:
    """Return the comparable fields of ``docker service inspect`` ``.Spec``."""
    task = spec.get("TaskTemplate") or {}
    container = task.get("ContainerSpec") or {}
    resources = task.get("Resources") or {}
    limits = resources.get("Limits") or {}
    reservations = resources.get("Reservations") or {}
    return {
        "image": _image(container.get("Image")),
        "command": _list(container.get("Command")),
        "args": _list(container.get("Args")),
        "env": _env(container.get("Env")),
        "resources": {
            "memory": limits.get("MemoryBytes") or None,
            "cpus": limits.get("NanoCPUs") or None,
            "pids": limits.get("Pids") or None,
            "reserved_memory": reservations.get("MemoryBytes") or None,
        },
        "constraints": sorted((task.get("Placement") or {}).get("Constraints") or []),
        "secrets": _running_files(container.get("Secrets"), "Secret"),
        "configs": _running_files(container.get("Configs"), "Config"),
        "binds": _binds(container.get("Mounts")),
    }


def drifted_fields(
    service: Mapping, config: Mapping, stack: str, spec: Mapping
) -> list[str]:
    """Return the names of the fields a stack deploy would change, sorted.

    Args:
        service / config / stack: see ``rendered_view``.
        spec: the running service's ``.Spec``.
    """
    want = rendered_view(service, config, stack)
    have = running_view(spec)
    return sorted(key for key in want if want[key] != have[key])


def drift_report(
    service: Mapping, config: Mapping, stack: str, spec: Mapping
) -> list[str]:
    """Return the drifted fields, naming the environment keys that differ.

    Values are left out: the environment and the secret names carry
    credentials and their digests.

    Args:
        service / config / stack: see ``rendered_view``.
        spec: the running service's ``.Spec``.
    """
    want = rendered_view(service, config, stack)
    have = running_view(spec)
    report = []
    for key in sorted(want):
        if want[key] == have[key]:
            continue
        if key == "env":
            keys = set(want["env"]) | set(have["env"])
            report += [
                f"env:{name}"
                for name in sorted(keys)
                if want["env"].get(name) != have["env"].get(name)
            ]
        else:
            report.append(key)
    return report
