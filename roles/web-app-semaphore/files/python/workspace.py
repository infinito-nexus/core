"""Args:
operation <result file>: reads WORKSPACE, WORKSPACE_ACTION,
    WORKSPACE_CORE_VERSION, WORKSPACE_CORE_FLOOR, WORKSPACE_OWN_BUILD,
    WORKSPACE_OWN_BUILD_VERSION, WORKSPACE_TARGETS, WORKSPACE_PLATFORM_TOKENS
    (``true`` or ``false``, the store's switch for the platform provider
    secrets), WORKSPACE_PRIVATE_TARGETS (a JSON list of CIDRs) and
    INFINITO_SRC_DIR, and prints the extra variables of the workspace playbook
    as JSON; exit code 2 with the refusal on standard error.
result <operation file> <result file>: prints the result the playbook wrote
    as one JSON line.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import sys
from pathlib import Path

WORKSPACE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
INTERFACE = Path(__file__).resolve().parent.with_name("opentofu") / "interface.json"
HOSTNAME = re.compile(
    json.loads(INTERFACE.read_text("utf-8"))["$defs"]["host_name"]["pattern"]
)
PAIR = re.compile(
    r"^(?:\[(?P<v6>[0-9A-Fa-f:.]+)\]|(?P<host>[^:\[\]]+)):(?P<port>\d{1,5})$"
)
ACTIONS = ("apply", "destroy")
LATEST = "latest"
PLATFORM_TOKENS = {"true": True, "false": False}
APPLY_ONLY = (
    "WORKSPACE_CORE_VERSION",
    "WORKSPACE_TARGETS",
    "WORKSPACE_PLATFORM_TOKENS",
)
RESULT_KEYS = ("alias", "project_id", "read_key", "templates", "workspace")
DESTROY_KEYS = ("stopped_tasks", "workspace")
TEMPLATE_KEYS = (
    "app",
    "arguments",
    "environment_id",
    "environment_variables",
    "git_branch",
    "git_url",
    "inventory_id",
    "playbook",
    "project_id",
    "repository_id",
    "runner_tag",
    "ssh_key_id",
    "survey_variables",
    "template_id",
)


class RefusalError(Exception):
    pass


def released_versions(source):
    """Args:
    source: the core tree of the runner image.

    Returns:
        Every version its changelog releases, newest first.
    """
    return parse_releases((Path(source) / "CHANGELOG.md").read_text(encoding="utf-8"))


def parse_releases(text):
    """Args:
    text: a ``CHANGELOG.md``.

    Returns:
        Every version it releases, newest first.
    """
    versions = {match.group(1) for match in RELEASE.finditer(text)}
    return sorted(versions, key=release_key, reverse=True)


def shipping_releases(released, floor):
    """Args:
    released: :func:`parse_releases`.
    floor: ``WORKSPACE_CORE_FLOOR``, empty while no release ships the
        workspace runner.

    Returns:
        The releases at or above the floor, newest first; none without one.
    """
    return [v for v in released if floor and release_key(v) >= release_key(floor)]


def release_key(version):
    """Args:
    version: a version like 17.0.0.

    Returns:
        Its parts as integers, which order releases.
    """
    return tuple(int(part) for part in version.split("."))


def core_version(value, released, floor, own_build, own_version):
    """Args:
    value: ``WORKSPACE_CORE_VERSION`` as the store sent it.
    released: :func:`released_versions`.
    floor: ``WORKSPACE_CORE_FLOOR``, the first release that ships the
        workspace runner; empty while no release does.
    own_build: ``WORKSPACE_OWN_BUILD``, the image of the deploying core on a
        dev or CI deploy; empty on production.
    own_version: ``WORKSPACE_OWN_BUILD_VERSION``, the version that image
        declares.

    Returns:
        ``(version, base)``: the version the core tree of the workspace runner
        declares, and the own build it builds on, empty for a release. The
        tag of the own build selects it, and so does ``latest`` while an own
        build is set, since a dev or CI deploy tests the deploying core;
        without one ``latest`` is the newest release at or above the floor.
    """
    if floor and not VERSION.match(floor):
        raise RefusalError(f"WORKSPACE_CORE_FLOOR {floor!r} is no version like 17.0.0")
    if own_build and value in (LATEST, own_build.rpartition(":")[2]):
        if not VERSION.match(own_version):
            raise RefusalError(
                f"WORKSPACE_OWN_BUILD_VERSION {own_version!r} is no version like 17.0.0"
            )
        return own_version, own_build
    shipped = f"ships from {floor} on" if floor else "ships in no release yet"
    shipping = shipping_releases(released, floor)
    if value == LATEST:
        if not shipping:
            raise RefusalError(
                "WORKSPACE_CORE_VERSION latest finds no release of the workspace "
                f"runner, which {shipped}"
            )
        return shipping[0], ""
    if not VERSION.match(value or ""):
        raise RefusalError(
            f"WORKSPACE_CORE_VERSION {value!r} is neither latest nor a version like 17.0.0"
        )
    if value not in released:
        raise RefusalError(f"WORKSPACE_CORE_VERSION {value} is no released version")
    if value not in shipping:
        raise RefusalError(
            f"WORKSPACE_CORE_VERSION {value} predates the workspace runner, "
            f"which {shipped}"
        )
    return value, ""


def parse_targets(value):
    """Args:
    value: ``WORKSPACE_TARGETS``, comma-separated ``<host>:<port>`` pairs.

    Returns:
        ``[(host, port)]``; an empty value is a workspace without servers.
    """
    if not value:
        return []
    pairs = []
    for raw in value.split(","):
        match = PAIR.match(raw)
        if not match:
            raise RefusalError(f"WORKSPACE_TARGETS holds the malformed pair {raw!r}")
        host = match.group("v6") or match.group("host")
        port = int(match.group("port"))
        if not 1 <= port <= 65535:
            raise RefusalError(f"WORKSPACE_TARGETS holds the port {port} of {raw!r}")
        if match.group("v6"):
            try:
                ipaddress.IPv6Address(host)
            except ValueError as error:
                raise RefusalError(
                    f"WORKSPACE_TARGETS holds the malformed pair {raw!r}"
                ) from error
        elif not _is_address(host) and not HOSTNAME.match(host):
            raise RefusalError(f"WORKSPACE_TARGETS holds the malformed pair {raw!r}")
        pairs.append((host, port))
    return pairs


def _is_address(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def resolve(host):
    """Args:
    host: a name or an address.

    Returns:
        The first address the resolver answers for it.
    """
    try:
        answers = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise RefusalError(
            f"WORKSPACE_TARGETS names {host}, which does not resolve"
        ) from error
    return answers[0][4][0]


def pin_targets(pairs, private, resolver):
    """Args:
    pairs: :func:`parse_targets`.
    private: the networks ``services.semaphore.workspaces.private_targets`` opens.
    resolver: :func:`resolve` or a stand-in.

    Returns:
        ``[{host, port, address}]``: each pair with the address it resolved to
        once, which every later connection of the workspace uses.
    """
    networks = [ipaddress.ip_network(net, strict=False) for net in private]
    pinned = []
    for host, port in pairs:
        address = ipaddress.ip_address(resolver(host))
        closed = address.is_loopback or address.is_link_local or address.is_unspecified
        opened = any(address in network for network in networks)
        if closed or not (address.is_global or opened):
            raise RefusalError(
                f"WORKSPACE_TARGETS names {host}:{port}, whose address {address} is "
                "neither public nor in services.semaphore.workspaces.private_targets"
            )
        pinned.append({"host": host, "port": port, "address": str(address)})
    return pinned


def operation(env, result_file, resolver=resolve):
    """Args:
    env: the task environment.
    result_file: where the playbook writes the result.
    resolver: :func:`resolve` or a stand-in.

    Returns:
        The extra variables of the workspace playbook.
    """
    workspace = env.get("WORKSPACE", "")
    if not WORKSPACE.match(workspace):
        raise RefusalError(f"WORKSPACE {workspace!r} is no lowercase UUID")
    action = env.get("WORKSPACE_ACTION", "")
    if action not in ACTIONS:
        raise RefusalError(f"WORKSPACE_ACTION {action!r} is neither apply nor destroy")
    variables = {
        "WORKSPACE": workspace,
        "WORKSPACE_ACTION": action,
        "WORKSPACE_RESULT_FILE": result_file,
    }
    if action == "destroy":
        for name in APPLY_ONLY:
            if env.get(name):
                raise RefusalError(f"{name} is not taken by destroy")
        return variables
    platform_tokens = PLATFORM_TOKENS.get(env.get("WORKSPACE_PLATFORM_TOKENS"))
    if platform_tokens is None:
        raise RefusalError(
            f"WORKSPACE_PLATFORM_TOKENS {env.get('WORKSPACE_PLATFORM_TOKENS')!r} "
            f"is neither true nor false"
        )
    version, base = core_version(
        env.get("WORKSPACE_CORE_VERSION", ""),
        released_versions(env["INFINITO_SRC_DIR"]),
        env.get("WORKSPACE_CORE_FLOOR", ""),
        env.get("WORKSPACE_OWN_BUILD", ""),
        env.get("WORKSPACE_OWN_BUILD_VERSION", ""),
    )
    private = json.loads(env.get("WORKSPACE_PRIVATE_TARGETS") or "[]")
    pinned = pin_targets(
        parse_targets(env.get("WORKSPACE_TARGETS", "")), private, resolver
    )
    return {
        **variables,
        "WORKSPACE_CORE_BASE": base,
        "WORKSPACE_CORE_VERSION": version,
        "WORKSPACE_TARGETS": pinned,
        "WORKSPACE_PLATFORM_TOKENS": platform_tokens,
    }


def destroy_result(workspace, written):
    """Args:
    workspace: the ``WORKSPACE`` of the operation.
    written: what the playbook wrote for ``destroy``.

    Returns:
        The last output line of ``destroy``, ``destroyed``, ``stopped_tasks``
        and ``workspace``.
    """
    if tuple(sorted(written)) != DESTROY_KEYS:
        raise RefusalError(f"the playbook wrote the destroy keys {sorted(written)}")
    if written["workspace"] != workspace:
        raise RefusalError("the playbook wrote the result of another workspace")
    stopped = written["stopped_tasks"]
    if isinstance(stopped, bool) or not isinstance(stopped, int) or stopped < 0:
        raise RefusalError(f"the playbook wrote the stopped task count {stopped!r}")
    return json.dumps(
        {"destroyed": True, "stopped_tasks": stopped, "workspace": workspace},
        sort_keys=True,
    )


def result(operation_file, result_file):
    """Args:
    operation_file: the extra variables :func:`operation` printed.
    result_file: what the playbook wrote.

    Returns:
        The last output line of the operation.
    """
    variables = json.loads(Path(operation_file).read_text(encoding="utf-8"))
    if variables["WORKSPACE_ACTION"] == "destroy":
        return destroy_result(
            variables["WORKSPACE"],
            json.loads(Path(result_file).read_text(encoding="utf-8")),
        )
    written = json.loads(Path(result_file).read_text(encoding="utf-8"))
    if tuple(sorted(written)) != RESULT_KEYS:
        raise RefusalError(f"the playbook wrote the result keys {sorted(written)}")
    if written["workspace"] != variables["WORKSPACE"]:
        raise RefusalError("the playbook wrote the result of another workspace")
    if not isinstance(written["templates"], dict) or not written["templates"]:
        raise RefusalError("the playbook wrote no templates object")
    for name, template in written["templates"].items():
        if tuple(sorted(template)) != TEMPLATE_KEYS:
            raise RefusalError(
                f"the playbook wrote the keys {sorted(template)} for {name}"
            )
    return json.dumps(written, sort_keys=True, separators=(",", ":"))


def main(argv, env):
    """Args:
    argv: the command line after the script name.
    env: the task environment.

    Returns:
        The exit code.
    """
    try:
        if argv[:1] == ["operation"] and len(argv) == 2:
            print(json.dumps(operation(env, argv[1]), sort_keys=True))
        elif argv[:1] == ["result"] and len(argv) == 3:
            print(result(argv[1], argv[2]))
        else:
            print(f"workspace.py: unexpected arguments {argv}", file=sys.stderr)
            return 2
    except RefusalError as refusal:
        print(f"workspace.sh: {refusal}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], dict(os.environ)))
