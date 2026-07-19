from __future__ import annotations

from utils.roles.entity.name import get_entity_name


def get_docker_paths(application_id: str, path_docker_compose_instances: str) -> dict:
    """
    Build the compose dict based on path_docker_compose_instances and application_id.
    Uses get_entity_name to extract the entity name from application_id.
    """
    entity = get_entity_name(application_id)
    base = f"{path_docker_compose_instances}{entity}/"

    return {
        "directories": {
            "instance": base,
            "env": f"{base}.env/",
            "services": f"{base}services/",
            "volumes": f"{base}volumes/",
            "config": f"{base}config/",
        },
        "files": {
            "env": f"{base}.env/env",
            "compose": f"{base}compose.yml",
            "compose_override": f"{base}compose.override.yml",
            "compose_ca_override": f"{base}compose.ca.override.yml",
            "dockerfile": f"{base}Dockerfile",
        },
    }
