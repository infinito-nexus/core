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
import subprocess
from typing import TYPE_CHECKING, Any

from cli.administration.deploy.development.profile import Profile
from utils.cache import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping

_FORWARDED_ENV_KEYS = (
    "APP_ID",
    "guide_host",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY_OWNER",
    "GITHUB_REPOSITORY",
    "INFINITO_GHCR_MIRROR_PREFIX",
)
_IMAGE_KEY = "INFINITO_IMAGE"
_IMAGE_TAG_KEY = "INFINITO_IMAGE_TAG"
_LOCAL_IMAGE_TAG_PREFIX = "dev-"
_LOCAL_IMAGE_SCRIPT = (
    PROJECT_ROOT / "scripts" / "meta" / "resolve" / "image" / "local.sh"
)


def deploy_image_tag() -> str:
    """Return the Infinito.Nexus image tag the deploy pins its images to.

    Returns:
        ``INFINITO_IMAGE_TAG`` on CI, which tags the images it built;
        ``dev-<commit>`` of this checkout's ``HEAD`` everywhere else.
    """
    if Profile().is_ci():
        return os.environ[_IMAGE_TAG_KEY]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return f"{_LOCAL_IMAGE_TAG_PREFIX}{head.stdout.strip()}"


def pin_deploy_image(env: dict[str, str]) -> None:
    """Point a deploy that runs outside the infinito container at the image of this checkout.

    Args:
        env: the deploy's environment, updated in place: ``INFINITO_IMAGE_TAG``
            becomes :func:`deploy_image_tag`, and an empty ``INFINITO_IMAGE``
            the local image name the compose stack resolves the same way.
    """
    env[_IMAGE_TAG_KEY] = deploy_image_tag()
    if not env.get(_IMAGE_KEY):
        env[_IMAGE_KEY] = subprocess.run(
            ["bash", str(_LOCAL_IMAGE_SCRIPT)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()


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
        "--validate",
        "true",
        "--diff",
        "--skip-pull",
        "--id",
        *deploy_ids,
    ]
    if debug:
        cmd.insert(cmd.index("--diff") + 1, "--debug")

    if extra_ansible_vars:
        for key, value in extra_ansible_vars.items():
            cmd.extend(["-e", f"{key}={json.dumps(value, separators=(',', ':'))}"])

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
    extra_env[_IMAGE_TAG_KEY] = deploy_image_tag()

    r = compose.exec(
        cmd,
        check=False,
        live=True,
        extra_env=extra_env,
    )

    return int(r.returncode)
