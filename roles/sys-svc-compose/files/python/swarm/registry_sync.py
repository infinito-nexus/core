#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

PULL_TIMEOUT = 1800
WORKERS = 4


def run(cmd: list[str], timeout: int = 600) -> int:
    print(f">>> {' '.join(cmd)}", file=sys.stderr)
    try:
        return subprocess.run(cmd, check=False, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f">>> TIMEOUT after {timeout}s: {' '.join(cmd)}", file=sys.stderr)
        return 124


def manifest_exists(image: str) -> bool:
    rc = subprocess.run(
        ["docker", "manifest", "inspect", "--insecure", image],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    return rc == 0


def pull_and_tag(upstream: str, image: str) -> None:
    rc = run(["docker", "pull", upstream], timeout=PULL_TIMEOUT)
    if rc != 0:
        raise RuntimeError(f"docker pull {upstream} failed (rc={rc})")
    rc = run(["docker", "tag", upstream, image])
    if rc != 0:
        raise RuntimeError(f"docker tag {upstream} {image} failed (rc={rc})")


def push(image: str, image_id: str, pushed_id: str) -> None:
    if manifest_exists(image) and pushed_id == image_id:
        print(f">>> skip push (already in registry): {image}", file=sys.stderr)
        return
    rc = run(["docker", "push", image])
    if rc != 0:
        raise RuntimeError(f"docker push {image} failed (rc={rc})")


def in_parallel(job: Callable[..., None], arguments: list[tuple]) -> None:
    """Run *job* for every argument tuple, ``WORKERS`` at a time.

    Args:
        job: one pull or push; raises on failure.
        arguments: positional arguments of each call.
    """
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for future in [pool.submit(job, *args) for args in arguments]:
            future.result()


def local_image_id(image: str) -> str:
    proc = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


IMAGE_ID_LABEL = "infinito.image-id"


def _label_image_id(svc: dict, image_id: str) -> bool:
    """Pin the local image ID as a container label; True when it changed.

    Args:
        svc: one compose service, mutated in place.
        image_id: ID of the locally built image the service runs.
    """
    labels = svc.get("labels")
    if isinstance(labels, list):
        entry = f"{IMAGE_ID_LABEL}={image_id}"
        if entry in labels:
            return False
        svc["labels"] = [
            *(
                item
                for item in labels
                if not str(item).startswith(f"{IMAGE_ID_LABEL}=")
            ),
            entry,
        ]
        return True
    current = labels if isinstance(labels, dict) else {}
    if current.get(IMAGE_ID_LABEL) == image_id:
        return False
    svc["labels"] = {**current, IMAGE_ID_LABEL: image_id}
    return True


def sync(*, compose_file: Path, prefix: str) -> int:
    with compose_file.open() as f:
        doc = yaml.safe_load(f)  # nocheck: direct-yaml

    services = (doc or {}).get("services") or {}
    if not isinstance(services, dict):
        return 0

    targets: list[str] = []
    pulled: list[tuple[str, str]] = []
    changed = False

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
            pulled.append((upstream, image))
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
        svc["image"] = new_image
        targets.append(new_image)
        changed = True
        if manifest_exists(new_image):
            continue
        pulled.append((image, new_image))

    in_parallel(pull_and_tag, list(dict.fromkeys(pulled)))

    for svc in services.values():
        if not isinstance(svc, dict) or not isinstance(svc.get("image"), str):
            continue
        if svc["image"].removeprefix(prefix) not in locally_built:
            continue
        image_id = local_image_id(svc["image"])
        if image_id and _label_image_id(svc, image_id):
            changed = True

    if changed:
        with compose_file.open("w") as f:
            yaml.safe_dump(
                doc, f, sort_keys=False, default_flow_style=False
            )  # nocheck: direct-yaml

    pushed_file = compose_file.parent / ".pushed-images.json"
    pushed = json.loads(pushed_file.read_text()) if pushed_file.is_file() else {}
    pending = [
        (
            image,
            local_image_id(image)
            if image.removeprefix(prefix) in locally_built
            else "",
            pushed.get(image, ""),
        )
        for image in dict.fromkeys(targets)
    ]
    in_parallel(push, pending)
    for image, image_id, _ in pending:
        if image_id:
            pushed[image] = image_id
    pushed_file.write_text(json.dumps(pushed, indent=2, sort_keys=True))

    for upstream, image in dict.fromkeys(pulled):
        run(["docker", "rmi", image, upstream])

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
