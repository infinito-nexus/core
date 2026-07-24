import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ansible.errors import AnsibleError
from jinja2 import Environment, StrictUndefined, select_autoescape

# Adjust the PYTHONPATH to include the lookup_plugins folder from the web-app-dashboard role.
sys.path.insert(
    0,
    str(
        Path(str(Path(__file__).parent))
        / "../../../../roles/web-app-dashboard/lookup_plugins"
    ),
)

import docker_cards as docker_cards_module
from docker_cards import LookupModule

from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_VARS_MAIN,
)


def _ansible_bool(value):
    """
    Minimal Ansible-like bool filter for unit tests.
    Mirrors common Ansible truthy/falsey handling for strings.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"y", "yes", "true", "on", "1"}:
            return True
        if v in {"n", "no", "false", "off", "0", ""}:
            return False
    return bool(value)


class DummyTemplar:
    """
    Small, deterministic templating stub for unit tests.
    It is intentionally minimal: only supports rendering Jinja strings
    and provides an Ansible-like `bool` filter.
    """

    def __init__(self, variables):
        self._vars = variables
        self._env = Environment(
            undefined=StrictUndefined, autoescape=select_autoescape()
        )
        self._env.filters["bool"] = _ansible_bool

    def template(self, value):
        if value is None:
            return value

        # Keep non-strings untouched
        if not isinstance(value, str):
            return value

        # Only render if it looks like a Jinja template
        if "{{" in value and "}}" in value:
            tmpl = self._env.from_string(value)
            return tmpl.render(**self._vars)

        return value


class DummyTlsResolveLookup:
    """
    Deterministic tls stub.
    Emulates: lookup('tls', app_id, 'url.base') -> 'http(s)://domain/'
    """

    def __init__(self, templar):
        self._templar = templar

    def run(self, terms, variables=None, **kwargs):
        variables = variables or {}

        # NEW API: want-path is positional (2nd term)
        if not terms or len(terms) not in (1, 2):
            raise AnsibleError(
                "dummy tls: terms must be [app_id] or [app_id, want_path]"
            )

        app_id = str(terms[0]).strip()
        if not app_id:
            raise AnsibleError("dummy tls: empty term")

        want = ""
        if len(terms) == 2:
            want = str(terms[1]).strip()

        domains = variables.get("domains", {})
        if app_id not in domains:
            raise AnsibleError(f"dummy tls: app_id '{app_id}' not in domains")

        # normalize domain mapping value (string / dict / list)
        domain_val = domains[app_id]
        if isinstance(domain_val, list):
            domain = domain_val[0] if domain_val else ""
        elif isinstance(domain_val, dict):
            domain = next(iter(domain_val.values()), "")
        else:
            domain = domain_val

        domain = self._templar.template(domain).strip() if domain else ""
        if not domain:
            raise AnsibleError(f"dummy tls: empty domain for '{app_id}'")

        tls_enabled = _ansible_bool(variables.get("TLS_ENABLED", True))
        scheme = "https" if tls_enabled else "http"
        base_url = f"{scheme}://{domain}/"

        if want and want != "url.base":
            raise AnsibleError(f"dummy tls: unsupported want_path='{want}'")

        return [base_url]


class TestDockerCardsLookup(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to simulate the roles directory.
        self.test_roles_dir = tempfile.mkdtemp(prefix="test_roles_")

        # Create a sample role "web-app-dashboard" under that directory.
        self.role_name = "web-app-dashboard"
        self.role_dir = str(Path(self.test_roles_dir) / self.role_name)
        Path(str(Path(self.role_dir) / "meta")).mkdir(parents=True)
        Path(str(Path(self.role_dir) / "vars")).mkdir(parents=True)

        vars_main = str(Path(self.role_dir) / ROLE_FILE_VARS_MAIN)
        with Path(vars_main).open("w", encoding="utf-8") as f:
            f.write("application_id: portfolio\n")

        # Create a sample README.md with a H1 line for the title.
        readme_path = str(Path(self.role_dir) / "README.md")
        with Path(readme_path).open("w", encoding="utf-8") as f:
            f.write("# Portfolio Application\nThis is a sample portfolio role.")

        # Create a sample meta/main.yml in the meta folder. Per
        # the icon class lives in meta/info.yml (file-root convention),
        # not under galaxy_info.
        meta_main_path = str(Path(self.role_dir) / ROLE_FILE_META_MAIN)
        meta_yaml = """
galaxy_info:
  description: "A role for deploying a portfolio application."
"""
        with Path(meta_main_path).open("w", encoding="utf-8") as f:
            f.write(meta_yaml)

        meta_info_path = str(Path(self.role_dir) / ROLE_FILE_META_INFO)
        info_yaml = """
