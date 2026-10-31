from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath


def generate_ansible_roles_index(roles_dir, output_file, caption):
    """Write a toctree listing every ``.rst`` file in ``roles_dir``.

    Args:
        roles_dir: directory holding the generated role pages.
        output_file: index file to write; entries are relative to its directory.
        caption: page title and toctree caption.
    """
    roles = Path(roles_dir).resolve()
    output = Path(output_file).resolve()
    if not roles.exists():
        print(f"Error: Directory {roles} does not exist.")
        return
    output.parent.mkdir(parents=True, exist_ok=True)

    entries = [
        f"   {PurePosixPath(os.path.relpath(roles / name, start=output.parent)).with_suffix('')}"
        for name in sorted(
            path.name for path in roles.iterdir() if path.suffix == ".rst"
        )
    ]
    lines = [
        caption,
        "=" * len(caption),
        "",
        ".. toctree::",
        "   :maxdepth: 1",
        f"   :caption: {caption}",
        "",
        *entries,
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Index generated at {output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate an index for documentation.")
    parser.add_argument(
        "--roles-dir", required=True, help="Directory containing .rst files."
    )
    parser.add_argument(
        "--output-file", required=True, help="Path to the output index.rst file."
    )
    parser.add_argument("--caption", required=True, help="The index title")
    args = parser.parse_args(argv)

    generate_ansible_roles_index(args.roles_dir, args.output_file, args.caption)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
