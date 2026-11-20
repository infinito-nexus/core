from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

__all__ = [
    "COMPOSE_TEMPLATE",
    "PROJECT_ROOT",
    "is_env_template",
    "is_main_compose_template",
    "is_service_env_template",
]

COMPOSE_TEMPLATE = "compose.yml.j2"


def _is_role_template(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith(".j2")
    )


def is_env_template(rel_path: str) -> bool:
    """Whether *rel_path* is a role's env-file template (``*env.j2``, ``*.env*.j2``).

    Args:
        rel_path: repository-relative path, as ``git ls-files`` reports it.
    """
    base = Path(rel_path).name
    return _is_role_template(rel_path) and (".env" in base or base.endswith("env.j2"))


def is_service_env_template(rel_path: str) -> bool:
    """Whether *rel_path* is a per-service env template (``templates/env/*.j2``).

    Args:
        rel_path: repository-relative path, as ``git ls-files`` reports it.
    """
    return _is_role_template(rel_path) and "/templates/env/" in rel_path


def is_main_compose_template(rel_path: str) -> bool:
    """Whether *rel_path* is a role's compose template.

    Args:
        rel_path: repository-relative path, as ``git ls-files`` reports it.
    """
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith(COMPOSE_TEMPLATE)
    )
