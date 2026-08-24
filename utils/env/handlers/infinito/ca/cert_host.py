"""INFINITO_CA_CERT_HOST: host path of the self-signed root CA cert.

Derived from the ca_trust_paths SPOT plus SOFTWARE_NAME (group_vars); consumed
by scripts/system/tls/trust/*.sh so the path never lives in shell literals.
SOFTWARE_NAME is line-parsed instead of yaml-loaded: the env generator runs on
the bare bootstrap python before any dependency (PyYAML) is installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plugins.filter.ca_trust_paths import ca_cert_host
from utils import PROJECT_ROOT
from utils.cache.files import read_text

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_CA_CERT_HOST"
COMMENT = "Host path of the self-signed root CA cert (ca_trust_paths SPOT)."

_GENERAL_VARS = "group_vars/all/00_general.yml"


def _software_domain() -> str:
    for line in read_text(str(PROJECT_ROOT / _GENERAL_VARS)).splitlines():
        if not line.startswith("SOFTWARE_NAME:"):
            continue
        value = line.split(":", 1)[1].split("#", 1)[0].strip()
        return value.strip("\"'").lower()
    raise RuntimeError(f"SOFTWARE_NAME not found in {_GENERAL_VARS}")


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, ca_cert_host(_software_domain()), comment=COMMENT)
