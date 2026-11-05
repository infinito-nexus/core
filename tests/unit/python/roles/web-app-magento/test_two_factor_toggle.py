from __future__ import annotations

import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ROLE = PROJECT_ROOT / "roles" / "web-app-magento"
_TWO_FACTOR = _ROLE / "tasks" / "02_two_factor.yml"
_SETUP = _ROLE / "tasks" / "01_setup.yml"
_TOGGLE = "🔐 Enable or disable Magento's two-factor modules"
_NGINX_REGISTERS = {"magento_nginx_restart_compose", "magento_nginx_restart_swarm"}
_PREFIX = "container exec --user app -w /var/www/html magento-php bin/magento"


def _status(*enabled: str) -> dict[str, Any]:
    """Return the register of ``bin/magento module:status --enabled``.

    Args:
        enabled: two-factor modules the command lists next to the always-on ones.

    Returns:
        The register with ``stdout`` and ``stdout_lines`` as Ansible sets them.
    """
    stdout = "\n".join(["Magento_Store", "Magento_Backend", *enabled])
    return {"rc": 0, "stdout": stdout, "stdout_lines": stdout.splitlines()}


def _included_file(task: dict[str, Any]) -> str | None:
    include = task.get("include_tasks")
    return include.get("file") if isinstance(include, dict) else include


class TestTwoFactorToggle(unittest.TestCase):
    toggle: ClassVar[dict[str, Any]]
    modules: ClassVar[list[str]]

    @classmethod
    def setUpClass(cls) -> None:
        tasks = DataLoader().load_from_file(str(_TWO_FACTOR), trusted_as_template=True)
        cls.toggle = next(task for task in tasks if task["name"] == _TOGGLE)
        cls.modules = load_yaml(_ROLE / ROLE_FILE_VARS_MAIN)[
            "MAGENTO_TWO_FACTOR_MODULES"
        ]

    def _toggle(self, flag: bool, status: dict[str, Any]) -> str | None:
        """Render the toggle task for one flag and module state.

        Args:
            flag: ``MAGENTO_TWO_FACTOR_ENABLED``.
            status: the ``magento_enabled_modules`` register.

        Returns:
            The command the task runs, or ``None`` when its ``when`` skips it.
        """
        variables: dict[str, Any] = {
            "MAGENTO_TWO_FACTOR_ENABLED": flag,
            "MAGENTO_TWO_FACTOR_MODULES": self.modules,
            "MAGENTO_USER": "app",
            "MAGENTO_ROOT": "/var/www/html",
            "MAGENTO_PHP_CONTAINER_ADDRESS": "magento-php",
            "magento_enabled_modules": status,
        }
        variables["magento_two_factor_misaligned"] = Templar(
            loader=DataLoader(), variables=variables
        ).template(self.toggle["vars"]["magento_two_factor_misaligned"])
        templar = Templar(loader=DataLoader(), variables=variables)
        condition = self.toggle.get("when")
        if condition is not None and not templar.template(
            trust_as_template("{{ " + condition + " }}")
        ):
            return None
        return templar.template(self.toggle["ansible.builtin.shell"]["cmd"])

    def test_a_redeploy_with_the_modules_already_disabled_runs_no_toggle(self) -> None:
        self.assertIsNone(
            self._toggle(False, _status()),
            "module:disable deletes generated/ before it reads any module state, so a "
            "request PHP-FPM serves meanwhile regenerates classes into it and the "
            "command dies on 'rmdir(/var/www/html/generated/code/Magento): Directory "
            "not empty'",
        )

    def test_a_redeploy_with_the_modules_already_enabled_runs_no_toggle(self) -> None:
        self.assertIsNone(self._toggle(True, _status(*self.modules)))

    def test_a_fresh_install_disables_every_two_factor_module(self) -> None:
        self.assertEqual(
            self._toggle(False, _status(*self.modules)),
            f"{_PREFIX} module:disable {' '.join(self.modules)}",
        )

    def test_only_the_module_still_enabled_is_disabled(self) -> None:
        self.assertEqual(
            self._toggle(False, _status(self.modules[-1])),
            f"{_PREFIX} module:disable {self.modules[-1]}",
        )

    def test_a_raised_flag_enables_the_disabled_modules(self) -> None:
        self.assertEqual(
            self._toggle(True, _status()),
            f"{_PREFIX} module:enable {' '.join(self.modules)}",
        )

    def test_a_fresh_install_toggles_before_nginx_routes_requests_to_php(self) -> None:
        tasks = load_yaml_any(str(_SETUP))
        toggle = next(
            (
                index
                for index, task in enumerate(tasks)
                if _included_file(task) == _TWO_FACTOR.name
            ),
            None,
        )
        self.assertIsNotNone(
            toggle, f"{_SETUP.name} does not include {_TWO_FACTOR.name}"
        )
        nginx = [
            index
            for index, task in enumerate(tasks)
            if task.get("register") in _NGINX_REGISTERS
        ]
        self.assertEqual(len(nginx), len(_NGINX_REGISTERS))
        self.assertLess(
            toggle,
            min(nginx),
            "nginx only includes the Magento vhost after this reload, so a toggle "
            "before it never races a request PHP-FPM serves",
        )


if __name__ == "__main__":
    unittest.main()
