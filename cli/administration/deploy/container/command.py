from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
import uuid

from . import PROJECT_ROOT

INFINITO_SRC_DIR = os.environ["INFINITO_SRC_DIR"]


def ensure_image(image: str, rebuild: bool = False, no_cache: bool = False) -> None:
    """
    Handle Docker image creation rules:
      - rebuild=True  => always rebuild
      - rebuild=False & image missing => build once
      - no_cache=True => add '--no-cache' to docker build
    """
    build_args = ["docker", "build", "--pull"]
    if no_cache:
        build_args.append("--no-cache")
    build_args += ["-t", image, "."]

    if rebuild:
        print(f">>> Forcing rebuild of Docker image '{image}'...")
        subprocess.run(build_args, check=True)
        print(f">>> Docker image '{image}' rebuilt (forced).")
        return

    print(f">>> Checking if Docker image '{image}' exists...")
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        print(f">>> Docker image '{image}' already exists.")
        return

    print(f">>> Docker image '{image}' not found. Building it...")
    subprocess.run(build_args, check=True)
    print(f">>> Docker image '{image}' successfully built.")


def docker_exec(
    container: str,
    args: list[str],
    check: bool = True,
) -> subprocess.CompletedProcess:
    """
    Helper to run `docker exec` with optional working directory.
    """
    cmd = ["docker", "exec"]
    cmd.append(container)
    cmd += args

    print(">>> docker exec:")
    print(shlex.join(cmd))

    return subprocess.run(cmd, check=check)


def _docker_exec_capture(
    container: str, args: list[str]
) -> subprocess.CompletedProcess:
    cmd = ["docker", "exec", container, *args]

    print(">>> docker exec (capture):")
    print(shlex.join(cmd))

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def wait_for_docker_socket(container: str, timeout: int = 60) -> None:
    """
    Ensure Docker CLI exists in the container and the host docker socket is usable.
    """
    print(">>> Waiting for Docker to be usable inside CI container...")

    # 0) Verify docker CLI exists
    which = _docker_exec_capture(container, ["sh", "-lc", "command -v docker || true"])
    docker_path = (which.stdout or "").strip()
    if not docker_path:
        diag = _docker_exec_capture(
            container,
            [
                "sh",
                "-lc",
                "echo '[diag] PATH='\"$PATH\"; ls -la /usr/bin /bin 2>/dev/null | head -n 200 || true",
            ],
        )
        raise RuntimeError(
            "Docker CLI ('docker') not found inside CI container.\n"
            "Fix: install docker client in the image used for --image.\n\n"
            f"[diag stdout]\n{diag.stdout}\n"
            f"[diag stderr]\n{diag.stderr}\n"
        )

    # 2) Poll docker info
    last_out = ""
    last_err = ""
    for _ in range(timeout):
        result = _docker_exec_capture(
            container, ["sh", "-lc", "docker info >/dev/null 2>&1; echo $?"]
        )
        rc = (result.stdout or "").strip()
        if rc == "0":
            print(">>> Docker is usable inside container.")
            return

        # capture a bit more detail for later
        dv = _docker_exec_capture(
            container, ["sh", "-lc", "docker version 2>&1 || true"]
        )
        last_out = dv.stdout
        last_err = dv.stderr
        time.sleep(1)

    raise RuntimeError(
        "Docker did not become usable inside container in time.\n\n"
        "Most common causes:\n"
        "  - DOCKER_HOST is wrong\n\n"
        f"[last docker version stdout]\n{last_out}\n"
        f"[last docker version stderr]\n{last_err}\n"
    )


def start_ci_container(
    image: str,
    build: bool,
    rebuild: bool,
    no_cache: bool,
    name: str | None = None,
) -> str:
    """
    Start a CI container that uses the host Docker socket (no Docker-in-Docker).

    Returns the container name.
    """
    if build or rebuild:
        ensure_image(image, rebuild=rebuild, no_cache=no_cache)

    if not name:
        name = f"infinito-ci-{uuid.uuid4().hex[:8]}"

    print(f">>> Starting CI container '{name}' (host Docker socket mode)...")
    project_root = str(PROJECT_ROOT)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-v",
            f"{project_root}:{INFINITO_SRC_DIR}",
            image,
            "sh",
            "-lc",
            "tail -f /dev/null",
        ],
        check=True,
    )
    wait_for_docker_socket(name)
    print(f">>> CI container '{name}' started and Docker socket is usable.")
    return name


