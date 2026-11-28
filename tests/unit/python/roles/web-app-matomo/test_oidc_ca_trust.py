from __future__ import annotations

import posixpath
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

APP = "web-app-matomo"
ROLE = PROJECT_ROOT / "roles" / APP
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
TLS_VARS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"))
)
CA_TRUST = TLS_VARS["CA_TRUST"]
CA_ROLE = PROJECT_ROOT / "roles" / "sys-ca-selfsigned"
CA_BASE_DIR = "/etc/infinito.example/ca"


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["path_join"] = lambda parts: posixpath.join(*parts)
    return env


def _custom_cacert_pem(*, injected: bool) -> str:
    """
    Args:
        injected: what ``lookup('ca_injected', application_id)`` answers.

    Returns:
        What ``custom_cacert_pem`` of ``MATOMO_OIDC_GENERAL`` renders to.
    """
    env = _environment()

    def lookup(name: str, *terms: str) -> bool:
        if name == "ca_injected" and terms == (APP,):
            return injected
        raise AssertionError(
            f"custom_cacert_pem renders an unexpected lookup {name}{terms}"
        )

    env.globals["lookup"] = lookup
    return env.from_string(VARS["MATOMO_OIDC_GENERAL"]["custom_cacert_pem"]).render(
        application_id=APP, CA_TRUST=CA_TRUST
    )


class TestMatomoTrustsTheInjectedCa(unittest.TestCase):
    def test_an_injected_ca_names_the_injected_bundle(self):
        self.assertEqual(
            _custom_cacert_pem(injected=True),
            CA_TRUST["inject_bundle_container"],
            "Matomo's Http::configCurlCertificate sets CURLOPT_CAINFO to its own "
            "bundled CA file unless [General] custom_cacert_pem names another, and "
            "that overrides the curl.cainfo of the injected php.ini, so RebelOIDC's "
            "token exchange fails on a self-signed issuer",
        )

    def test_without_an_injected_ca_the_key_is_removed(self):
        self.assertEqual(
            _custom_cacert_pem(injected=False),
            "",
            "config_converge.php removes a [General] key whose value is empty, so "
            "Matomo falls back to its bundled CA file instead of a path never mounted",
        )

    def test_the_bundle_is_the_one_the_injection_mounts(self):
        bundle_host = (
            _environment()
            .from_string(CA_TRUST["bundle_host"])
            .render(CA_ROOT={"base_dir": CA_BASE_DIR})
        )
        self.assertEqual(
            PurePosixPath(CA_TRUST["inject_bundle_container"]),
            PurePosixPath(CA_TRUST["inject_cert_container"]).parent
            / PurePosixPath(bundle_host).name,
            "sys-svc-compose-ca mounts the host bundle beside the injected root CA "
            "under the bundle's own file name",
        )

    def test_the_bundle_carries_the_public_roots(self):
        tasks = load_yaml_any(str(CA_ROLE / "tasks" / "00_core.yml"))
        build = next(
            task["ansible.builtin.script"]["cmd"]
            for task in tasks
            if "build-trust-bundle.sh" in str(task.get("ansible.builtin.script", ""))
        )
        env = _environment()
        env.filters["quote"] = shlex.quote
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            own = root / "root-ca.crt"
            own.write_text("OWN CA\n")
            public = root / "ca-certificates.crt"
            public.write_text("PUBLIC ROOTS\n")
            bundle = root / "bundle.pem"
            argv = shlex.split(
                env.from_string(build).render(
                    role_path=str(CA_ROLE),
                    CA_TRUST={"bundle_host": str(bundle)},
                    CA_ROOT={"cert_host": str(own)},
                    _ca_public_bundle=[str(public)],
                )
            )
            subprocess.run(["sh", *argv], check=True, capture_output=True, timeout=30)
            self.assertEqual(
                read_text(str(bundle)),
                "OWN CA\nPUBLIC ROOTS\n",
                "custom_cacert_pem replaces the CA file of every outbound call of "
                "Matomo, so the bundle has to hold the public roots beside the own CA",
            )


if __name__ == "__main__":
    unittest.main()
