from __future__ import annotations

import argparse
import json
from pathlib import Path

from cli.contributing.mirror.providers import GHCRProvider
from utils.cache.yaml import dump_yaml_str
from utils.docker.image.discovery import iter_role_images


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit the mirrors.yml mapping that redirects every role-declared "
            "image (applications.*.services.*) to its GHCR mirror URI."
        ),
    )
    parser.add_argument("--repo-root", default=".")
    GHCRProvider.add_args(parser)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    provider = GHCRProvider.from_args(args)
    repo_root = Path(args.repo_root).resolve()

    applications: dict = {}

    for img in iter_role_images(repo_root):
        app = applications.setdefault(img.role, {})
        services = app.setdefault("services", {})
        services[str(img.service)] = {
            "image": provider.image_base(img),
            "version": img.version,
        }

    result = {"applications": applications}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(dump_yaml_str(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
