from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.administration.inventory.credentials import schema
from utils.manager.value_generator import ValueGenerator
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class SchemaInventoryManagerTests(unittest.TestCase):
    def test_the_schema_manager_never_builds_a_value_generator(self):
        with tempfile.TemporaryDirectory() as scratch:
            role = Path(scratch, "web-app-probe")
            role_vars = role / ROLE_FILE_VARS_MAIN
            role_vars.parent.mkdir(parents=True)
            role_vars.write_text("application_id: web-app-probe\n", encoding="utf-8")
            with mock.patch.object(
                ValueGenerator,
                "__init__",
                autospec=True,
                side_effect=AssertionError("schema mode built a value generator"),
            ):
                manager = schema.SchemaInventoryManager(role)

        self.assertIsInstance(manager.value_generator, schema.AlgorithmRecorder)


if __name__ == "__main__":
    unittest.main()