logo:
  class: fa-solid fa-briefcase
"""
        with Path(meta_info_path).open("w", encoding="utf-8") as f:
            f.write(info_yaml)

        self._orig_lookup_get = docker_cards_module.lookup_loader.get

        class _VarsLookup:
            def __init__(self, key):
                self._key = key

            def run(self, terms, variables=None, **kwargs):
                return [(variables or {}).get(self._key, {})]

        def _patched_get(name, loader=None, templar=None):
            if name == "applications":
                return _VarsLookup("applications")
            if name == "domains":
                return _VarsLookup("domains")
            if name == "tls":
                return DummyTlsResolveLookup(templar)
            raise AnsibleError(f"Unexpected lookup requested: {name}")

        docker_cards_module.lookup_loader.get = _patched_get

    def tearDown(self):
        # Restore patched lookup_loader
        docker_cards_module.lookup_loader.get = self._orig_lookup_get

        # Remove the temporary roles directory after the test.
        shutil.rmtree(self.test_roles_dir)

    def _base_fake_variables(self):
        # include TLS vars (even if our stub doesn't need all of them)
        return {
            "domains": {"portfolio": "myportfolio.com"},
            "applications": {
                # Per the materialised payload moved to services.<X>.
                "portfolio": {"services": {"dashboard": {"enabled": True}}}
            },
            "group_names": ["portfolio"],
            "TLS_ENABLED": True,
            "TLS_MODE": "letsencrypt",
            "LETSENCRYPT_BASE_PATH": "/etc/letsencrypt",
            "LETSENCRYPT_LIVE_PATH": "/etc/letsencrypt/live",
        }

    def _run_lookup(self, lookup_module, fake_variables):
        # Provide deterministic templating behavior for unit tests.
        lookup_module._templar = DummyTemplar(fake_variables)
        lookup_module._loader = mock.MagicMock()
        return lookup_module.run([self.test_roles_dir], variables=fake_variables)

    def test_lookup_when_group_includes_application_id(self):
        lookup_module = LookupModule()

        fake_variables = self._base_fake_variables()
        fake_variables["TLS_ENABLED"] = True

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

        cards = result[0]
        self.assertIsInstance(cards, list)
        self.assertEqual(len(cards), 1)

        card = cards[0]
        self.assertEqual(card["title"], "Portfolio Application")
        self.assertEqual(card["text"], "A role for deploying a portfolio application.")
        self.assertEqual(card["icon"]["class"], "fa-solid fa-briefcase")
        self.assertEqual(card["url"], "https://myportfolio.com")
        self.assertTrue(card["iframe"])

    def test_iframe_flag_defaults_to_enabled(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertTrue(result[0][0]["iframe"])

    def test_iframe_flag_false_decouples_from_enabled(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()
        fake_variables["applications"]["portfolio"]["services"]["dashboard"][
            "iframe"
        ] = False

        result = self._run_lookup(lookup_module, fake_variables)

        cards = result[0]
        self.assertEqual(len(cards), 1)
        self.assertFalse(cards[0]["iframe"])

    def test_lookup_url_uses_https_when_tls_enabled_true(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()
        fake_variables["TLS_ENABLED"] = True

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(result[0][0]["url"], "https://myportfolio.com")

    def test_lookup_url_uses_http_when_tls_enabled_false(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()
        fake_variables["TLS_ENABLED"] = False

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(result[0][0]["url"], "http://myportfolio.com")

    def test_lookup_when_group_excludes_application_id(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()
        fake_variables["group_names"] = []  # Not including "portfolio"

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 0)

    def test_lookup_url_renders_domain_url_jinja(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()

        fake_variables["domains"] = {"portfolio": "{{ DOMAIN_PRIMARY }}"}
        fake_variables["DOMAIN_PRIMARY"] = "myportfolio.com"
        fake_variables["TLS_ENABLED"] = True

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(result[0][0]["url"], "https://myportfolio.com")

    def test_lookup_url_https_when_tls_enabled_is_string(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()

        fake_variables["TLS_ENABLED"] = "true"

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(result[0][0]["url"], "https://myportfolio.com")

    def test_lookup_url_http_when_tls_enabled_is_string(self):
        lookup_module = LookupModule()
        fake_variables = self._base_fake_variables()

        fake_variables["TLS_ENABLED"] = "false"

        result = self._run_lookup(lookup_module, fake_variables)

        self.assertEqual(result[0][0]["url"], "http://myportfolio.com")


if __name__ == "__main__":
    unittest.main()
