from __future__ import annotations

import argparse
from pathlib import Path

README = """\
# Auto Generated Technical Documentation: {name}

This folder contains an auto-generated technical role documentation for Infinito.Nexus.
"""


def create_readme_in_subdirs(generated_dir):
    """Give every directory below ``generated_dir`` a titled ``README.md``.

    Args:
        generated_dir: root of the generated documentation tree.
    """
    root = Path(generated_dir).resolve()
    if not root.exists():
        print(f"Error: Directory {root} does not exist.")
        return

    for subdir in [path for path in root.rglob("*") if path.is_dir()]:
        readme = subdir / "README.md"
        readme.write_text(README.format(name=subdir.name), encoding="utf-8")
        print(f"README.md created at {readme}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create README.md files in all subdirectories of the given directory."
    )
    parser.add_argument(
        "--generated-dir", required=True, help="Path to the generated directory."
    )
    args = parser.parse_args(argv)

    create_readme_in_subdirs(args.generated_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
