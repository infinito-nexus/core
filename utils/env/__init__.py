"""Project .env generator -- internal helpers.

The CLI entry point lives at ``cli.meta.env`` (`python -m cli.meta.env`
or `make dotenv`). It reads the committed ``default.env``, layers
runtime context on top (distro, GHA/Act flags, df/meminfo-derived
sizes, sha256 secrets, repo owner/name resolution), and writes the
resulting ``.env`` to the repo root.
"""
