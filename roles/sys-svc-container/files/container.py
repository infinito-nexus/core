#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def die(msg: str, code: int = 2) -> None:
    print(f"[container] {msg}", file=sys.stderr)
    raise SystemExit(code)


def warn(msg: str) -> None:
    print(f"[container][WARN] {msg}", file=sys.stderr)


def must_exist(path: str, label: str) -> str:
    p = Path(path)
    if not p.exists():
        die(f"{label} does not exist: {path}")
    return str(p)


FLAGS_TAKE_VALUE = {
    "-e",
    "--env",
    "--env-file",
    "--network",
    "--name",
    "-v",
    "--volume",
    "-u",
    "--user",
    "-w",
    "--workdir",
    "--entrypoint",
    "-p",
    "--publish",
    "--security-opt",
    "--add-host",
    "--dns",
    "--dns-search",
    "--dns-option",
    "--label",
    "-l",
    "--hostname",
    "-h",
    "--platform",
    "--restart",
    "--pull",
    "--runtime",
    "--ipc",
    "--pid",
    "--cap-add",
    "--cap-drop",
    "--mount",
    "--gpus",
    "--group-add",
    "--shm-size",
    "--stop-timeout",
    "--stop-signal",
    "--log-driver",
    "--log-opt",
}


def split_docker_run_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """
    Split argv into:
      - run_opts: docker run options (everything before IMAGE)
      - image_and_args: [IMAGE, ...ARGS]
    """
    if not argv:
        die("Usage: container run [docker-run-flags...] IMAGE [COMMAND/ARGS...]")

    run_opts: list[str] = []
    i = 0

    while i < len(argv):
        a = argv[i]

        if a == "--":
            run_opts.append(a)
            i += 1
            break

        if a.startswith("-"):
            run_opts.append(a)
            if a in FLAGS_TAKE_VALUE:
                i += 1
                if i >= len(argv):
                    die(f"docker run flag requires a value: {a}")
                run_opts.append(argv[i])
            i += 1
            continue

        break

    if i >= len(argv):
        die("Missing IMAGE argument")

    return run_opts, argv[i:]


def extract_entrypoint(run_opts: list[str]) -> tuple[list[str], str | None]:
    """
    Remove --entrypoint from run_opts and return (new_opts, entrypoint_value).
    Supports:
      --entrypoint sh
      --entrypoint=sh
    """
    out: list[str] = []
    entrypoint: str | None = None
    i = 0

    while i < len(run_opts):
        a = run_opts[i]

        if a == "--entrypoint":
            if i + 1 >= len(run_opts):
                die("--entrypoint requires a value")
            entrypoint = run_opts[i + 1]
            i += 2
            continue

        if a.startswith("--entrypoint="):
            entrypoint = a.split("=", 1)[1]
            i += 1
            continue

        out.append(a)
        i += 1

    return out, entrypoint


def extract_pull_policy(run_opts: list[str]) -> str:
    """
    Supported:
      --pull always|missing|never
      --pull=always|missing|never
    Default: "missing"
    """
    policy = "missing"
    i = 0

    while i < len(run_opts):
        a = run_opts[i]

        if a == "--pull":
            if i + 1 < len(run_opts):
                policy = str(run_opts[i + 1]).strip() or policy
            i += 2
            continue

        if a.startswith("--pull="):
            policy = a.split("=", 1)[1].strip() or policy
            i += 1
            continue

        i += 1

    policy = policy.lower()
    if policy not in {"always", "missing", "never"}:
        policy = "missing"
    return policy


def docker_pull(image: str) -> None:
    try:
        p = subprocess.run(
            ["docker", "pull", image],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        die("docker not found. Please install Docker.", code=127)

    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        die(f"docker pull failed for {image}: {msg}", code=2)


def inspect_image_entrypoint(image: str) -> list[str]:
    try:
        p = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                image,
                "--format",
                "{{json .Config.Entrypoint}}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        die("docker not found. Please install Docker.", code=127)

    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        die(f"docker image inspect failed for {image}: {msg}", code=2)

    raw = (p.stdout or "").strip()
    if raw in ("", "null", "None"):
        return []

    try:
        val = json.loads(raw)
    except Exception:
        return []

    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str) and val:
        return [val]
    return []


