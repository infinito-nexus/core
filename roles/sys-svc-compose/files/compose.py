#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

# `utils.cache.yaml` is unavailable here: this file is copy-deployed.
import yaml


def detect_env_file(project_dir: Path) -> Path | None:
    """Detect compose env file: <dir>/.env or legacy <dir>/.env/env."""
    c1 = project_dir / ".env"
    if c1.is_file():
        return c1
    c2 = project_dir / ".env" / "env"
    if c2.is_file():
        return c2
    return None


def _yaml_services(path: Path) -> set[str]:
    """Return the top-level `services:` keys declared in a compose YAML file."""
    try:
        with path.open() as f:
            doc = yaml.safe_load(f)  # nocheck: direct-yaml
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(doc, dict):
        return set()
    services = doc.get("services")
    if not isinstance(services, dict):
        return set()
    return set(services.keys())


def ca_override_is_stale(base_compose: Path, ca_override: Path) -> bool:
    base_services = _yaml_services(base_compose)
    if not base_services:
        return False
    override_services = _yaml_services(ca_override)
    if not override_services:
        return False
    return bool(override_services - base_services)


def detect_compose_files(project_dir: Path) -> list[Path]:
    """Detect Compose file stack: compose.yml + optional overrides."""
    base = project_dir / "compose.yml"
    if not base.is_file():
        raise FileNotFoundError(f"Missing compose.yml in: {project_dir}")

    files = [base]

    override = project_dir / "compose.override.yml"
    if override.is_file():
        files.append(override)

    ca_override = project_dir / "compose.ca.override.yml"
    if ca_override.is_file():
        if ca_override_is_stale(base, ca_override):
            print(
                "[compose] skipping stale compose.ca.override.yml "
                "(declares services not in compose.yml; awaiting regeneration)",
                file=sys.stderr,
            )
        else:
            files.append(ca_override)

    cache_override = generate_cache_override(project_dir, base)
    if cache_override is not None:
        files.append(cache_override)

    return files


# Mirrors that speak HTTP by default in their distro's package-manager
# config. Alpine 3.18+ defaults to HTTPS and would fail TLS verification
# inside builds that lack the frontend CA, so it is excluded.
_CACHE_HTTP_HOSTNAMES = (
    "deb.debian.org",
    "archive.ubuntu.com",
    "security.ubuntu.com",
)


def generate_cache_override(project_dir: Path, base_compose: Path) -> Path | None:
    """Emit transient build.extra_hosts override when cache profile active."""
    cache_ip = (os.environ.get("INFINITO_CACHE_PACKAGE_FRONTEND_IP") or "").strip()
    if not cache_ip or not base_compose.is_file():
        return None

    with Path(base_compose).open() as f:
        doc = yaml.safe_load(f)  # nocheck: direct-yaml

    services = (doc or {}).get("services") or {}
    services_with_build = sorted(
        name
        for name, svc in services.items()
        if isinstance(svc, dict) and svc.get("build")
    )
    if not services_with_build:
        return None

    extra_hosts = [f"{host}:{cache_ip}" for host in _CACHE_HTTP_HOSTNAMES]
    override_doc = {
        "services": {
            name: {"build": {"extra_hosts": list(extra_hosts)}}
            for name in services_with_build
        }
    }

    out = project_dir / "compose.cache.override.yml"
    with Path(out).open("w") as f:
        yaml.safe_dump(override_doc, f, sort_keys=True)  # nocheck: direct-yaml
    return out


def resolve_files(project_dir: Path, files: list[str]) -> list[Path]:
    """Resolve -f/--file paths against project_dir."""
    out: list[Path] = []
    for f in files:
        p = Path(f)
        if not p.is_absolute():
            p = project_dir / p
        out.append(p.resolve())
    return out


# Subcommands that parse service `env_file:` values. Compose's env parser
# rejects $-bearing secrets, but the swarm dotenv keeps $ literal because
# `docker stack deploy` does NOT parse env_file. build/config need no runtime
# env, so they get env_file-stripped copies (and no --env-file) instead.
_ENV_PARSING_SUBCOMMANDS = {"build", "config"}


def _subcommand(passthrough: list[str]) -> str:
    # The docker compose subcommand is the first passthrough token (main()
    # strips a leading `--`; the wrapper's own flags are parsed off earlier).
    return passthrough[0] if passthrough else ""


def strip_env_files(project_dir: Path, files: list[Path]) -> list[Path]:
    """Return env_file-free copies of the compose files for build/config."""
    out: list[Path] = []
    for f in files:
        with Path(f).open() as fh:
            doc = yaml.safe_load(fh)  # nocheck: direct-yaml
        for svc in ((doc or {}).get("services") or {}).values():
            if isinstance(svc, dict):
                svc.pop("env_file", None)
        dst = project_dir / f"{Path(f).stem}.noenv.yml"
        with Path(dst).open("w") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False)  # nocheck: direct-yaml
        out.append(dst)
    return out


def build_cmd(
    project: str,
    project_dir: Path,
    passthrough: list[str],
    extra_files: list[str] | None = None,
) -> list[str]:
    """Auto-detected compose files, with extra_files appended last."""
    files = detect_compose_files(project_dir)

    if extra_files:
        files.extend(resolve_files(project_dir, extra_files))

    cmd: list[str] = ["docker", "compose", "-p", project]

    if _subcommand(passthrough) in _ENV_PARSING_SUBCOMMANDS:
        for f in strip_env_files(project_dir, files):
            cmd += ["-f", str(f)]
    else:
        for f in files:
            cmd += ["-f", str(f)]
        env_file = detect_env_file(project_dir)
        if env_file:
            cmd += ["--env-file", str(env_file)]

    cmd += passthrough
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Infinito.Nexus docker compose wrapper (auto env + overrides)"
    )
    ap.add_argument(
        "--chdir",
        help="Compose project directory (default: current working directory)",
    )
    ap.add_argument(
        "-f",
        "--file",
        action="append",
        dest="files",
        help="Additional compose file(s) appended after auto-detected files",
    )
    ap.add_argument(
        "--project",
        help="Compose project name (-p) (default: basename of chdir)",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Print resolved command to stderr before execution",
    )
    ap.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to `docker compose` (e.g. up -d, restart, down -v, ps -a)",
    )
    args = ap.parse_args()

    project_dir = Path(args.chdir) if args.chdir else Path.cwd()
    project_dir = project_dir.resolve()

    if not project_dir.is_dir():
        print(
            f"[compose] --chdir is not a directory: {project_dir}",
            file=sys.stderr,
        )
        return 2

    project = args.project or project_dir.name

    passthrough = args.args
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    if not passthrough:
        print("[compose] No docker compose args provided.", file=sys.stderr)
        return 2

    try:
        cmd = build_cmd(
            project=project,
            project_dir=project_dir,
            passthrough=passthrough,
            extra_files=args.files,
        )
    except Exception as exc:
        print(f"[compose] {exc}", file=sys.stderr)
        return 2

    if args.debug:
        print(">>> " + " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)

    # execvp preserves signal handling under systemd. The argv list is
    # built from this script's own argv plus `--env-file` / `--profile`
    # additions; no shell parses it.
    os.execvp(cmd[0], cmd)  # noqa: S606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
