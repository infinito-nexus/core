from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

COMPOSE_TEMPLATE = "compose.yml.j2"


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