def try_inspect_entrypoint_with_pull(image: str, pull_policy: str) -> list[str]:
    if pull_policy == "always":
        docker_pull(image)

    try:
        return inspect_image_entrypoint(image)
    except SystemExit:
        if pull_policy in {"missing", "always"}:
            docker_pull(image)
            return inspect_image_entrypoint(image)
        raise


def require_ca_env_soft() -> tuple[str, str, str, str, str] | None:
    """
    Return (ca_cert_host, wrapper_host, trust_name, ca_container,
    wrapper_container) or None if CA injection is not available. The two
    container-side paths come from the CA_TRUST group_vars SPOT, forwarded
    as env like the host-side trio.
    """
    ca_host = os.environ.get("CA_TRUST_CERT_HOST", "").strip()
    wrapper_host = os.environ.get("CA_TRUST_WRAPPER_HOST", "").strip()
    trust_name = os.environ.get("CA_TRUST_NAME", "").strip()
    ca_container = os.environ.get("CA_TRUST_CERT_CONTAINER", "").strip()
    wrapper_container = os.environ.get("CA_TRUST_WRAPPER_CONTAINER", "").strip()

    host_missing = []
    if not ca_host:
        host_missing.append("CA_TRUST_CERT_HOST")
    if not wrapper_host:
        host_missing.append("CA_TRUST_WRAPPER_HOST")
    if not trust_name:
        host_missing.append("CA_TRUST_NAME")

    container_missing = []
    if not ca_container:
        container_missing.append("CA_TRUST_CERT_CONTAINER")
    if not wrapper_container:
        container_missing.append("CA_TRUST_WRAPPER_CONTAINER")

    if host_missing:
        warn(
            "CA injection disabled (missing env: "
            + ", ".join(host_missing + container_missing)
            + "). Falling back to plain 'docker run'."
        )
        return None

    if container_missing:
        die(
            "CA injection misconfigured: "
            + ", ".join(container_missing)
            + " not set while the CA_TRUST host env is present. Redeploy the "
            "systemd units / update the caller env to the CA_TRUST group_vars SPOT."
        )

    try:
        ca_host = must_exist(ca_host, "CA trust certificate")
        wrapper_host = must_exist(wrapper_host, "CA trust wrapper script")
    except SystemExit:
        warn(
            "CA injection disabled (CA files not found). Falling back to plain 'docker run'."
        )
        return None

    return ca_host, wrapper_host, trust_name, ca_container, wrapper_container


