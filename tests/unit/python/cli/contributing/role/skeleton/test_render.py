from __future__ import annotations

import contextlib
import ipaddress
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.build.docs.readme import schema
from cli.build.docs.readme.generate import MANAGED_SECTIONS
from cli.build.docs.readme.sections import h2_titles
from cli.contributing.role.skeleton import render as skeleton
from cli.contributing.role.skeleton.manifest import validate
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_LICENSE,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_PLAYWRIGHT_SPEC,
    ROLE_FILE_README,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)
from utils.software import SOFTWARE_NAME

BASE_FILES = {
    ROLE_FILE_README,
    "files/playwright/.nocheck",
    ROLE_FILE_PLAYWRIGHT_SPEC,
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_LICENSE,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    "tasks/00_core.yml",
    "tasks/utils/stack.yml",
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_TEMPL_COMPOSE,
    "templates/env.j2",
    "templates/playwright.env.j2",
    ROLE_FILE_VARS_MAIN,
}
UNSWEPT_FLAGS = {"docs", "semaphore", "tor", "container_backup"}
STATIC_FILES = {
    ROLE_FILE_README,
    "files/playwright/.nocheck",
    ROLE_FILE_PLAYWRIGHT_SPEC,
    "files/site/style.css",
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_LICENSE,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    "tasks/00_core.yml",
    "tasks/utils/stack.yml",
    ROLE_FILE_TASKS_MAIN,
    "templates/index.html.j2",
    "templates/playwright.env.j2",
    "templates/proxy.conf.j2",
    ROLE_FILE_VARS_MAIN,
}


def _manifest(**overrides):
    data = {
        "name": "notes",
        "description": "Self-hosted note taking web application",
        "homepage": "https://example.org/",
        "license": "MIT",
        "image": "ghcr.io/example/notes:1.2.3",
        "port": 8080,
    }
    data.update(overrides)
    manifest, errors = validate(data)
    if errors:
        raise AssertionError(errors)
    return manifest


def _static(description="Site that turns applications into Infinito.Nexus roles"):
    manifest, errors = validate(
        {
            "kind": "static",
            "name": "builder",
            "description": description,
            "license": "MIT",
        }
    )
    if errors:
        raise AssertionError(errors)
    return manifest


def _full():
    return _manifest(
        database="postgres",
        login="oidc",
        features=["email", "redis"],
        environment={"MODE": "prod"},
        volumes=["/var/lib/notes"],
    )


class _Tree:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.roles = self.root / "roles"
        self.roles.mkdir()
        self.target = self.root / "out"
        self.subnets: list[tuple[str, ipaddress.IPv4Network]] = []

    def role(self, name: str, domains: str = "") -> Path:
        role_dir = self.roles / name
        (role_dir / "meta").mkdir(parents=True)
        if domains:
            (role_dir / ROLE_FILE_META_DOMAINS).write_text(domains, encoding="utf-8")
        return role_dir

    @contextlib.contextmanager
    def active(self):
        with (
            mock.patch.object(
                skeleton,
                "iter_role_dirs",
                side_effect=lambda: sorted(self.roles.iterdir()),
            ),
            mock.patch.object(
                skeleton, "iter_subnets", side_effect=lambda: iter(self.subnets)
            ),
            mock.patch.object(
                skeleton, "suggest_single_ports", return_value=([7990], 0)
            ),
        ):
            yield

    def cleanup(self) -> None:
        self._tmp.cleanup()


class _RenderCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def render(self, manifest, *, force: bool = False) -> Path:
        with self.tree.active():
            return skeleton.render(manifest, self.tree.target, force=force)

    def files(self, manifest) -> dict[str, str]:
        with self.tree.active():
            return skeleton.render_files(
                skeleton.context(manifest, 7990, "192.168.1.0/24")
            )

    def services(self, manifest) -> dict:
        return load_yaml_str(self.files(manifest)[ROLE_FILE_META_SERVICES])


