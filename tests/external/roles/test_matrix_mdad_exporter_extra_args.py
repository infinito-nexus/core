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

from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

from . import fetch_mdad_file

_VAR = "matrix_synapse_usage_exporter_container_extra_arguments"
_ROLE = "roles/custom/matrix-synapse-usage-exporter"
_DEFAULTS = f"{_ROLE}/{ROLE_FILE_DEFAULTS_MAIN}"
_SERVICE_UNIT = f"{_ROLE}/templates/systemd/matrix-synapse-usage-exporter.service.j2"


class TestMatrixMdadExporterExtraArgs(unittest.TestCase):
    def test_the_pinned_defaults_declare_the_variable(self) -> None:
        self.assertIsNotNone(
            re.search(rf"^{_VAR}:", fetch_mdad_file(self, _DEFAULTS), re.MULTILINE),
            f"the MDAD pin no longer declares {_VAR}; the exporter starts without "
            "its open-files cap",
        )

    def test_the_pinned_unit_passes_the_variable_to_docker_create(self) -> None:
        self.assertIsNotNone(
            re.search(
                rf"{{%\s*for\s+\w+\s+in\s+{_VAR}\s*%}}",
                fetch_mdad_file(self, _SERVICE_UNIT),
            ),
            f"the MDAD pin's exporter unit no longer loops over {_VAR}; the "
            "variable is declared but never reaches docker create",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
