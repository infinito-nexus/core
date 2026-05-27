"""`infinito meta env` subcommand -- generate the project's `.env`.

Reads `default.env` plus the current runtime context (distro, GHA/Act
flags, df/meminfo-derived sizes, sha256 secrets, ...) and writes the
resulting `.env` at the repo root. Implementation lives in
`utils.env`; this package is the CLI entry point.
"""

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
