"""Node Tor v3 onion identity for the harness.

:func:`init_env` pre-mints the node's onion, writes ``INFINITO_DOMAIN`` (which the
dev inventory maps to ``DOMAIN_PRIMARY``) into the env file, and stores the
authoritative hidden-service key files at the repo root. The ``svc-net-tor`` role
copies those keys into the running daemon so it serves exactly that address, and
coredns/dns-search resolve the same onion. The onion is a deploy-time input;
there is no in-deploy minting (a random mint would not match the pre-set domain).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from utils.tor_onion import mint

HS_FILE_MODES = {
    "hostname": 0o600,
    "hs_ed25519_public_key": 0o600,
    "hs_ed25519_secret_key": 0o600,
}

IDENTITY_DIRNAME = ".onion-identity"


def identity_hs_dir(base_dir: str | Path) -> Path:
    """Authoritative hidden-service key files, next to the env file (repo root).

    Single source of truth for the node's onion identity: the ``svc-net-tor`` role
    copies them into the running daemon. Lives outside anything the deploy
    regenerates (unlike ``.env``) and is mounted into the DiD at
    ``{playbook_dir}/.onion-identity/hs``.
    """
    return Path(base_dir) / IDENTITY_DIRNAME / "hs"


def _write_files(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = directory / name
        fd = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, HS_FILE_MODES[name]
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)


def _upsert_env(env_path: Path, updates: dict[str, str]) -> None:
    """Set/replace ``KEY=VALUE`` lines in an env file, preserving everything else."""
    raw = ""
    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8")  # nocheck: cache-read
    lines = raw.splitlines(keepends=True)
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            out.append(f"{key}={remaining.pop(key)}\n")
        else:
            out.append(line)
    if out and not out[-1].endswith("\n"):
        out.append("\n")
    for key, value in remaining.items():
        out.append(f"{key}={value}\n")
    env_path.write_text("".join(out), encoding="utf-8")


def init_env(env_file: str | Path) -> str:
    """Ensure the node onion identity and (re)write ``INFINITO_DOMAIN`` into the env.

    Idempotent: an existing key at ``.onion-identity/hs`` is reused so the address
    is stable across runs (and can be restored after ``make test``/``autoformat``
    regenerate ``.env``). Setting ``INFINITO_DOMAIN`` makes the whole harness —
    coredns, docker ``dns-search`` and ``DOMAIN_PRIMARY`` — resolve the same onion;
    the key files make the daemon serve exactly that address. Returns it.
    """
    env_path = Path(env_file)
    hs = identity_hs_dir(env_path.parent)
    hostname_file = hs / "hostname"
    if hostname_file.exists():
        address = hostname_file.read_text(
            encoding="ascii"
        ).strip()  # nocheck: cache-read
    else:
        key = mint()
        _write_files(hs, key.files())
        address = key.address
    # Escape the literal dot for the coredns regex; match the existing .env style
    # (double backslash inside double quotes).
    domain_re = address.replace(".", "\\\\.")
    _upsert_env(
        env_path,
        {
            "INFINITO_DOMAIN": address,
            "INFINITO_DOMAIN_RE": f'"{domain_re}"',
        },
    )
    return address