class TestFileSet(_RenderCase):
    def test_a_bare_manifest_renders_the_base_file_set(self):
        role_dir = self.render(_manifest())
        written = {
            path.relative_to(role_dir).as_posix()
            for path in role_dir.rglob("*")  # nocheck: project-walk  tempdir role
            if path.is_file()
        }
        self.assertEqual(BASE_FILES, written)

    def test_volumes_add_the_volumes_file(self):
        self.assertEqual(
            BASE_FILES | {ROLE_FILE_META_VOLUMES},
            set(self.files(_manifest(volumes=["/data"]))),
        )

    def test_the_role_directory_is_named_after_the_manifest(self):
        self.assertEqual(
            self.tree.target / "web-app-cst-notes", self.render(_manifest())
        )

    def test_every_rendered_yaml_file_parses(self):
        for path, text in self.files(_full()).items():
            if path.endswith(".yml"):
                with self.subTest(path=path):
                    load_yaml_str(text)

    def test_the_stack_is_core_s_bridge_and_the_core_tasks_name_no_stack_role(self):
        files = self.files(_full())
        bridge = PROJECT_ROOT / "roles" / "svc-stack" / "files" / "bridge.yml"
        self.assertEqual(files["tasks/utils/stack.yml"], read_text(str(bridge)))
        self.assertEqual(
            load_yaml_str(files["tasks/00_core.yml"]),
            [{"include_tasks": "utils/once/flag.yml"}],
        )


class TestTargets(_RenderCase):
    def test_an_existing_role_directory_is_refused_without_force(self):
        role_dir = self.tree.target / "web-app-cst-notes"
        role_dir.mkdir(parents=True)
        with self.assertRaises(skeleton.RenderError):
            self.render(_manifest())
        self.assertEqual([], list(role_dir.iterdir()))

    def test_force_replaces_an_existing_role_directory(self):
        role_dir = self.tree.target / "web-app-cst-notes"
        role_dir.mkdir(parents=True)
        (role_dir / "stale").write_text("x", encoding="utf-8")
        self.render(_manifest(), force=True)
        self.assertFalse((role_dir / "stale").exists())

    def test_an_entity_collision_names_the_in_tree_role(self):
        self.tree.role("web-app-notes")
        with self.assertRaises(skeleton.RenderError) as raised:
            self.render(_manifest())
        self.assertIn("web-app-notes", raised.exception.errors[0])

    def test_a_domain_collision_names_the_role_serving_it(self):
        self.tree.role("web-app-other", "canonical:\n  - notes.{{ DOMAIN_PRIMARY }}\n")
        with self.assertRaises(skeleton.RenderError) as raised:
            self.render(_manifest())
        self.assertIn("web-app-other", raised.exception.errors[0])

    def test_a_service_key_as_name_is_refused(self):
        with self.assertRaises(skeleton.RenderError):
            self.render(_manifest(name="sso"))

    def test_a_refused_render_writes_nothing(self):
        self.tree.role("web-app-notes")
        with contextlib.suppress(skeleton.RenderError):
            self.render(_manifest())
        self.assertFalse(self.tree.target.exists())


class TestAllocation(_RenderCase):
    def test_the_subnet_skips_every_overlapping_role_subnet(self):
        self.tree.subnets = [
            ("a", ipaddress.IPv4Network("192.168.0.0/24")),
            ("b", ipaddress.IPv4Network("192.168.1.16/28")),
        ]
        with self.tree.active():
            self.assertEqual("192.168.2.0/24", skeleton.allocate_subnet())

    def test_the_port_comes_from_the_port_suggester(self):
        with self.tree.active():
            self.assertEqual(7990, skeleton.allocate_port())

    def test_the_allocated_port_and_subnet_reach_the_role(self):
        role_dir = self.render(_manifest())
        services = load_yaml_any(str(role_dir / ROLE_FILE_META_SERVICES))
        networks = load_yaml_any(str(role_dir / ROLE_FILE_META_NETWORKS))
        self.assertEqual(
            (7990, "192.168.0.0/24"),
            (services["notes"]["ports"]["local"]["http"], networks["local"]["subnet"]),
        )


