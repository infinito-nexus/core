"""The pinned MDAD release still creates the usage exporter with our extra arguments.

web-app-matrix caps the exporter's open-files limit by setting
``matrix_synapse_usage_exporter_container_extra_arguments`` in the MDAD vars it
renders. MDAD ignores an unknown variable without a word, so a pin bump that
renames or drops it would bring back the uncapped exporter that pinned 16 GiB
in CI run 42239638356, with every deploy still green until memory runs out.

The variable lives in the upstream repository at the pinned ref, not in this
one, so the check is external: it fetches two files of that ref from
raw.githubusercontent.com. A timeout or a refused connection is reported as
unverified rather than failing, the way the sibling external checks do; a
fetched file that lacks the variable is a defect of the pin and fails.
"""

from __future__ import annotations

import re
import unittest
from urllib.parse import urlsplit

import requests

from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_SERVICES = PROJECT_ROOT / "roles/web-app-matrix" / ROLE_FILE_META_SERVICES
_VAR = "matrix_synapse_usage_exporter_container_extra_arguments"
_ROLE = "roles/custom/matrix-synapse-usage-exporter"
_DEFAULTS = f"{_ROLE}/{ROLE_FILE_DEFAULTS_MAIN}"
_SERVICE_UNIT = f"{_ROLE}/templates/systemd/matrix-synapse-usage-exporter.service.j2"
_TIMEOUT_SECONDS = 20


def _raw_base() -> str:
    upstream = load_yaml_any(str(_SERVICES))["matrix"]["upstream"]
    slug = urlsplit(upstream["repo"]).path.strip("/").removesuffix(".git")
    return f"https://raw.githubusercontent.com/{slug}/{upstream['ref']}"


class TestMatrixMdadExporterExtraArgs(unittest.TestCase):
    def _fetch(self, path: str) -> str:
        url = f"{_raw_base()}/{path}"
        try:
            response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            warning(
                f"{url} was not checked ({type(exc).__name__}: {exc})",
                title="MDAD pin unverified",
                file=str(_SERVICES.relative_to(PROJECT_ROOT)),
            )
            self.skipTest(f"{url} unreachable")
        self.assertEqual(
            response.status_code,
            200,
            f"{url} answered HTTP {response.status_code}; the MDAD pin no longer "
            "ships the usage exporter role at this path",
        )
        return response.text

    def test_the_pinned_defaults_declare_the_variable(self) -> None:
        self.assertIsNotNone(
            re.search(rf"^{_VAR}:", self._fetch(_DEFAULTS), re.MULTILINE),
            f"the MDAD pin no longer declares {_VAR}; the exporter starts without "
            "its open-files cap",
        )

    def test_the_pinned_unit_passes_the_variable_to_docker_create(self) -> None:
        self.assertIsNotNone(
            re.search(
                rf"{{%\s*for\s+\w+\s+in\s+{_VAR}\s*%}}", self._fetch(_SERVICE_UNIT)
            ),
            f"the MDAD pin's exporter unit no longer loops over {_VAR}; the "
            "variable is declared but never reaches docker create",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
