from __future__ import annotations

import argparse
import os
from pathlib import Path

import pathspec

HEADER = """\
YAML Files
===========

This document lists all `.yaml` and `.yml` files found in the specified directory, excluding ignored files.

"""


def load_gitignore_patterns(source_dir):
    gitignore = Path(source_dir) / ".gitignore"
    lines = (
        gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    )
    return pathspec.GitIgnoreSpec.from_lines(lines)


def generate_yaml_index(source_dir, output_file):
    """Write an ``.rst`` page that literal-includes every non-ignored YAML file.

    Args:
        source_dir: tree to scan; its top-level ``.gitignore`` filters the result.
        output_file: page to write; includes are relative to its directory.
    """
    source = Path(source_dir)
    output = Path(output_file)
    spec = load_gitignore_patterns(source)
    yaml_files = sorted(
        (
            str(path)
            for path in source.rglob("*")
            if path.suffix in {".yml", ".yaml"}
            and path.is_file()
            and not spec.match_file(str(path.relative_to(source)))
        ),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    includes = "".join(
        f".. literalinclude:: {os.path.relpath(file, start=output.parent)}\n"
        "   :language: yaml\n"
        "   :linenos:\n\n"
        for file in yaml_files
    )
    output.write_text(HEADER + includes, encoding="utf-8")
    print(f"YAML index has been generated at {output_file}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate an index for YAML files while respecting .gitignore."
    )
    parser.add_argument(
        "--source-dir", required=True, help="Directory containing YAML files."
    )
    parser.add_argument(
        "--output-file", required=True, help="Path to the output .rst file."
    )
    args = parser.parse_args(argv)

    generate_yaml_index(args.source_dir, args.output_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
