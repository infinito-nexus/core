#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# docker run flags that take a value
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


# ---------------------------------------------------------------------------
# docker run argument parsing
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# CA handling (SOFT)
# ---------------------------------------------------------------------------


def require_ca_env_soft() -> tuple[str, str, str] | None:
    """
    Return (ca_cert_host, wrapper_host, trust_name)
    or None if CA injection is not available.
    """
    ca_host = os.environ.get("CA_TRUST_CERT_HOST", "").strip()
    wrapper_host = os.environ.get("CA_TRUST_WRAPPER_HOST", "").strip()
    trust_name = os.environ.get("CA_TRUST_NAME", "").strip()

    missing = []
    if not ca_host:
        missing.append("CA_TRUST_CERT_HOST")
    if not wrapper_host:
        missing.append("CA_TRUST_WRAPPER_HOST")
    if not trust_name:
        missing.append("CA_TRUST_NAME")

    if missing:
        warn(
            "CA injection disabled (missing env: "
            + ", ".join(missing)
            + "). Falling back to plain 'docker run'."
        )
        return None

    try:
        ca_host = must_exist(ca_host, "CA trust certificate")
        wrapper_host = must_exist(wrapper_host, "CA trust wrapper script")
    except SystemExit:
        warn(
            "CA injection disabled (CA files not found). Falling back to plain 'docker run'."
        )
        return None

    return ca_host, wrapper_host, trust_name


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


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

    ca_host, wrapper_host, trust_name = ca_env

    run_opts, image_and_args = split_docker_run_argv(argv)
    pull_policy = extract_pull_policy(run_opts)
    run_opts, user_entrypoint = extract_entrypoint(run_opts)

    image = image_and_args[0]
    user_args = image_and_args[1:]

    # Container-internal CA-injection paths bind-mounted from the host.
    # Not user-controllable; matched on the host side by sys-svc-compose-ca.
    ca_container = "/tmp/infinito/ca/root-ca.crt"  # noqa: S108
    wrapper_container = "/tmp/infinito/bin/with-ca-trust.sh"  # noqa: S108

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
            # Inject CA cert as a volume + env vars so Node.js (NODE_EXTRA_CA_CERTS),
            # curl (CURL_CA_BUNDLE), Python requests (REQUESTS_CA_BUNDLE), and other
            # tools can trust the internal CA even without a wrapper entrypoint.
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

    # List-form exec: no shell parses the argv. CMD comes from this
    # script's own argv (the wrapper), not from external user input.
    os.execvp(final_cmd[0], final_cmd)  # noqa: S606
    return 0


def passthrough_any(subcmd: str, argv: list[str], debug: bool) -> int:
    """
    Passthrough for ANY docker subcommand.
    This keeps the wrapper future-proof so new docker subcommands don't require
    code changes as long as callers use `container <subcmd> ...`.
    """
    return exec_docker(["docker", subcmd, *argv], debug=debug)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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

    # Default: passthrough ANY docker subcommand (info/version/system/network/volume/buildx/...)
    # Example: `container info` -> `docker info`
    #          `container system prune -af` -> `docker system prune -af`
    return passthrough_any(cmd, args, debug=debug)


if __name__ == "__main__":
    raise SystemExit(main())
