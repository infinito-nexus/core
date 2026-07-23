"""Execute one deploy pass inside the infinito container.

:func:`_run_deploy` is the SPOT for how a single
``cli.administration.deploy.dedicated`` invocation is assembled: the
inventory/password file layout, the ansible CLI flags, the ``-e`` var
encoding, and which host environment variables are forwarded into the
container.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_FORWARDED_ENV_KEYS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY_OWNER",
    "GITHUB_REPOSITORY",
    "INFINITO_IMAGE_TAG",
    "INFINITO_GHCR_MIRROR_PREFIX",
)


def _run_deploy(
    compose,
    *,
    deploy_ids: list[str],
    debug: bool,
    passthrough: list[str],
    inventory_dir: str,
    container_name: str,
    extra_ansible_vars: Mapping[str, Any] | None = None,
) -> int:
    inv_root = str(inventory_dir).rstrip("/")
    inv_file = f"{inv_root}/devices.yml"
    pw_file = f"{inv_root}/.password"

    cmd = [
        "python3",
        "-m",
        "cli.administration.deploy.dedicated",
        inv_file,
        "-p",
        pw_file,
        "-vv",
        "--assert",
        "true",
        "--diff",
        "--id",
        *deploy_ids,
    ]
    if debug:
        cmd.insert(cmd.index("--diff") + 1, "--debug")

    if extra_ansible_vars:
        for key, value in extra_ansible_vars.items():
            cmd.extend(["-e", f"{key}={json.dumps(value)}"])

    if passthrough:
        cmd.extend(passthrough)

    extra_env: dict[str, str] = {
        "ANSIBLE_FORCE_COLOR": "1",
        "PY_COLORS": "1",
        "TERM": "xterm-256color",
    }
    services_disabled = os.environ.get("disable", "")
    if services_disabled:
        extra_env["disable"] = services_disabled

    ansible_log_path = (
        os.environ.get("ANSIBLE_LOG_PATH") or "/tmp/infinito-deploy.log"  # noqa: S108 - fixed fallback log path inside the ephemeral CI container
    )
    extra_env["ANSIBLE_LOG_PATH"] = ansible_log_path

    for key in _FORWARDED_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            extra_env[key] = val

    r = compose.exec(
        cmd,
        check=False,
        live=True,
        extra_env=extra_env,
    )

    return int(r.returncode)
