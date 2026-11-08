"""The software's identity: its repository, read from the group_vars SPOT, its author and address."""

from __future__ import annotations

import os

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.distros import environment_image
from utils.env.parser import parse_static_env

SOFTWARE_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"
SOFTWARE_NAME: str = load_yaml(str(SOFTWARE_VARS))["SOFTWARE_NAME"]
SOFTWARE_REPOSITORY: str = load_yaml(str(SOFTWARE_VARS))["SOFTWARE_REPOSITORY"]
SOFTWARE_AUTHOR = "Kevin Veen-Birkenbach"
SOFTWARE_EMAIL = "kevinveenbirkenbach@infinito.nexus"
SOFTWARE_URL = "https://infinito.nexus"
SOFTWARE_CONTACT = "contact@infinito.nexus"
SOFTWARE_LICENSE = "Infinito.Nexus Community License (Non-Commercial)"
DEPLOY_IMAGE_ENV = "INFINITO_IMAGE"


def deploy_image() -> str:
    """Reference of the image the published deploy instructions tell a reader to run.

    Returns:
        The ``INFINITO_IMAGE`` the run resolved for itself when set, otherwise
        the environment image of the distro and tag ``default.env`` declares,
        under the owner and repository of ``SOFTWARE_REPOSITORY``.
    """
    if override := os.environ.get(DEPLOY_IMAGE_ENV):
        return override
    declared = parse_static_env(PROJECT_ROOT / "default.env")
    owner, repository = SOFTWARE_REPOSITORY.removesuffix(".git").rsplit("/", 2)[-2:]
    return environment_image(
        declared["INFINITO_DISTRO"],
        owner,
        repository,
        declared["INFINITO_IMAGE_TAG"],
    )
