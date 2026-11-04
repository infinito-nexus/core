"""Hash the build sections of a rendered compose file."""

from __future__ import annotations

import hashlib
import json

from utils.cache.yaml import load_yaml_str


def docker_build_digest(compose: str) -> str:
    """Return the sha256 of every service's ``build`` section.

    Args:
        compose: the rendered compose file.
    """
    builds = [
        service["build"]
        for service in load_yaml_str(compose)["services"].values()
        if isinstance(service, dict) and "build" in service
    ]
    return hashlib.sha256(json.dumps(builds, sort_keys=True).encode()).hexdigest()


class FilterModule:
    def filters(self):
        return {"docker_build_digest": docker_build_digest}
