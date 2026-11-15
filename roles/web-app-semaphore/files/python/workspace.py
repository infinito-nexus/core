"""Args:
operation <result file>: reads WORKSPACE, WORKSPACE_ACTION,
    WORKSPACE_CORE_VERSION, WORKSPACE_TARGETS, WORKSPACE_PRIVATE_TARGETS (a
    JSON list of CIDRs) and INFINITO_SRC_DIR, and prints the extra variables
    of the workspace playbook as JSON; exit code 2 with the refusal on
    standard error.
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
    text = (Path(source) / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = {match.group(1) for match in RELEASE.finditer(text)}
    return sorted(
        versions, key=lambda v: tuple(int(p) for p in v.split(".")), reverse=True
    )


def core_version(value, released):
    """Args:
    value: ``WORKSPACE_CORE_VERSION`` as the store sent it.
    released: :func:`released_versions`.

    Returns:
        The released version the workspace runner builds on; ``latest`` is
        the newest one.
    """
    if value == LATEST:
        if not released:
            raise RefusalError(
                "WORKSPACE_CORE_VERSION latest finds no released version"
            )
        return released[0]
    if not VERSION.match(value or ""):
        raise RefusalError(
            f"WORKSPACE_CORE_VERSION {value!r} is neither latest nor a version like 17.0.0"
        )
    if value not in released:
        raise RefusalError(f"WORKSPACE_CORE_VERSION {value} is no released version")
    return value


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
        for name in ("WORKSPACE_CORE_VERSION", "WORKSPACE_TARGETS"):
            if env.get(name):
                raise RefusalError(f"{name} is not taken by destroy")
        return variables
    version = core_version(
        env.get("WORKSPACE_CORE_VERSION", ""),
        released_versions(env["INFINITO_SRC_DIR"]),
    )
    private = json.loads(env.get("WORKSPACE_PRIVATE_TARGETS") or "[]")
    pinned = pin_targets(
        parse_targets(env.get("WORKSPACE_TARGETS", "")), private, resolver
    )
    return {
        **variables,
        "WORKSPACE_CORE_VERSION": version,
        "WORKSPACE_TARGETS": pinned,
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
