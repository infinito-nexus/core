from __future__ import annotations

import unittest

from jinja2 import Environment, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.hosts import repo_records
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "dev-nix"
TEMPLATE = ROLE / "templates" / "nix.conf.j2"
INVENTORY = PROJECT_ROOT / "inventories" / "development" / "default.yml"
KEY = "INFINITO_CACHE_PACKAGE_URL"
NEXUS = "http://10.47.0.2:8081"
REPO = "raw-nixos-cache"
UPSTREAM_KEY = "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
FIXED = {
    "SOFTWARE_NAME": "Infinito.Nexus ",
    "dev_nix_ssl_cert_file": "/etc/ssl/certs/ca-certificates.crt",
    "dev_nix_enable_experimental_features": True,
    "dev_nix_experimental_features": ["nix-command", "flakes"],
}


def _package_cache(source: str) -> str:
    if source == "role":
        return load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["nix"]["package_cache"]
    applications = load_yaml(str(INVENTORY))["applications"]
    return applications["dev-nix"]["services"]["nix"]["package_cache"]


def _conf(template: str, environ: dict[str, str], source: str = "inventory") -> str:
    env = Environment(
        keep_trailing_newline=True,
        trim_blocks=True,
        autoescape=select_autoescape(default_for_string=False),
    )

    def lookup(name: str, *terms: str) -> object:
        if name == "env":
            return environ.get(terms[0], "")
        if name == "config":
            return env.from_string(_package_cache(source)).render()
        raise KeyError(name)

    env.globals["lookup"] = lookup
    context: dict[str, object] = dict(FIXED)
    for name, raw in load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN)).items():
        context[name] = env.from_string(str(raw)).render(context)
    return env.from_string(template).render(context)


def _settings(conf: str) -> dict[str, str]:
    return dict(
        (part.strip() for part in line.split("=", 1))
        for line in conf.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _findings(template: str) -> list[str]:
    settings = _settings(_conf(template, {KEY: NEXUS}))
    found = []
    if settings.get("extra-substituters") != f"{NEXUS}/repository/{REPO}":
        found.append("nix does not substitute through the raw-nixos-cache repository")
    if settings.get("trusted-public-keys") != UPSTREAM_KEY:
        found.append(
            "nix does not check the proxied closures with cache.nixos.org's key"
        )
    return found


class TestNixSubstituter(unittest.TestCase):
    def test_with_the_cache_nix_substitutes_through_nexus(self) -> None:
        self.assertEqual(_findings(read_text(str(TEMPLATE))), [])

    def test_the_substituter_names_the_raw_proxy_of_cache_nixos_org(self) -> None:
        self.assertEqual(
            (repo_records()[REPO]["flavor"], repo_records()[REPO]["upstream"]),
            ("raw", "https://cache.nixos.org/"),
        )

    def test_without_the_cache_nix_conf_names_no_substituter(self) -> None:
        settings = _settings(_conf(read_text(str(TEMPLATE)), {}))
        self.assertNotIn("extra-substituters", settings)
        self.assertNotIn("trusted-public-keys", settings)

    def test_any_other_inventory_names_no_substituter(self) -> None:
        settings = _settings(_conf(read_text(str(TEMPLATE)), {KEY: NEXUS}, "role"))
        self.assertNotIn("extra-substituters", settings)

    def test_the_deploy_container_receives_the_nexus_root(self) -> None:
        compose = load_yaml(str(PROJECT_ROOT / "compose.yml"))
        environment = compose["services"]["infinito"]["environment"]
        self.assertEqual(environment[KEY], f"${{{KEY}}}")

    def test_the_guard_reports_a_conf_without_the_substituter(self) -> None:
        template = read_text(str(TEMPLATE))
        start = template.index("{% if DEV_NIX_SUBSTITUTER %}")
        bare = template[:start]
        self.assertEqual(
            _findings(bare),
            [
                "nix does not substitute through the raw-nixos-cache repository",
                "nix does not check the proxied closures with cache.nixos.org's key",
            ],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
