"""Extract the messages of the documentation into the ``docs`` gettext template.

Usage:
  python -m infinito_docs.i18n --src <checkout> --output <docs.pot> --jobs <n>
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from infinito_docs.commands import generate_commands

PACKAGE_DIR = Path(__file__).resolve().parent
DOMAIN = "docs"


def extract(src: Path, output: Path, jobs: int) -> None:
    """Generate the sources of ``src`` and write their messages to ``output``.

    Args:
        src: scratch checkout; the generators write into it.
        output: path of the resulting ``.pot`` file.
        jobs: parallel Sphinx processes.
    """
    tooling = str(PACKAGE_DIR.parent)
    inherited = [
        path for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path
    ]
    with tempfile.TemporaryDirectory(prefix="infinito-docs-i18n-") as scratch:
        conf = Path(scratch) / "conf"
        out = Path(scratch) / "out"
        shutil.copytree(PACKAGE_DIR, conf)
        if (src / "assets" / "img").is_dir():
            shutil.copytree(
                src / "assets" / "img", conf / "assets" / "img", dirs_exist_ok=True
            )
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([tooling, *inherited])}
        for command in generate_commands(src):
            subprocess.run(command, check=True, env=env, cwd=scratch)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "sphinx",
                "-b",
                "gettext",
                "-q",
                "-W",
                str(src),
                str(out),
                "-c",
                str(conf),
                "-j",
                str(jobs),
            ],
            check=True,
            env={**env, "PYTHONPATH": os.pathsep.join([str(src), tooling, *inherited])},
            cwd=scratch,
        )
        shutil.copyfile(out / f"{DOMAIN}.pot", output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=int)
    args = parser.parse_args()
    extract(args.src.resolve(), args.output.resolve(), args.jobs)


if __name__ == "__main__":
    main()
