#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml


def run_cmd(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> tuple[int, str, str]:
    """Run a command with stdout and stderr captured SEPARATELY.

    Compose prints warnings ('variable is not set', ...) on stderr; merging
    them into stdout poisons every parser downstream (yaml config, the
    `config --images` list, the `pull --help` probe).
    """
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def _print_streams(out: str, err: str, *, to_stderr: bool) -> None:
    if out.strip():
        print(
            out,
            file=sys.stderr if to_stderr else sys.stdout,
            end="" if out.endswith("\n") else "\n",
        )
    if err.strip():
        print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")


def run_or_fail(cmd: list[str], *, cwd: Path, env: dict[str, str], label: str) -> None:
    print(f">>> {' '.join(cmd)}", file=sys.stderr)
    rc, out, err = run_cmd(cmd, cwd=cwd, env=env)
    _print_streams(out, err, to_stderr=rc != 0)
    if rc != 0:
        raise RuntimeError(f"{label} failed (rc={rc})")


def base_compose_cmd(*, project: str, cwd: Path) -> list[str]:
    return ["/usr/bin/compose", "--chdir", str(cwd), "--project", project, "--"]


def has_buildable_services(
    *, base_cmd: list[str], cwd: Path, env: dict[str, str]
) -> bool:
    rc, out, err = run_cmd([*base_cmd, "config"], cwd=cwd, env=env)

    if rc != 0:
        _print_streams(out, err, to_stderr=True)
        raise RuntimeError(
            "docker compose config failed; cannot detect buildable services"
        )

    return any(
        line.lstrip() != line and line.strip().startswith("build:")
        for line in out.splitlines()
    )


def pull_service_targets(
    *, base_cmd: list[str], cwd: Path, env: dict[str, str]
) -> list[str] | None:
    """Service names safe to pass to `docker compose pull`.

    Excludes services that declare `build:` and services that merely REUSE an
    image some other service builds (registry-less local tag, e.g. a cron
    service on the app's custom image); `--ignore-buildable` only covers the
    former, so compose otherwise aborts the whole pull with 'pull access
    denied' on the reused tag.

    Returns:
        None when nothing needs excluding (caller pulls everything) or when
        the config cannot be parsed (fall back to unchanged behavior);
        otherwise the possibly-empty list of pullable service names.
    """
    rc, out, _err = run_cmd([*base_cmd, "config"], cwd=cwd, env=env)
    if rc != 0:
        return None
    try:
        doc = yaml.safe_load(out)  # nocheck: direct-yaml
    except yaml.YAMLError:
        return None
    services = (doc or {}).get("services")
    if not isinstance(services, dict):
        return None

    locally_built = {
        svc["image"]
        for svc in services.values()
        if isinstance(svc, dict)
        and "build" in svc
        and isinstance(svc.get("image"), str)
    }
    if not locally_built:
        return None

    targets: list[str] = []
    excluded = False
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if "build" in svc or (isinstance(image, str) and image in locally_built):
            excluded = True
            continue
        targets.append(name)

    return sorted(targets) if excluded else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="docker compose pull/build (retry handled by Ansible)"
    )
    ap.add_argument("--chdir", required=True, help="Compose instance directory")
    ap.add_argument("--project", required=True, help="Compose project name (-p)")
    ap.add_argument(
        "--compose-files",
        required=True,
        help='Compose files args string like: "-f compose.yml -f compose.override.yml"',
    )
    ap.add_argument("--env-file", default="", help="Optional env file path")

    ap.add_argument("--lock-dir", required=True, help="Directory for lock files")
    ap.add_argument(
        "--lock-key", required=True, help="Unique lock key (e.g. sha1 of instance dir)"
    )
    ap.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip docker compose build --pull",
    )
    ap.add_argument(
        "--ignore-buildable",
        action="store_true",
        help="Use --ignore-buildable for pull when supported",
    )

    args = ap.parse_args()

    cwd = Path(args.chdir)
    lock_dir = Path(args.lock_dir)
    lock_file = lock_dir / f"{args.lock_key}.lock"

    if lock_file.exists():
        return 0

    lock_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)

    base_cmd = base_compose_cmd(project=args.project, cwd=cwd)

    if not args.skip_build and has_buildable_services(
        base_cmd=base_cmd, cwd=cwd, env=env
    ):
        build_pull_cmd = [*base_cmd, "build", "--pull"]
        print(f">>> {' '.join(build_pull_cmd)}", file=sys.stderr)
        rc, out, err = run_cmd(build_pull_cmd, cwd=cwd, env=env)
        _print_streams(out, err, to_stderr=True)
        if rc != 0:
            run_or_fail(
                [*base_cmd, "build"],
                cwd=cwd,
                env=env,
                label="docker compose build",
            )

    pull_cmd = [*base_cmd, "pull"]

    if args.ignore_buildable:
        rc, help_out, _err = run_cmd([*base_cmd, "pull", "--help"], cwd=cwd, env=env)
        if rc == 0 and "--ignore-buildable" in help_out:
            pull_cmd.append("--ignore-buildable")

    targets = pull_service_targets(base_cmd=base_cmd, cwd=cwd, env=env)
    if targets is not None:
        if not targets:
            print(
                ">>> pull skipped: every service uses a locally-built image",
                file=sys.stderr,
            )
            lock_file.write_text("ok\n", encoding="utf-8")
            print("pulled")
            return 0
        pull_cmd.extend(targets)

    print(f">>> {' '.join(pull_cmd)}", file=sys.stderr)
    rc, out, err = run_cmd(pull_cmd, cwd=cwd, env=env)
    _print_streams(out, err, to_stderr=True)

    if rc != 0:
        rc_images, images_out, _err = run_cmd(
            [*base_cmd, "config", "--images"], cwd=cwd, env=env
        )
        if rc_images != 0:
            raise RuntimeError(f"docker compose pull failed (rc={rc})")
        required = [line.strip() for line in images_out.splitlines() if line.strip()]
        missing = []
        for image in required:
            rc_inspect, _out, _err = run_cmd(
                ["docker", "image", "inspect", image], cwd=cwd, env=env
            )
            if rc_inspect != 0:
                missing.append(image)
        if missing:
            raise RuntimeError(
                f"docker compose pull failed (rc={rc}); images missing locally: {missing}"
            )
        print(
            f"docker compose pull failed (rc={rc}) but all images present locally",
            file=sys.stderr,
        )

    lock_file.write_text("ok\n", encoding="utf-8")
    print("pulled")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(rc)
