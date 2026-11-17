from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.docker.image.toolchain import DOCKERFILE, input_files

if TYPE_CHECKING:
    from pathlib import Path

SUPPORT_FILES = (
    ".gitignore",
    "scripts/image/build.sh",
    "scripts/image/cleanup_local.sh",
    "scripts/image/prune.sh",
    "scripts/meta/env/load.sh",
    "scripts/meta/env/python.sh",
    "scripts/meta/resolve/image/local.sh",
    "scripts/meta/resolve/repository/name.sh",
    "scripts/meta/resolve/repository/primary.sh",
    "utils/docker/__init__.py",
    "utils/docker/image/__init__.py",
    "utils/docker/image/toolchain.py",
)

DISTRO = "debian"
PARENT_IMAGE = "ghcr.io/example/pkgmgr-debian:stable"
LOADED_FILE_KEY = "INFINITO_ENV_LOADED_FILE"  # nocheck: env-loader-internal-guard

DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_LOG}"
case "$1 $2" in
"image inspect")
\t[ -n "${STUB_PARENT_ID:-}" ] || exit 1
\tprintf '%s\\n' "${STUB_PARENT_ID}"
\t;;
"builder prune")
\t[ "$3" = "--help" ] && printf '      --max-used-space bytes\\n'
\t;;
"image ls")
\tprintf '%s' "${STUB_IMAGES:-}"
\t;;
"ps -a")
\tprintf '%s' "${STUB_CONTAINER_IMAGES:-}"
\t;;
esac
if [ "$1" = "build" ]; then
\tfor last; do :; done
\tfind "${last}" -type f -printf '%P %s\\n' | LC_ALL=C sort >"${STUB_CONTEXT}"
fi
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    """Run git with the operator's global and system configuration masked out.

    Args:
        cwd: directory git runs in.
        args: the git arguments.
    """
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.invalid",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout


def toolchain_checkout(base: Path, extra: tuple[str, ...] = ()) -> Path:
    """Copy the toolchain inputs and the scripts resolving and building them into a committed repository.

    Args:
        base: empty directory; the repository lands in ``base/primary``.
        extra: further repository files the caller's script needs.

    Returns:
        The repository's root.
    """
    root = base / "primary"
    for rel in (DOCKERFILE, *input_files(PROJECT_ROOT), *SUPPORT_FILES, *extra):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / rel, target)
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "--no-verify", "--message", "probe")
    return root


def stub_docker(base: Path) -> Path:
    """Write the docker stub and return the directory to put first on PATH.

    Args:
        base: directory the stub lands under.
    """
    bin_dir = base / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    return bin_dir


def loaded_env(base: Path, **overrides: str) -> dict[str, str]:
    """Environment of a caller that already sourced load.sh for ``DISTRO``.

    Args:
        base: directory holding the docker stub's ``bin`` and its log files.
        overrides: values that replace the defaults below.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("INFINITO_", "GITHUB_", "GIT_"))
        and key not in {"BASH_ENV", "REPO_PREFIX", "OWNER", "PYTHONPATH", "VENV"}
    }
    env.update(
        {
            "PATH": f"{base / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(base / "docker.log"),
            "STUB_CONTEXT": str(base / "context.txt"),
            "INFINITO_ENV_LOADED": "1",  # nocheck: env-loader-internal-guard
            "INFINITO_ENV_LOADED_MTIME": "0",  # nocheck: env-loader-internal-guard
            "INFINITO_ENV_LOADED_DISTRO": DISTRO,  # nocheck: env-loader-internal-guard
            "INFINITO_ENV_LOADED_STACK": "",  # nocheck: env-loader-internal-guard
            "INFINITO_DISTRO": DISTRO,
            "INFINITO_PARENT_IMAGE": PARENT_IMAGE,
            "INFINITO_SRC_DIR": "/opt/src/infinito",
            "INFINITO_VENV_DIR": "/opt/venvs/infinito",
            "INFINITO_PACKAGE_INSTALL_SCRIPT": "scripts/install/package.sh",
            "INFINITO_PYTHON_INSTALL_SCRIPT": "roles/dev-python/files/shell/install.sh",
            "INFINITO_DOCKER_CLI_INSTALL_SCRIPT": "roles/sys-svc-container/files/shell/install-cli.sh",
            "INFINITO_BUILD_CACHE_MAX_SIZE": "20g",
            "INFINITO_LINT_RUNNER": "docker",
            "STUB_PARENT_ID": "sha256:parent-a",
        }
    )
    env.update(overrides)
    return env


def loaded_in(checkout: Path, env: dict[str, str]) -> dict[str, str]:
    """Return ``env`` as load.sh leaves it once it loaded ``checkout``.

    Args:
        checkout: repository root whose scripts the call runs.
        env: an environment of :func:`loaded_env`.

    Returns:
        ``env`` naming the ``.env`` of ``checkout`` as loaded, so its load.sh
        keeps ``env`` instead of generating a ``.env`` through the ``cli``
        package the caller's interpreter happens to import.
    """
    return {**env, LOADED_FILE_KEY: str(checkout / ".env")}


def resolve_tag(checkout: Path, env: dict[str, str]) -> str:
    """Run the checkout's own local.sh and return the tag it prints.

    Args:
        checkout: repository root to resolve the tag in.
        env: environment of the call.
    """
    done = subprocess.run(
        ["bash", str(checkout / "scripts/meta/resolve/image/local.sh")],
        cwd=checkout,
        env=loaded_in(checkout, env),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()
