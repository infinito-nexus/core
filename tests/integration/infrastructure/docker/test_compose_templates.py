import re
import unittest
from typing import ClassVar

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

_UNSET = object()


class TestDockerComposeTemplates(unittest.TestCase):
    TEMPLATE_PATTERN = f"roles/*/{ROLE_FILE_TEMPL_COMPOSE}"

    ALLOWED_BEFORE_BASE: ClassVar[list[re.Pattern]] = [
        re.compile(r"^\s*$"),
        re.compile(r"^\s*version:.*$"),
        re.compile(r"^\s*#.*$"),
        re.compile(r"^\s*\{\#.*\#\}\s*$"),
    ]

    BASE_INCLUDE = "{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}"
    NET_INCLUDE = "{{ lookup('compose_networks') }}"
    NET_INCLUDE_RE: ClassVar[re.Pattern] = re.compile(
        r"\{\{\s*lookup\(\s*'compose_networks'[^)]*\)\s*\}\}"
    )
    HOST_MODE = 'network_mode: "host"'

    def test_docker_compose_includes(self):
        """
        Verifies for each found compose.yml.j2:
        1. BASE_INCLUDE is present exactly once
        2. If no host‑mode is set, NET_INCLUDE must appear exactly once
        3. BASE_INCLUDE appears before NET_INCLUDE when both are required
        4. Only allowed lines appear before BASE_INCLUDE (invalid lines issue warnings)
        """
        template_paths = sorted(PROJECT_ROOT.glob(self.TEMPLATE_PATTERN))
        self.assertTrue(
            template_paths, f"No templates found for pattern {self.TEMPLATE_PATTERN}"
        )

        for template_path in template_paths:
            with self.subTest(template=template_path):
                content = read_text(str(template_path))
                lines = content.splitlines()

                count_base = lines.count(self.BASE_INCLUDE)
                self.assertEqual(
                    count_base,
                    1,
                    f"{template_path}: '{self.BASE_INCLUDE}' occurs {count_base} times, expected once",
                )

                host_mode = self.HOST_MODE in content

                count_net = sum(1 for line in lines if self.NET_INCLUDE_RE.search(line))
                if host_mode:
                    self.assertLessEqual(
                        count_net,
                        1,
                        f"{template_path}: '{self.NET_INCLUDE}' occurs {count_net} times with host networking, expected 0 or 1",
                    )
                else:
                    self.assertEqual(
                        count_net,
                        1,
                        f"{template_path}: '{self.NET_INCLUDE}' occurs {count_net} times, expected once",
                    )

                if count_base and count_net:
                    idx_base = lines.index(self.BASE_INCLUDE)
                    idx_net = next(
                        i
                        for i, line in enumerate(lines)
                        if self.NET_INCLUDE_RE.search(line)
                    )
                    self.assertLess(
                        idx_base,
                        idx_net,
                        f"{template_path}: '{self.BASE_INCLUDE}' must come before '{self.NET_INCLUDE}'",
                    )


class TestServiceJournaldTag(unittest.TestCase):
    APPLICATION_ID = "web-app-pixelfed"
    MODES = ("compose", "swarm")
    SERVICE_BASE_INCLUDE = (
        "{% include 'roles/sys-svc-container/templates/base.yml.j2' %}"
    )
    SERVICE_NAME_RE: ClassVar[re.Pattern] = re.compile(r"\{%\s*set\s+service_name\s*=")
    TEMPLATES: ClassVar[dict[str, tuple[str, str]]] = {
        "roles/sys-svc-container/templates/base.yml.j2": ("services:\n  svc:\n", "svc"),
        "roles/svc-db-redis/templates/service.yml.j2": ("services:\n", "redis"),
        "roles/sys-svc-rdbms/templates/services/mariadb.yml.j2": (
            "services:\n",
            "database",
        ),
    }

    def _render_logging(self, template, mode, wazuh_enabled):
        env = Environment(
            loader=ChoiceLoader(
                [
                    DictLoader(
                        {
                            "roles/sys-svc-container/templates/resource.yml.j2": "",
                            "roles/sys-svc-container/templates/deploy.yml.j2": "",
                        }
                    ),
                    FileSystemLoader(str(PROJECT_ROOT)),
                ]
            ),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["has_env"] = lambda _app: False
        env.filters["get_entity_name"] = get_entity_name

        def _lookup(name, *args, **_kwargs):
            if name == "config":
                self.assertEqual(
                    args[:2], (self.APPLICATION_ID, "services.wazuh.enabled")
                )
                return args[2] if wazuh_enabled is _UNSET else wazuh_enabled
            if name == "database":
                return {"local": True, "host": "database"}.get(args[1], "x")
            return ""

        env.globals["lookup"] = _lookup
        rendered = env.get_template(template).render(
            application_id=self.APPLICATION_ID,
            DEPLOYMENT_MODE=mode,
            DOCKER_RESTART_POLICY="unless-stopped",
        )
        prefix, key = self.TEMPLATES[template]
        return load_yaml_str(f"{prefix}{rendered}")["services"][key]["logging"]

    def test_logging_is_plain_journald_without_wazuh_opt_in(self):
        for template in self.TEMPLATES:
            for mode in self.MODES:
                for flag in (_UNSET, False):
                    with self.subTest(template=template, mode=mode, wazuh_enabled=flag):
                        self.assertEqual(
                            self._render_logging(template, mode, flag),
                            {"driver": "journald"},
                        )

    def test_wazuh_opt_in_tags_journald_with_entity_name(self):
        for template in self.TEMPLATES:
            for mode in self.MODES:
                with self.subTest(template=template, mode=mode):
                    self.assertEqual(
                        self._render_logging(template, mode, True),
                        {"driver": "journald", "options": {"tag": "pixelfed"}},
                    )

    def test_sidecar_logging_blocks_match_the_service_base(self):
        blocks = {}
        for template in self.TEMPLATES:
            lines = read_text(str(PROJECT_ROOT / template)).splitlines()
            start = lines.index("    logging:")
            end = lines.index("{% endif %}", start)
            blocks[template] = lines[start : end + 1]
        base, *sidecars = self.TEMPLATES
        for sidecar in sidecars:
            with self.subTest(template=sidecar):
                self.assertEqual(blocks[sidecar], blocks[base])

    def test_all_templates_render_the_same_logging(self):
        for mode in self.MODES:
            for flag in (_UNSET, False, True):
                with self.subTest(mode=mode, wazuh_enabled=flag):
                    rendered = [
                        self._render_logging(template, mode, flag)
                        for template in self.TEMPLATES
                    ]
                    self.assertTrue(all(r == rendered[0] for r in rendered), rendered)

    def test_every_service_of_an_opted_in_role_includes_the_service_base(self):
        opted_in = []
        for services_path in sorted(
            PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_SERVICES}")
        ):
            role = services_path.parent.parent.name
            wazuh = (load_yaml_str(read_text(str(services_path))) or {}).get("wazuh")
            if get_entity_name(role) == "wazuh" or not isinstance(wazuh, dict):
                continue
            if wazuh.get("enabled") is not True:
                continue
            opted_in.append(role)
            template = read_text(
                str(PROJECT_ROOT / "roles" / role / ROLE_FILE_TEMPL_COMPOSE)
            )
            with self.subTest(role=role):
                self.assertEqual(
                    template.count(self.SERVICE_BASE_INCLUDE),
                    len(self.SERVICE_NAME_RE.findall(template)),
                    f"{role}: every service block must include the service base, "
                    "so its journald tag is set",
                )
        self.assertIn(self.APPLICATION_ID, opted_in)


if __name__ == "__main__":
    unittest.main()
