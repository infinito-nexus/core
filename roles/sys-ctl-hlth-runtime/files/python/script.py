#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass

PROBE_MARKER = "INFINITO-RUNTIME-PROBE"
HARDENED_SETTINGS = ("expose_php", "session.upload_progress.enabled")
PHP_PROBE = (
    f'echo "\\n{PROBE_MARKER}|", PHP_VERSION, "|", ini_get("expose_php"), "|", '
    'ini_get("session.upload_progress.enabled"), "\\n";'
)
NO_BINARY_EXIT_CODES = frozenset({126, 127})
EXEC_TIMEOUT_SECONDS = 60
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
ENABLED_VALUES = frozenset({"1", "on", "yes", "true"})


@dataclass(frozen=True)
class Container:
    id: str
    name: str
    stack: str | None
    service: str | None


@dataclass(frozen=True)
class PhpProbe:
    version: str
    settings: dict


class ProbeError(RuntimeError):
    pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check PHP versions and hardening of running containers."
    )
    parser.add_argument(
        "--floors",
        required=True,
        help='JSON: {"php": {"<major>.<minor>": "<lowest patched version>"}}',
    )
    parser.add_argument(
        "--hardened",
        required=True,
        help='JSON: {"<stack>": ["<service mounting php_hardening>", ...]}',
    )
    return parser.parse_args(argv)


def identity(labels: dict | None) -> tuple[str | None, str | None]:
    """Return the ``(stack, service)`` a container belongs to.

    Args:
        labels: the container's ``Config.Labels``, ``None`` when it has none.

    Returns:
        The swarm stack and service or the compose project and service;
        ``(None, None)`` for a container started outside both.
    """
    if not labels:
        return None, None
    stack = labels.get("com.docker.stack.namespace")
    if stack:
        service = labels["com.docker.swarm.service.name"]
        return stack, service.removeprefix(f"{stack}_")
    project = labels.get("com.docker.compose.project")
    if project:
        return project, labels["com.docker.compose.service"]
    return None, None


def running_containers() -> list[Container]:
    ids = subprocess.run(
        ["container", "ps", "-q", "--no-trunc"],
        capture_output=True,
        text=True,
        check=True,
        timeout=EXEC_TIMEOUT_SECONDS,
    ).stdout.split()
    if not ids:
        return []
    inspected = json.loads(
        subprocess.run(
            ["container", "inspect", "--type", "container", *ids],
            capture_output=True,
            text=True,
            check=True,
            timeout=EXEC_TIMEOUT_SECONDS,
        ).stdout
    )
    containers = []
    for entry in inspected:
        stack, service = identity(entry["Config"]["Labels"])
        containers.append(
            Container(
                id=entry["Id"],
                name=entry["Name"].lstrip("/"),
                stack=stack,
                service=service,
            )
        )
    return containers


def parse_probe(stdout: str) -> PhpProbe:
    """Read the probe line out of the ``php -r`` output.

    Args:
        stdout: everything php printed, startup warnings included.

    Returns:
        The PHP version and whether each of HARDENED_SETTINGS is on.
    """
    for line in stdout.splitlines():
        if not line.startswith(f"{PROBE_MARKER}|"):
            continue
        fields = line.split("|")[1:]
        if len(fields) != 1 + len(HARDENED_SETTINGS):
            raise ProbeError(f"malformed probe line: {line!r}")
        version, *values = fields
        return PhpProbe(
            version=version,
            settings={
                name: value.strip().lower() in ENABLED_VALUES
                for name, value in zip(HARDENED_SETTINGS, values, strict=True)
            },
        )
    raise ProbeError(f"php printed no probe line: {stdout.strip()!r}")


def probe_php(container_id: str) -> PhpProbe | None:
    """Run the PHP probe inside a container.

    Args:
        container_id: the container to exec into.

    Returns:
        The probe result, or ``None`` when the container has no ``php``.
    """
    try:
        result = subprocess.run(
            ["container", "exec", container_id, "php", "-r", PHP_PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=EXEC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"php did not answer within {exc.timeout}s") from exc
    if result.returncode in NO_BINARY_EXIT_CODES:
        return None
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip()
        raise ProbeError(f"php exited {result.returncode}: {output}")
    return parse_probe(result.stdout)


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = VERSION_PATTERN.match(version)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _line_tuple(line: str) -> tuple[int, int]:
    major, minor = line.split(".")
    return int(major), int(minor)


def floor_violation(version: str, floors: dict) -> str | None:
    """Judge a runtime version against the floors of its runtime.

    Args:
        version: the version the runtime reports, e.g. ``8.3.12`` or
            ``8.1.2-1ubuntu2.14``.
        floors: ``{"<major>.<minor>": "<lowest patched version>"}``.

    Returns:
        ``None`` when the version is at or above its line's floor or on a line
        newer than every floor, otherwise the reason it fails.
    """
    current = _version_tuple(version)
    if current is None:
        return f"unparsable version {version!r}"
    line = f"{current[0]}.{current[1]}"
    if line in floors:
        floor = floors[line]
        if current < _version_tuple(floor):
            return f"{version} is below the security floor {floor}"
        return None
    if current[:2] > max(_line_tuple(key) for key in floors):
        return None
    return f"{version} runs the end-of-life line {line}"


def check(
    containers: list[Container],
    php_floors: dict,
    hardened: dict,
    probe,
) -> tuple[list[str], list[str]]:
    """Evaluate every container.

    Args:
        containers: the running containers.
        php_floors: the PHP floors, see :func:`floor_violation`.
        hardened: ``{stack: [service, ...]}`` that must run hardened PHP.
        probe: callable returning a :class:`PhpProbe` or ``None`` per id.

    Returns:
        ``(failures, infos)`` as printable lines.
    """
    failures: list[str] = []
    infos: list[str] = []
    for container in sorted(containers, key=lambda c: c.name):
        in_hardened_stack = container.stack in hardened
        must_harden = (
            in_hardened_stack and container.service in hardened[container.stack]
        )
        try:
            result = probe(container.id)
        except ProbeError as exc:
            failures.append(f"{container.name}: {exc}")
            continue
        if result is None:
            if must_harden:
                failures.append(
                    f"{container.name}: declares php_hardening but has no php to verify it"
                )
            continue
        violation = floor_violation(result.version, php_floors)
        if violation:
            failures.append(f"{container.name}: PHP {violation}")
        enabled = [name for name, on in result.settings.items() if on]
        if not enabled:
            continue
        message = f"{container.name}: {', '.join(enabled)} on"
        if must_harden:
            failures.append(f"{message}, the php_hardening ini is not in effect")
        elif in_hardened_stack:
            infos.append(f"{message} (sidecar without php_hardening)")
    return failures, infos


def main(argv=None) -> int:
    args = parse_args(argv)
    php_floors = json.loads(args.floors)["php"]
    hardened = json.loads(args.hardened)
    try:
        containers = running_containers()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        print(f"❌ listing the running containers failed: {exc}")
        return 1
    failures, infos = check(containers, php_floors, hardened, probe_php)
    for line in infos:
        print(f"ℹ️ {line}")
    for line in failures:
        print(f"❌ {line}")
    if failures:
        print(f"🚨 {len(failures)} runtime finding(s).")
        return 1
    print("✅ Every PHP runtime is at or above its floor and hardened where declared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
