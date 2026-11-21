import argparse
import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from cli.administration.deploy.dedicated import modes
from cli.administration.deploy.dedicated.paths import MODES_FILE
from utils.cache.yaml import load_yaml_any


class TestModeValidate(unittest.TestCase):
    spec: ClassVar[dict[str, Any]]
    parser: ClassVar[argparse.ArgumentParser]

    @classmethod
    def setUpClass(cls):
        cls.parser = argparse.ArgumentParser()
        cls.spec = modes.add_dynamic_mode_args(
            cls.parser, modes.load_modes_from_yaml(MODES_FILE)
        )

    def _resolve(self, *argv: str) -> dict[str, Any]:
        return modes.build_modes_from_args(self.spec, self.parser.parse_args(argv))

    def _default_validate(self, debug: bool) -> bool:
        variables = {
            key: trust_as_template(value) if isinstance(value, str) else value
            for key, value in load_yaml_any(MODES_FILE).items()
        }
        variables["DEBUG"] = debug
        templar = Templar(loader=DataLoader(), variables=variables)
        return templar.evaluate_conditional(trust_as_template("VALIDATE | bool"))

    def test_the_playbook_default_follows_debug(self):
        self.assertIs(load_yaml_any(MODES_FILE)["DEBUG"], False)
        self.assertIs(self._default_validate(debug=False), False)
        self.assertIs(self._default_validate(debug=True), True)

    def test_no_flag_leaves_the_playbook_default(self):
        self.assertNotIn("VALIDATE", self._resolve())

    def test_validate_false_reaches_the_playbook(self):
        self.assertIs(self._resolve("--validate", "false")["VALIDATE"], False)

    def test_validate_true_reaches_the_playbook(self):
        self.assertIs(self._resolve("--validate", "true")["VALIDATE"], True)


if __name__ == "__main__":
    unittest.main()
