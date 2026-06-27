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


def manifest_exists(image: str) -> bool:
    rc = subprocess.run(
        ["docker", "manifest", "inspect", image],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    return rc == 0


def sync(*, compose_file: Path, prefix: str) -> int:
    with compose_file.open() as f:
        doc = yaml.safe_load(f)  # nocheck: direct-yaml

    services = (doc or {}).get("services") or {}
    if not isinstance(services, dict):
        return 0

    targets: list[str] = []
    changed = False

    # Refs some service builds locally; a sibling service may reference the same
    # (already-prefixed) image without its own build:, and must not try to pull
    # that local-only ref from the registry.
    locally_built = {
        svc["image"].removeprefix(prefix)
        for svc in services.values()
        if isinstance(svc, dict)
        and "build" in svc
        and isinstance(svc.get("image"), str)
    }

    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if not isinstance(image, str) or not image:
            continue

        if image.startswith(prefix):
            targets.append(image)
            upstream = image[len(prefix) :]
            if "build" in svc or manifest_exists(image) or upstream in locally_built:
                continue
            rc = run(["docker", "pull", upstream])
            if rc != 0:
                raise RuntimeError(f"docker pull {upstream} failed (rc={rc})")
            rc = run(["docker", "tag", upstream, image])
            if rc != 0:
                raise RuntimeError(f"docker tag {upstream} {image} failed (rc={rc})")
            continue

        if "build" in svc:
            new_image = f"{prefix}{image}"
            rc = run(["docker", "tag", image, new_image])
            if rc != 0:
                raise RuntimeError(f"docker tag {image} {new_image} failed (rc={rc})")
            svc["image"] = new_image
            targets.append(new_image)
            changed = True
            continue

        new_image = f"{prefix}{image}"
        rc = run(["docker", "pull", image])
        if rc != 0:
            raise RuntimeError(f"docker pull {image} failed (rc={rc})")
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
        if manifest_exists(image):
            print(f">>> skip push (already in registry): {image}", file=sys.stderr)
            continue
        rc = run(["docker", "push", image])
        if rc != 0:
            raise RuntimeError(f"docker push {image} failed (rc={rc})")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Cache upstream images and retag locally-built compose images "
            "with the swarm registry prefix, push them, and rewrite "
            "compose.yml so subsequent `docker stack deploy "
            "--resolve-image never` references the registry-qualified names."
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

    return sync(compose_file=compose_file, prefix=prefix)


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(rc)
