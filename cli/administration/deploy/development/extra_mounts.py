"""Mount extra host directories read-only into the infinito container."""

from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import dump_yaml

OVERRIDE = "build/compose/extra-mounts.override.yml"


def parse_mounts(raw: str) -> list[Path]:
    """Return the directories of a comma-separated ``INFINITO_EXTRA_MOUNTS`` value.

    Args:
        raw: comma-separated absolute host directories.

    Raises:
        SystemExit: an entry is not an existing absolute directory.
    """
    directories: list[Path] = []
    for item in filter(None, (part.strip() for part in raw.split(","))):
        directory = Path(item)
        if not directory.is_absolute() or not directory.is_dir():
            raise SystemExit(
                f"INFINITO_EXTRA_MOUNTS: {item} is not an existing absolute directory"
            )
        directories.append(directory)
    return directories


def write_mounts_override(repo_root: Path, directories: list[Path]) -> str:
    """Write the compose override that mounts ``directories`` into the container.

    Args:
        repo_root: repository root the compose files are relative to.
        directories: host directories, each mounted read-only at its own path.

    Returns:
        The override path relative to ``repo_root``.
    """
    volumes = [
        {"type": "bind", "source": str(path), "target": str(path), "read_only": True}
        for path in directories
    ]
    dump_yaml(repo_root / OVERRIDE, {"services": {"infinito": {"volumes": volumes}}})
    return OVERRIDE