def run_in_container(
    image: str,
    build: bool,
    rebuild: bool,
    no_cache: bool,
    inventory_dir: str,
    inventory_args: list[str],
    deploy_args: list[str],
    name: str | None = None,
) -> None:
    """
    Full CI "run" mode:
      - start CI container (host docker socket mode)
      - run `infinito administration inventory provision` (with forwarded inventory_args)
      - ensure CI vault password file
      - run cli.administration.deploy.dedicated (with forwarded deploy_args)
      - always remove container at the end
    """
    container_name = None

    inv_root = str(inventory_dir).rstrip("/")
    inv_file = f"{inv_root}/devices.yml"
    pw_file = f"{inv_root}/.password"

    try:
        container_name = start_ci_container(
            image=image,
            build=build,
            rebuild=rebuild,
            no_cache=no_cache,
            name=name,
        )

        # 1) Create CI inventory
        print(
            ">>> Creating CI inventory inside container "
            "(infinito administration inventory provision)..."
        )
        inventory_cmd: list[str] = [
            "infinito",
            "administration",
            "inventory",
            "provision",
            inv_root,
            "--host",
            "localhost",
        ]
        inventory_cmd.extend(inventory_args)

        docker_exec(
            container_name,
            inventory_cmd,
            check=True,
        )

        # 1b) Mock backup authorized_keys file for user-backup
        print(">>> Mocking backup authorized_keys file inside CI inventory...")
        mock_key = os.environ.get(
            "AUTHORIZED_KEYS",
            "ssh-ed25519 AAAA_TEST_DUMMY_KEY github-ci-dummy@infinito",
        ).strip()

        mock_cmd = (
            "set -euo pipefail; "
            f"p={shlex.quote(inv_root)}/files/localhost/home/backup/.ssh/authorized_keys; "
            'mkdir -p "$(dirname "$p")"; '
            "printf '%s\n' " + shlex.quote(mock_key) + ' > "$p"; '
            'chmod 0644 "$p"; '
            'ls -la "$(dirname "$p")"; '
            'head -n 3 "$p" || true'
        )
        docker_exec(container_name, ["bash", "-lc", mock_cmd], check=True)

        # 2) Ensure vault password file exists
        print(">>> Ensuring CI vault password file exists...")
        ensure_pw_cmd = (
            f"mkdir -p {shlex.quote(inv_root)} && "
            f"[ -f {shlex.quote(pw_file)} ] || "
            f"printf '%s\n' 'ci-vault-password' > {shlex.quote(pw_file)}"
        )
        docker_exec(
            container_name,
            ["sh", "-c", ensure_pw_cmd],
            check=True,
        )

        # 3) Run dedicated deploy
        cmd = [
            "python3",
            "-m",
            "cli.administration.deploy.dedicated",
            inv_file,
            "-p",
            pw_file,
            "-vv",
            "--assert",
            "true",
            *deploy_args,
        ]
        print(">>> Deploy command inside container:")
        print(" ".join(cmd))
        result = docker_exec(container_name, cmd, check=False)

        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)

        print(">>> Deployment finished successfully inside CI container.")

    finally:
        if container_name:
            print(f">>> Cleaning up CI container '{container_name}'...")
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def stop_container(name: str) -> None:
    print(f">>> Stopping container '{name}'...")
    subprocess.run(["docker", "stop", name], check=True)
    print(f">>> Container '{name}' stopped.")


def remove_container(name: str) -> None:
    print(f">>> Removing container '{name}'...")
    subprocess.run(["docker", "rm", "-f", name], check=True)
    print(f">>> Container '{name}' removed.")


