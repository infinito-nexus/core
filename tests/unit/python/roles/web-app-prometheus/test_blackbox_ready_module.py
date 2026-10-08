from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str

TEMPLATE_DIR = PROJECT_ROOT / "roles/web-app-prometheus/templates/configuration"


def ready_module(*, tls_mode: str, prometheus_tls: bool, ca_injected: bool) -> dict:
    def lookup(name, *terms):
        if name == "tls" and terms[1] == "enabled":
            return prometheus_tls
        if name == "ca_injected":
            return ca_injected
        raise AssertionError(f"the template calls an unexpected lookup: {name!r}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    rendered = env.get_template("blackbox.yml.j2").render(
        lookup=lookup,
        application_id="web-app-prometheus",
        TLS_MODE=tls_mode,
    )
    return load_yaml_str(rendered)["modules"]["http_ready"]["http"]


class TestBlackboxReadyModule(unittest.TestCase):
    def test_an_http_target_passes_while_prometheus_itself_uses_tls(self):
        module = ready_module(
            tls_mode="letsencrypt", prometheus_tls=True, ca_injected=False
        )
        self.assertIs(module["fail_if_not_ssl"], False)

    def test_certificates_are_verified_while_prometheus_itself_has_no_tls(self):
        module = ready_module(
            tls_mode="letsencrypt", prometheus_tls=False, ca_injected=False
        )
        self.assertIs(module["tls_config"]["insecure_skip_verify"], False)

    def test_certificates_are_verified_once_the_private_ca_is_mounted(self):
        module = ready_module(
            tls_mode="self_signed", prometheus_tls=True, ca_injected=True
        )
        self.assertIs(module["tls_config"]["insecure_skip_verify"], False)

    def test_verification_is_skipped_only_without_the_private_ca(self):
        module = ready_module(
            tls_mode="self_signed", prometheus_tls=False, ca_injected=False
        )
        self.assertIs(module["tls_config"]["insecure_skip_verify"], True)


if __name__ == "__main__":
    unittest.main()