class TestServices(_RenderCase):
    def test_the_image_version_is_the_literal_manifest_tag(self):
        entity = self.services(_manifest())["notes"]
        self.assertEqual(
            ("ghcr.io/example/notes", "1.2.3"), (entity["image"], entity["version"])
        )

    def test_no_file_uses_the_role_version_lookup(self):
        self.assertFalse(
            any("role_version" in text for text in self.files(_full()).values())
        )

    def test_a_database_is_declared_and_read_through_the_database_lookup(self):
        files = self.files(_manifest(database="mariadb"))
        self.assertIn("mariadb", load_yaml_str(files[ROLE_FILE_META_SERVICES]))
        self.assertIn(
            "lookup('database', application_id, 'password')", files["templates/env.j2"]
        )

    def test_oidc_declares_sso_with_the_oidc_flavor(self):
        self.assertEqual(
            "oidc", self.services(_manifest(login="oidc"))["sso"]["flavor"]
        )

    def test_oidc_passes_the_client_values(self):
        self.assertIn(
            "OIDC.CLIENT.SECRET",
            self.files(_manifest(login="oidc"))["templates/env.j2"],
        )

    def test_ldap_declares_the_ldap_service(self):
        self.assertIn("ldap", self.services(_manifest(login="ldap")))

    def test_no_login_opts_out_of_sso_with_its_nocheck(self):
        text = self.files(_manifest())[ROLE_FILE_META_SERVICES]
        self.assertIn("# nocheck: sso\nsso:\n  enabled: false\n  shared: false\n", text)

    def test_features_declare_the_email_and_redis_services(self):
        services = self.services(_manifest(features=["email", "redis"]))
        self.assertEqual(
            ("{{ 'web-app-email' in group_names }}", True),
            (services["email"]["enabled"], services["redis"]["enabled"]),
        )

    def test_environment_entries_reach_the_env_template(self):
        text = self.files(_manifest(environment={"MODE": 'say "hi"'}))[
            "templates/env.j2"
        ]
        self.assertIn('MODE={{ "say \\"hi\\"" | dotenv_quote }}', text)

    def test_a_volume_is_a_named_volume_and_its_service_stops_for_backup(self):
        files = self.files(_manifest(volumes=["/data"]))
        volumes = load_yaml_str(files[ROLE_FILE_META_VOLUMES])
        services = load_yaml_str(files[ROLE_FILE_META_SERVICES])
        self.assertEqual(
            ("volume", True),
            (volumes["data"]["type"], services["notes"]["backup"]["stop_required"]),
        )

    def test_the_service_key_set_matches_every_rendered_key(self):
        keys = set(self.services(_static())) - {"builder"}
        for manifest in (_full(), _manifest(database="mariadb", login="ldap")):
            keys |= set(self.services(manifest)) - {"notes"}
        self.assertEqual(skeleton.SERVICE_KEYS, keys)


class TestVariants(_RenderCase):
    def test_variant_zero_pins_every_dynamic_flag_true_and_variant_one_false(self):
        files = self.files(_full())
        services = load_yaml_str(files[ROLE_FILE_META_SERVICES])
        variants = load_yaml_str(files[ROLE_FILE_META_VARIANTS])
        dynamic = {
            key
            for key, value in services.items()
            if isinstance(value, dict)
            and "in group_names" in str(value.get("enabled", ""))
            and key not in UNSWEPT_FLAGS
        }
        self.assertEqual(
            (dict.fromkeys(dynamic, True), dict.fromkeys(dynamic, False)),
            tuple(
                {key: variant["services"][key]["enabled"] for key in dynamic}
                for variant in variants
            ),
        )


class TestReadme(_RenderCase):
    def test_the_required_sections_appear_in_template_order(self):
        required = [
            title
            for title in schema.required_sections()
            if title not in MANAGED_SECTIONS
        ]
        titles = h2_titles(self.files(_manifest())["README.md"])
        self.assertEqual(required, [title for title in titles if title in required])

    def test_no_generated_section_is_rendered(self):
        titles = set(h2_titles(self.files(_manifest())["README.md"]))
        self.assertEqual(set(), titles & set(MANAGED_SECTIONS))

    def test_the_review_list_names_every_part_to_check(self):
        text = self.files(_manifest())["README.md"]
        for part in (
            "CSP",
            "RBAC",
            "Application settings",
            "Playwright coverage beyond the baseline",
        ):
            with self.subTest(part=part):
                self.assertIn(f"**{part}:**", text)


