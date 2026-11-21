from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

VHOST_TASKS = PROJECT_ROOT / "roles/svc-stack/tasks/proxy/vhost.yml"
EMPTY = "{% if false %}location /never {\n}\n{% endif %}"
LOCATION = "location /extra {\n    return 204;\n}\n"


class TestVhostExtraTemplates(unittest.TestCase):
    def setUp(self) -> None:
        self.deploy = next(
            task for task in load_yaml_any(VHOST_TASKS) if "stack_host_contents" in task
        )["vars"]
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def template(self, name: str, text: str) -> str:
        """Args:
            name: file name of the template in the scratch search path.
            text: template source.

        Returns:
            the absolute path of the written template.
        """
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def render(self, var: str, **facts: object) -> object:
        """Args:
            var: name of the var of the vhost deploy task to render.
            facts: the per-vhost facts proxy/domain.yml would set.

        Returns:
            the rendered value.
        """
        variables = {
            "ansible_search_path": [str(self.root)],
            "front_proxy_extra_template": "",
            "front_proxy_extra_configuration": "",
            "front_proxy_location_extra_template": "",
            "front_proxy_template_vars": {},
            **facts,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        return templar.template(trust_as_template(self.deploy[var]))

    def test_an_extra_template_that_renders_nothing_adds_no_text(self) -> None:
        extra = self.template("extra.conf.j2", EMPTY)
        self.assertEqual(
            self.render(
                "webserver_extra_configuration", front_proxy_extra_template=extra
            ),
            "",
        )

    def test_an_extra_template_adds_its_text(self) -> None:
        extra = self.template("extra.conf.j2", LOCATION)
        self.assertEqual(
            self.render(
                "webserver_extra_configuration", front_proxy_extra_template=extra
            ),
            LOCATION,
        )

    def test_without_an_extra_template_the_declared_text_applies(self) -> None:
        self.assertEqual(
            self.render(
                "webserver_extra_configuration",
                front_proxy_extra_configuration="return 204;",
            ),
            "return 204;",
        )

    def test_a_location_template_that_renders_nothing_adds_no_text(self) -> None:
        location = self.template("location.conf.j2", EMPTY)
        rendered = self.render(
            "front_proxy_render_vars", front_proxy_location_extra_template=location
        )
        self.assertEqual(rendered["webserver_location_extra_configuration"], "")

    def test_a_location_template_adds_its_text(self) -> None:
        location = self.template("location.conf.j2", LOCATION)
        rendered = self.render(
            "front_proxy_render_vars", front_proxy_location_extra_template=location
        )
        self.assertEqual(rendered["webserver_location_extra_configuration"], LOCATION)

    def test_without_a_location_template_only_the_vhost_vars_apply(self) -> None:
        self.assertEqual(
            self.render(
                "front_proxy_render_vars", front_proxy_template_vars={"aca_origin": "*"}
            ),
            {"aca_origin": "*"},
        )


if __name__ == "__main__":
    unittest.main()
