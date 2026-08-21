#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import yaml

HASH_SUFFIX_RE = re.compile(r"^(?P<prefix>.+)_[0-9a-f]{8}$")


def content_hash(path: Path, length: int = 8) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]
    except UnicodeDecodeError:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:length]


def rotate(compose_file: Path) -> int:
    with compose_file.open() as f:
        doc = yaml.safe_load(f)  # nocheck: direct-yaml

    if not isinstance(doc, dict):
        return 0

    changed = False
    for section in ("secrets", "configs"):
        entries = doc.get(section)
        if not isinstance(entries, dict):
            continue
        for key, spec in entries.items():
            if not isinstance(spec, dict):
                continue
            source = spec.get("file")
            name = spec.get("name")
            if not isinstance(source, str) or not isinstance(name, str):
                continue
            m = HASH_SUFFIX_RE.match(name)
            if not m:
                continue
            path = Path(source)
            if not path.is_file():
                print(
                    f">>> skip {section[:-1]} '{key}': source missing ({source})",
                    file=sys.stderr,
                )
                continue
            real = f"{m.group('prefix')}_{content_hash(path)}"
            if real != name:
                print(
                    f">>> rotate {section[:-1]} '{key}': {name} -> {real}",
                    file=sys.stderr,
                )
                spec["name"] = real
                changed = True

    if changed:
        with compose_file.open("w") as f:
            yaml.safe_dump(
                doc, f, sort_keys=False, default_flow_style=False
            )  # nocheck: direct-yaml
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Recompute the content-hash suffix of file-backed swarm "
            "secret/config names in compose.yml from the files on THIS host; "
            "the controller-side hash falls back to the path string, so a "
            "rotated source collides with the immutable docker secret."
        )
    )
    ap.add_argument("--chdir", required=True, help="Compose instance directory")
    args = ap.parse_args()

    compose_file = Path(args.chdir) / "compose.yml"
    if not compose_file.is_file():
        raise RuntimeError(f"compose.yml not found at {compose_file}")
    return rotate(compose_file)


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(rc)