class TestStaticKind(_RenderCase):
    def test_a_static_manifest_renders_the_static_file_set_without_allocation(self):
        with mock.patch.object(skeleton, "allocate_port") as port:
            role_dir = self.render(_static())
        written = {
            path.relative_to(role_dir).as_posix()
            for path in role_dir.rglob("*")  # nocheck: project-walk  tempdir role
            if path.is_file()
        }
        self.assertEqual((STATIC_FILES, 0), (written, port.call_count))

    def test_every_rendered_yaml_file_parses(self):
        for path, text in self.files(_static()).items():
            if path.endswith(".yml"):
                with self.subTest(path=path):
                    load_yaml_str(text)

    def test_the_site_is_a_host_mode_vhost_on_the_stack_bridge(self):
        services = self.services(_static())
        self.assertEqual(
            ({"host": {"enabled": True}}, True, True),
            (
                services["builder"]["modes"],
                services["stack"]["enabled"],
                services["openresty"]["enabled"],
            ),
        )

    def test_the_page_links_the_brand_kit_and_pins_design_injection_off(self):
        files = self.files(_static())
        self.assertIn(
            f"lookup('cdn', '{skeleton.BRAND_ROLE}')", files[ROLE_FILE_VARS_MAIN]
        )
        self.assertFalse(
            load_yaml_str(files[ROLE_FILE_META_SERVICES])["design"]["enabled"]
        )

    def test_the_page_renders_header_footer_and_the_brand_nav_on_the_server(self):
        files = self.files(_static())
        page = files["templates/index.html.j2"]
        self.assertIn("'services.brand.nav'", files[ROLE_FILE_VARS_MAIN])
        self.assertEqual(
            (1, 1, 1),
            (
                page.count('<header class="brand-header">'),
                page.count('<footer class="brand-footer">'),
                page.count("{% for app in "),
            ),
        )
        self.assertNotIn("<script>", page)

    def test_the_cosmos_tag_and_sky_are_gated_by_the_design_lookup(self):
        files = self.files(_static())
        page = files["templates/index.html.j2"]
        self.assertIn(
            "BUILDER_COSMOS: \"{{ lookup('design', application_id).cosmos }}\"",
            files[ROLE_FILE_VARS_MAIN],
        )
        self.assertEqual(2, page.count("{% if BUILDER_COSMOS %}"))
        self.assertLess(page.index("{% if BUILDER_COSMOS %}"), page.index("cosmos.js"))

    def test_the_page_writes_the_software_name_through_its_variables(self):
        cases = {
            "Site that turns applications into Infinito.Nexus roles": (
                "{{ SOFTWARE_NAME }}"
            ),
            "Site that hosts the infinito.nexus press kit": "{{ SOFTWARE_DOMAIN }}",
        }
        for description, variable in cases.items():
            with self.subTest(description=description):
                page = self.files(_static(description))["templates/index.html.j2"]
                self.assertEqual(
                    (0, 2),
                    (
                        page.lower().count(SOFTWARE_NAME.lower()),
                        page.count(variable),
                    ),
                )

    def test_the_site_meets_the_web_app_service_contracts(self):
        text = self.files(_static())[ROLE_FILE_META_SERVICES]
        services = load_yaml_str(text)
        self.assertEqual(
            (True, 1, False, False, {"logout", "endpoint", "documentation", "session"}),
            (
                "nocheck: garbage-collector-required" in text.split("\nbuilder:")[0],
                services["builder"]["bond"],
                services["semaphore"]["control"],
                services["prometheus"]["scrape"],
                set(services["sso"]["backchannel"]),
            ),
        )

    def test_no_file_names_the_cosmos_provider_role(self):
        files = self.files(_static())
        self.assertEqual(
            [], [path for path, text in files.items() if "web-app-cst-cosmos" in text]
        )

    def test_the_dynamic_flags_are_swept_by_the_variants(self):
        files = self.files(_static())
        services = load_yaml_str(files[ROLE_FILE_META_SERVICES])
        variants = load_yaml_str(files[ROLE_FILE_META_VARIANTS])
        dynamic = {
            key
            for key, value in services.items()
            if isinstance(value, dict)
            and "in group_names" in str(value.get("enabled", ""))
            and key not in UNSWEPT_FLAGS
        }
        self.assertEqual(
            (dict.fromkeys(dynamic, True), dict.fromkeys(dynamic, False)),
            tuple(
                {key: variant["services"][key]["enabled"] for key in dynamic}
                for variant in variants
            ),
        )

    def test_the_readme_keeps_the_required_sections(self):
        required = [
            title
            for title in schema.required_sections()
            if title not in MANAGED_SECTIONS
        ]
        titles = h2_titles(self.files(_static())["README.md"])
        self.assertEqual(required, [title for title in titles if title in required])


if __name__ == "__main__":
    unittest.main()
