from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.administration.roles.marker import write_marker
from cli.contributing.role.skeleton.manifest import validate
from cli.contributing.role.skeleton.render import RenderError, render
from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any

SAMPLES_DIR = Path(__file__).resolve().parent
PROVENANCE = "role skeleton sample"


def place(manifest_file: Path, roles_dir: Path) -> Path:
    """Render one sample manifest into ``roles_dir`` and mark it as pulled.

    Args:
        manifest_file: a sample manifest beside this module.
        roles_dir: the role search directory of the core checkout.

    Returns:
        The rendered role directory.

    Raises:
        RenderError: the sample does not validate or render.
    """
    manifest, errors = validate(load_yaml_any(str(manifest_file)))
    if manifest is None:
        raise RenderError([f"{manifest_file.name}: {error}" for error in errors])
    role_dir = render(manifest, roles_dir, force=False)
    write_marker(role_dir, role_dir.name, f"{PROVENANCE} {manifest_file.name}", "")
    return role_dir


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=(
            "Render every sample manifest of the role skeleton into roles/ with the "
            "custom-role pull marker, so make roles-clean removes them again."
        )
    ).parse_args(argv)
    try:
        placed = [place(path, ROLES_DIR) for path in sorted(SAMPLES_DIR.glob("*.yml"))]
    except RenderError as exc:
        print("\n".join(exc.errors), file=sys.stderr)
        return 2
    for role_dir in placed:
        print(role_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
