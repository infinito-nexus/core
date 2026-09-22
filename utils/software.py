"""The software's identity: its repository, read from the group_vars SPOT, its author and address."""

from __future__ import annotations

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

SOFTWARE_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"
SOFTWARE_REPOSITORY: str = load_yaml(str(SOFTWARE_VARS))["SOFTWARE_REPOSITORY"]
SOFTWARE_AUTHOR = "Kevin Veen-Birkenbach"
SOFTWARE_EMAIL = "kevinveenbirkenbach@infinito.nexus"
SOFTWARE_URL = "https://infinito.nexus"
SOFTWARE_CONTACT = "contact@infinito.nexus"
SOFTWARE_LICENSE = "Infinito.Nexus Community License (Non-Commercial)"
