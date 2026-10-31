"""Throwaway role repositories, inventories and core roles/ trees for the pull tests."""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from pathlib import Path

ROLE = "web-app-cst-demo"
ROLE_PATH = f"ansible/roles/{ROLE}"

_ENV = {
    **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd: Path, *args: str) -> str:
    """Run git in *cwd* with a throwaway identity and no signing.

    Args:
        cwd: the repository.
        args: the git subcommand and its arguments.
    """
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def write(path: Path, text: str) -> Path:
    """Write *text* to *path*, creating its parents.

    Args:
        path: the file.
        text: its content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def role_repo(root: Path, application_id: str = ROLE) -> Path:
    """A repository whose tag ``v1.0.0`` holds the role and whose branch ``feature`` moved on.

    Args:
        root: directory the repository is created in.
        application_id: the ``vars/main.yml`` application_id of the role.
    """
    repo = root / "repo"
    write(repo / "README.md", "repository root\n")
    write(repo / ROLE_PATH / ROLE_FILE_META_MAIN, "galaxy_info: {}\n")
    write(repo / ROLE_PATH / ROLE_FILE_VARS_MAIN, f"application_id: {application_id}\n")
    write(repo / ROLE_PATH / ROLE_FILE_TASKS_MAIN, "release: v1\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v1")
    git(repo, "tag", "v1.0.0")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo / ROLE_PATH / ROLE_FILE_TASKS_MAIN, "release: feature\n")
    git(repo, "commit", "-q", "-am", "feature")
    return repo


def local_role(root: Path, group: str) -> Path:
    """A checkout without Git history that holds the role *group* under ansible/roles/.

    Args:
        root: directory the checkout is created in.
        group: the role's group and application_id.
    """
    checkout = root / f"{group}-checkout"
    write(checkout / "ansible/roles" / group / ROLE_FILE_META_MAIN, "galaxy_info: {}\n")
    write(
        checkout / "ansible/roles" / group / ROLE_FILE_VARS_MAIN,
        f"application_id: {group}\n",
    )
    return checkout


def inventory(root: Path, groups: list[str], applications: dict) -> Path:
    """An inventory whose host joins *groups* and whose host_vars set *applications*.

    Args:
        root: directory the inventory is created in.
        groups: inventory groups ``localhost`` joins.
        applications: the host_vars ``applications`` block.
    """
    write(
        root / "host_vars/localhost.yml",
        json.dumps({"applications": applications}),
    )
    children = {group: {"hosts": {"localhost": {}}} for group in groups}
    return write(root / "devices.yml", json.dumps({"all": {"children": children}}))


def declaration(
    url: str, version: str | None = "v1.0.0", path: str = ROLE_PATH
) -> dict:
    """The ``applications.<group>`` block that declares a custom role.

    Args:
        url: ``source.url``.
        version: ``source.version``; ``None`` leaves it out.
        path: ``source.path``.
    """
    source = {"url": url, "path": path}
    if version is not None:
        source["version"] = version
    return {"custom": True, "source": source}


def roles_dir(root: Path, *in_tree: str) -> Path:
    """A core roles/ holding the given in-tree role directories.

    Args:
        root: directory the roles/ is created in.
        in_tree: names of in-tree roles to create.
    """
    roles = root / "roles"
    roles.mkdir(parents=True)
    for name in in_tree:
        (roles / name).mkdir()
    return roles
