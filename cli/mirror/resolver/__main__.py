from __future__ import annotations
import argparse
import json
from pathlib import Path
from utils.cache.yaml import dump_yaml_str

from utils.docker.image.discovery import iter_role_images
from cli.mirror.providers import GHCRProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    GHCRProvider.add_args(parser)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    provider = GHCRProvider.from_args(args)
    repo_root = Path(args.repo_root).resolve()

    applications: dict = {}
    images: dict = {}

    for img in iter_role_images(repo_root):
        if img.source_file == "defaults/main.yml":
            role_images = images.setdefault(img.role, {})
            role_images[str(img.service)] = {
                "image": provider.image_base(img),
                "version": img.version,
            }
            continue

        app = applications.setdefault(img.role, {})
        services = app.setdefault("services", {})
        services[str(img.service)] = {
            "image": provider.image_base(img),
            "version": img.version,
        }

    result = {"applications": applications, "images": images}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(dump_yaml_str(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
