#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


def run(cmd: list[str]) -> int:
    print(f">>> {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=False).returncode


def retag_push_and_rewrite(*, compose_file: Path, prefix: str) -> int:
    with compose_file.open() as f:
        doc = yaml.safe_load(f)  # nocheck: direct-yaml

    services = (doc or {}).get("services") or {}
    if not isinstance(services, dict):
        return 0

    targets: list[str] = []
    changed = False

    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        if "build" not in svc:
            continue
        image = svc.get("image")
        if not isinstance(image, str) or not image:
            continue
        if image.startswith(prefix):
            targets.append(image)
            continue
        new_image = f"{prefix}{image}"
        rc = run(["docker", "tag", image, new_image])
        if rc != 0:
            raise RuntimeError(f"docker tag {image} {new_image} failed (rc={rc})")
        svc["image"] = new_image
        targets.append(new_image)
        changed = True

    if changed:
        with compose_file.open("w") as f:
            yaml.safe_dump(
                doc, f, sort_keys=False, default_flow_style=False
            )  # nocheck: direct-yaml

    for image in targets:
        rc = run(["docker", "push", image])
        if rc != 0:
            raise RuntimeError(f"docker push {image} failed (rc={rc})")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Retag locally-built compose images with the swarm registry "
            "prefix, push them, and rewrite compose.yml so subsequent "
            "`docker stack deploy --resolve-image never` references the "
            "registry-qualified names."
        )
    )
    ap.add_argument("--chdir", required=True, help="Compose instance directory")
    ap.add_argument(
        "--registry-prefix",
        required=True,
        help='Registry host with trailing slash, e.g. "host:5000/"',
    )
    args = ap.parse_args()

    prefix = args.registry_prefix
    if not prefix:
        return 0

    compose_file = Path(args.chdir) / "compose.yml"
    if not compose_file.is_file():
        raise RuntimeError(f"compose.yml not found at {compose_file}")

    return retag_push_and_rewrite(compose_file=compose_file, prefix=prefix)


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(rc)
