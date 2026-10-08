from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str

TEMPLATE_DIR = PROJECT_ROOT / "roles/web-app-prometheus/templates/configuration"
ONION = "a" * 56 + ".onion"

DOMAINS = {
    "web-app-prometheus": [f"prometheus.{ONION}"],
    "web-app-nextcloud": {"nextcloud": f"next.cloud.{ONION}"},
    "web-app-gitea": ["git.infinito.test"],
    "web-svc-cdn": ["cdn.infinito.test"],
    "svc-db-postgres": ["postgres.infinito.test"],
}
ROLES_WITH_THE_PROMETHEUS_SERVICE = ["web-app-nextcloud", "web-app-gitea"]


def lookup(name, *terms, **_kwargs):
    if name == "domains":
        return DOMAINS
    if name == "roles_with_service":
        return [{"id": role} for role in ROLES_WITH_THE_PROMETHEUS_SERVICE]
    if name == "tls":
        term, want = terms
        scheme = "http" if term.endswith(".onion") else "https"
        return {
            "url.base": f"{scheme}://{term}/",
            "protocols.web": "http",
            "enabled": False,
        }[want]
    if name == "domain":
        return DOMAINS[terms[0]][0]
    if name == "scrape_target":
        return f"{terms[1]}:9000"
    if name == "native_metrics_apps":
        return []
    raise AssertionError(f"the template calls an unexpected lookup: {name!r}")


def probed_targets() -> dict[str, list[str]]:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    rendered = env.get_template("prometheus.yml.j2").render(
        lookup=lookup,
        application_id="web-app-prometheus",
        CURRENT_PLAY_APPLICATIONS=list(DOMAINS),
        DOMAIN_PRIMARY="infinito.test",
        ALERT_RULES_CONFIG_DOCKER="/etc/prometheus/alert_rules.yml",
    )
    jobs = {job["job_name"]: job for job in load_yaml_str(rendered)["scrape_configs"]}
    return {
        group["labels"]["app"]: group["targets"]
        for group in jobs["blackbox-healthz"]["static_configs"]
    }


class TestBlackboxTargets(unittest.TestCase):
    def test_an_onion_app_is_probed_under_its_onion_name_over_http(self):
        self.assertEqual(
            probed_targets()["web-app-nextcloud"],
            [f"http://next.cloud.{ONION}/healthz/ready"],
        )

    def test_a_clearnet_app_is_probed_under_its_own_scheme(self):
        self.assertEqual(
            probed_targets()["web-app-gitea"],
            ["https://git.infinito.test/healthz/ready"],
        )

    def test_only_the_roles_the_service_lookup_names_are_probed(self):
        self.assertEqual(set(probed_targets()), set(ROLES_WITH_THE_PROMETHEUS_SERVICE))


if __name__ == "__main__":
    unittest.main()