def exec_in_container(name: str, cmd_args: list[str]) -> int:
    if not cmd_args:
        print(
            "Error: exec mode requires a command to run inside the container.",
            file=sys.stderr,
        )
        return 1

    print(f">>> Executing command in container '{name}': {' '.join(cmd_args)}")
    result = docker_exec(name, cmd_args, check=False)
    return result.returncode


def split_inventory_and_deploy_args(rest: list[str]) -> tuple[list[str], list[str]]:
    """
    Split remaining arguments into:
      - inventory_args: passed to cli.administration.inventory.provision
      - deploy_args:    passed to cli.administration.deploy.dedicated

    Convention:
      - [inventory-args ...] -- [deploy-args ...]
      - If no '--' is present: inventory_args = [], deploy_args = all rest.
    """
    if not rest:
        return [], []

    if "--" in rest:
        idx = rest.index("--")
        inventory_args = rest[:idx]
        deploy_args = rest[idx + 1 :]
    else:
        inventory_args = []
        deploy_args = rest

    return inventory_args, deploy_args


def main() -> int:
    raw_argv = sys.argv[1:]

    if "--" in raw_argv:
        sep_index = raw_argv.index("--")
        container_argv = raw_argv[:sep_index]
        rest = raw_argv[sep_index + 1 :]
    else:
        container_argv = raw_argv
        rest = []

    parser = argparse.ArgumentParser(
        prog="infinito-deploy-container",
        description=(
            "Run Ansible deploy inside an infinito Docker image using the host Docker socket "
            "(no Docker-in-Docker) and auto-generated CI inventory.\n\n"
            "Usage (run mode):\n"
            "  python -m cli.administration.deploy.container run [container-opts] -- \\\n"
            "    [inventory-args ...] -- [deploy-args ...]\n\n"
            "Example:\n"
            "  python -m cli.administration.deploy.container run --build -- \\\n"
            "    --include svc-db-mariadb -- \\\n"
            "    --debug\n"
        ),
    )

    parser.add_argument(
        "mode",
        choices=["run", "start", "stop", "exec", "remove"],
        help="Container mode: run, start, stop, exec, remove.",
    )

    parser.add_argument("--image", default=os.environ.get("INFINITO_IMAGE"))
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--name")

    parser.add_argument(
        "--inventory-dir",
        default=os.environ.get("INFINITO_INVENTORY_DIR"),
        required=os.environ.get("INFINITO_INVENTORY_DIR") is None,
        help="Inventory directory to use (default: $INFINITO_INVENTORY_DIR).",
    )

    args = parser.parse_args(container_argv)
    mode = args.mode

    if mode == "run":
        inventory_args, deploy_args = split_inventory_and_deploy_args(rest)

        if not deploy_args:
            print(
                "Error: missing deploy arguments in run mode.\n"
                "Use:  container run [opts] -- [inventory args] -- [deploy args]",
                file=sys.stderr,
            )
            return 1

        try:
            run_in_container(
                image=args.image,
                build=args.build,
                rebuild=args.rebuild,
                no_cache=args.no_cache,
                inventory_dir=str(args.inventory_dir),
                inventory_args=inventory_args,
                deploy_args=deploy_args,
                name=args.name,
            )
        except subprocess.CalledProcessError as exc:
            print(
                f"[ERROR] Deploy failed with exit code {exc.returncode}",
                file=sys.stderr,
            )
            return exc.returncode
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

        return 0

    if mode == "start":
        try:
            name = start_ci_container(
                image=args.image,
                build=args.build,
                rebuild=args.rebuild,
                no_cache=args.no_cache,
                name=args.name,
            )
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

        print(f">>> Started CI container: {name}")
        return 0

    if not args.name:
        print(f"Error: '{mode}' requires --name", file=sys.stderr)
        return 1

    if mode == "stop":
        stop_container(args.name)
        return 0

    if mode == "remove":
        remove_container(args.name)
        return 0

    if mode == "exec":
        return exec_in_container(args.name, rest)

    print(f"Unknown mode: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
