from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar, trust_as_template

from . import PROJECT_ROOT

PROBE_PLUGIN = """
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables, **kwargs):
        return [variables["domain"]]
"""
MUTATING_PLUGIN = """
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables, **kwargs):
        variables["nested"]["hosts"].append("leaked.example")
        return [""]
"""
TEMPLATES = {
    "vhost.j2": "{{ domain }} {{ lookup('shallow_probe_variables_domain') }}\n",
    "broken.j2": "{{ domain }} {{ undefined_in_template }}\n",
    "mutating.j2": "{{ lookup('shallow_probe_mutates_nested') }}\n",
}


class _NoDeepCopy:
    def __deepcopy__(self, memo):
        raise AssertionError("the variables were deep-copied")


def _causes(error: BaseException | None) -> list[str]:
    causes = []
    while error is not None:
        causes.append(str(error))
        error = error.__cause__
    return causes


class TestTemplateShallow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        (tmp / "plugins").mkdir()
        (tmp / "plugins" / "shallow_probe_variables_domain.py").write_text(PROBE_PLUGIN)
        (tmp / "plugins" / "shallow_probe_mutates_nested.py").write_text(
            MUTATING_PLUGIN
        )
        (tmp / "templates").mkdir()
        for name, body in TEMPLATES.items():
            (tmp / "templates" / name).write_text(body)
        lookup_loader.add_directory(str(PROJECT_ROOT / "plugins" / "lookup"))
        lookup_loader.add_directory(str(tmp / "plugins"))
        cls.search_path = [str(tmp)]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _variables(self) -> dict:
        return {
            "domain": "play.example",
            "nested": {"hosts": ["a.example"]},
            "ansible_search_path": self.search_path,
        }

    def _render(self, plugin: str, variables: dict, template: str = "vhost.j2"):
        return Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template(
                "{{ lookup('" + plugin + "', '" + template + "', "
                "template_vars={'domain': 'source.example'}) }}"
            )
        )

    def test_a_lookup_inside_the_template_reads_the_per_call_domain(self) -> None:
        rendered = self._render("template_shallow", self._variables())
        self.assertEqual(rendered, "source.example source.example\n")
        self.assertEqual(rendered, self._render("template", self._variables()))

    def test_the_caller_variables_keep_their_values_and_identity(self) -> None:
        variables = self._variables()
        nested = variables["nested"]
        self._render("template_shallow", variables)
        self.assertEqual(variables, self._variables())
        self.assertIs(variables["nested"], nested)

    def test_no_value_of_the_caller_is_deep_copied(self) -> None:
        variables = {**self._variables(), "untouchable": _NoDeepCopy()}
        self.assertEqual(
            self._render("template_shallow", variables),
            "source.example source.example\n",
        )

    def test_the_builtin_template_lookup_deep_copies_every_value(self) -> None:
        variables = {**self._variables(), "untouchable": _NoDeepCopy()}
        with self.assertRaises(AnsibleError) as raised:
            self._render("template", variables)
        causes = _causes(raised.exception)
        self.assertTrue(any("deep-copied" in cause for cause in causes), causes)

    def test_a_lookup_mutating_a_nested_value_leaks_only_through_the_shallow_copy(
        self,
    ) -> None:
        builtin = self._variables()
        self._render("template", builtin, "mutating.j2")
        self.assertEqual(builtin, self._variables())
        shallow = self._variables()
        self._render("template_shallow", shallow, "mutating.j2")
        self.assertEqual(shallow["nested"]["hosts"], ["a.example", "leaked.example"])

    def test_an_undefined_variable_fails_with_the_builtin_message(self) -> None:
        messages = {}
        for plugin in ("template", "template_shallow"):
            with self.assertRaises(AnsibleError) as raised:
                self._render(plugin, self._variables(), "broken.j2")
            messages[plugin] = [
                cause.replace("template_shallow", "template")
                for cause in _causes(raised.exception)
            ]
        self.assertIn("undefined_in_template", " ".join(messages["template"]))
        self.assertEqual(messages["template_shallow"], messages["template"])

    def test_a_missing_template_fails_with_the_builtin_message(self) -> None:
        messages = {}
        for plugin in ("template", "template_shallow"):
            with self.assertRaises(AnsibleError) as raised:
                self._render(plugin, self._variables(), "absent.j2")
            messages[plugin] = [
                cause.replace("template_shallow", "template")
                for cause in _causes(raised.exception)
            ]
        self.assertIn("absent.j2", " ".join(messages["template"]))
        self.assertEqual(messages["template_shallow"], messages["template"])


if __name__ == "__main__":
    unittest.main()
