from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar, trust_as_template

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-opt-rdr-domains"
PROBE_PLUGIN = """
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables, **kwargs):
        return [variables["domain"]]
"""
TEMPLATE = "{{ domain }} {{ lookup('rdr_probe_variables_domain') }}\n"


class _NoDeepCopy:
    def __deepcopy__(self, memo):
        raise AssertionError("the variables were deep-copied")


class TestTemplateShallow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        (tmp / "plugins").mkdir()
        (tmp / "plugins" / "rdr_probe_variables_domain.py").write_text(PROBE_PLUGIN)
        (tmp / "templates").mkdir()
        (tmp / "templates" / "vhost.j2").write_text(TEMPLATE)
        lookup_loader.add_directory(str(ROLE / "lookup_plugins"))
        lookup_loader.add_directory(str(tmp / "plugins"))
        cls.search_path = [str(tmp)]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _variables(self) -> dict:
        return {"domain": "play.example", "ansible_search_path": self.search_path}

    def _render(self, plugin: str, variables: dict) -> str:
        return Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template(
                "{{ lookup('" + plugin + "', 'vhost.j2', "
                "template_vars={'domain': 'source.example'}) }}"
            )
        )

    def test_a_lookup_inside_the_template_reads_the_per_call_domain(self) -> None:
        rendered = self._render("template_shallow", self._variables())
        self.assertEqual(rendered, "source.example source.example\n")
        self.assertEqual(rendered, self._render("template", self._variables()))

    def test_the_caller_variables_keep_their_values(self) -> None:
        variables = self._variables()
        self._render("template_shallow", variables)
        self.assertEqual(variables, self._variables())

    def test_no_value_of_the_caller_is_deep_copied(self) -> None:
        variables = {**self._variables(), "untouchable": _NoDeepCopy()}
        self.assertEqual(
            self._render("template_shallow", variables),
            "source.example source.example\n",
        )
        with self.assertRaises(AnsibleError) as raised:
            self._render("template", variables)
        causes = []
        error: BaseException | None = raised.exception
        while error is not None:
            causes.append(str(error))
            error = error.__cause__
        self.assertTrue(any("deep-copied" in cause for cause in causes), causes)


class TestRedirectLoopRendersShallow(unittest.TestCase):
    def test_both_files_of_every_source_render_through_template_shallow(
        self,
    ) -> None:
        tasks = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))
        [loop_task] = [
            task for task in tasks if "redirect_source" in task.get("vars", {})
        ]
        files = loop_task["vars"]["redirect_source"]["files"]
        self.assertEqual(files.count("lookup('template_shallow', "), 2)
        self.assertNotIn("lookup('template', ", json.dumps(loop_task))


if __name__ == "__main__":
    unittest.main()