def exec_docker(cmd: list[str], debug: bool) -> int:
    if debug:
        print(">>> " + " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)

    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        die("docker not found. Please install Docker.", code=127)
    except Exception as exc:
        die(f"Unexpected error: {exc}", code=1)


def container_run(argv: list[str], debug: bool, with_ca: bool) -> int:
    """
    Wrap docker run only if CA injection is available.
    Otherwise fallback to plain docker run.
    """
    if not argv:
        die("Usage: container run [docker-run-flags...] IMAGE [COMMAND/ARGS...]")

    if not with_ca:
        return exec_docker(["docker", "run", *argv], debug=debug)

    ca_env = require_ca_env_soft()
    if not ca_env:
        return exec_docker(["docker", "run", *argv], debug=debug)

    ca_host, wrapper_host, trust_name, ca_container, wrapper_container = ca_env

    run_opts, image_and_args = split_docker_run_argv(argv)
    pull_policy = extract_pull_policy(run_opts)
    run_opts, user_entrypoint = extract_entrypoint(run_opts)

    image = image_and_args[0]
    user_args = image_and_args[1:]

    inject_opts: list[str] = [
        "-v",
        f"{ca_host}:{ca_container}:ro",
        "-v",
        f"{wrapper_host}:{wrapper_container}:ro",
        "-e",
        f"CA_TRUST_CERT={ca_container}",
        "-e",
        f"CA_TRUST_NAME={trust_name}",
        "--entrypoint",
        wrapper_container,
    ]

    final_cmd: list[str] = ["docker", "run"]
    final_cmd.extend(run_opts)
    final_cmd.extend(inject_opts)
    final_cmd.append(image)

    if user_entrypoint:
        final_cmd.append(user_entrypoint)
        final_cmd.extend(user_args)
    else:
        ep = try_inspect_entrypoint_with_pull(image, pull_policy=pull_policy)
        if not ep:
            warn(
                "Image has no ENTRYPOINT and none was provided. "
                "Injecting CA env vars without entrypoint wrapper."
            )
            ca_inject_opts: list[str] = [
                "-v",
                f"{ca_host}:{ca_container}:ro",
                "-e",
                f"CA_TRUST_CERT={ca_container}",
                "-e",
                f"CA_TRUST_NAME={trust_name}",
                "-e",
                f"NODE_EXTRA_CA_CERTS={ca_container}",
                "-e",
                f"SSL_CERT_FILE={ca_container}",
                "-e",
                f"REQUESTS_CA_BUNDLE={ca_container}",
                "-e",
                f"CURL_CA_BUNDLE={ca_container}",
            ]
            return exec_docker(
                ["docker", "run", *run_opts, *ca_inject_opts, image, *user_args],
                debug=debug,
            )

        final_cmd.extend(ep)
        final_cmd.extend(user_args)

    if debug:
        print(">>> " + " ".join(shlex.quote(x) for x in final_cmd), file=sys.stderr)

    os.execvp(final_cmd[0], final_cmd)  # noqa: S606  list-form exec, argv comes from the wrapper itself
    return 0


def passthrough_any(subcmd: str, argv: list[str], debug: bool) -> int:
    """
    Passthrough for ANY docker subcommand.
    This keeps the wrapper future-proof so new docker subcommands don't require
    code changes as long as callers use `container <subcmd> ...`.
    """
    return exec_docker(["docker", subcmd, *argv], debug=debug)


_EXEC_TIMEOUT_UNITS = {"s": 1, "min": 60, "h": 3600, "d": 86400}


def parse_exec_timeout_seconds(value: str) -> int:
    """Parse a systemd-style duration ('60min', '7d', '45s', '2h') to seconds.

    Args:
        value: duration string; a bare number counts as seconds.

    Returns:
        The duration in whole seconds.
    """
    raw = value.strip()
    for suffix, factor in sorted(_EXEC_TIMEOUT_UNITS.items(), key=lambda i: -len(i[0])):
        if raw.endswith(suffix):
            return int(float(raw[: -len(suffix)])) * factor
    return int(float(raw))


def exec_timeout_prefix() -> list[str]:
    """coreutils timeout prefix for `container exec` from CONTAINER_EXEC_TIMEOUT.

    Returns:
        ['timeout', '--kill-after=15', '<seconds>'] when the env var holds a
        positive duration; [] when it is unset, empty or 0 (no limit). Ansible
        task timeouts are SIGALRM-based and sleep through a wedged docker
        socket; this OS-level kill is the enforcement that still fires there.
    """
    raw = os.environ.get("CONTAINER_EXEC_TIMEOUT", "").strip()
    if not raw or raw == "0":
        return []
    try:
        seconds = parse_exec_timeout_seconds(raw)
    except ValueError:
        die(f"Invalid CONTAINER_EXEC_TIMEOUT duration: {raw!r}")
    if seconds <= 0:
        return []
    return ["timeout", "--kill-after=15", str(seconds)]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="container",
        description="Infinito container wrapper (CA-aware docker wrapper).",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print executed docker commands."
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="Subcommand: run|<any docker subcommand>|docker",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)

    ns = parser.parse_args()
    debug = bool(ns.debug)
    cmd = (ns.command or "").strip()

    args = list(ns.args)
    if args and args[0] == "--":
        args = args[1:]

    if not cmd:
        parser.print_help()
        return 2

    if cmd == "run":
        return container_run(
            args,
            debug=debug,
            with_ca=os.environ.get("CA_CONTAINER_ENABLED") == "1",
        )

    if cmd == "docker":
        return exec_docker(["docker", *args], debug=debug)

    if cmd == "exec":
        return exec_docker(
            [*exec_timeout_prefix(), "docker", "exec", *args], debug=debug
        )

    return passthrough_any(cmd, args, debug=debug)


if __name__ == "__main__":
    raise SystemExit(main())
