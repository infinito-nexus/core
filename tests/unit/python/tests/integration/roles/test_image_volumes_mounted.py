"""The volume sweep is only as good as the service key it attributes a mount to.

``meta/services.yml`` declares an image under a key that is not always the
compose service running it, so a sweep comparing a mount's ``service`` against
the declaring key reports a role that mounts the path under its real name as a
gap. Every such miss looks exactly like a genuinely unmounted ``VOLUME``, and
the sweep itself cannot run without a mirror, so the attribution is pinned
here instead.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

from tests.integration.roles import test_image_volumes_mounted as sweep
from utils.cache import PROJECT_ROOT
from utils.roles.applications.services.database import RDBMS_SERVICE_KEYS
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES

SERVICES = ROLE_FILE_META_SERVICES.split("/")[-1]
VOLUMES = ROLE_FILE_META_VOLUMES.split("/")[-1]

MISATTRIBUTED = (
    ("web-app-erpnext", "erpnext", "/home/frappe/frappe-bench/sites"),
    ("web-app-erpnext", "erpnext", "/home/frappe/frappe-bench/logs"),
    ("web-app-jitsi", "jitsi", "/config"),
    ("web-app-jitsi", "jitsi", "/usr/share/jitsi-meet/transcripts"),
    ("web-app-magento", "mariadb", "/var/lib/mysql"),
    ("web-app-stalwart", "postgres", "/var/lib/postgresql"),
    ("web-svc-xmpp", "xmpp", "/opt/ejabberd"),
)


def _mounts(*pairs: tuple[str, str]) -> dict:
    return {
        f"volume{number}": {
            "mounts": [{"service": service, "target": target}],
        }
        for number, (service, target) in enumerate(pairs)
    }


class _Tree:
    """Serve ``meta/*.yml`` from a ``{(role, file name): document}`` mapping."""

    def serve(self, tree: dict) -> mock._patch:
        def _load(path):
            return tree.get((path.parent.parent.name, path.name), {})

        return mock.patch.object(sweep, "load_yaml", side_effect=_load)


class TestServiceKeys(_Tree, unittest.TestCase):
    def test_an_entry_without_a_proxy_is_only_its_own_key(self) -> None:
        with self.serve({("role", SERVICES): {"app": {"image": "app"}}}):
            self.assertEqual(sweep.service_keys("role", "app"), {"app"})

    def test_a_proxy_service_key_joins_the_entry_key(self) -> None:
        tree = {("role", SERVICES): {"app": {"proxy": {"service_key": "nginx"}}}}
        with self.serve(tree):
            self.assertEqual(sweep.service_keys("role", "app"), {"app", "nginx"})

    def test_a_templated_service_key_leaves_only_the_entry_key(self) -> None:
        templated = "{{ 'synapse' if flavor == 'compose' else 'matrix' }}"
        tree = {("role", SERVICES): {"app": {"proxy": {"service_key": templated}}}}
        with self.serve(tree):
            self.assertEqual(sweep.service_keys("role", "app"), {"app"})

    def test_an_undeclared_entry_is_its_own_key(self) -> None:
        with self.serve({}):
            self.assertEqual(sweep.service_keys("role", "app"), {"app"})


class TestMountTargets(_Tree, unittest.TestCase):
    def test_a_mount_on_another_service_is_not_read(self) -> None:
        tree = {("role", VOLUMES): _mounts(("app", "/data"), ("other", "/elsewhere"))}
        with self.serve(tree):
            self.assertEqual(sweep.mount_targets("role", {"app"}), {"/data"})

    def test_every_named_service_contributes(self) -> None:
        tree = {("role", VOLUMES): _mounts(("app", "/data"), ("nginx", "/www"))}
        with self.serve(tree):
            self.assertEqual(
                sweep.mount_targets("role", {"app", "nginx"}), {"/data", "/www"}
            )

    def test_a_trailing_slash_is_normalised_away(self) -> None:
        with self.serve({("role", VOLUMES): _mounts(("app", "/data/"))}):
            self.assertEqual(sweep.mount_targets("role", {"app"}), {"/data"})

    def test_the_root_mount_survives_normalisation(self) -> None:
        with self.serve({("role", VOLUMES): _mounts(("app", "/"))}):
            self.assertEqual(sweep.mount_targets("role", {"app"}), {"/"})

    def test_a_mount_without_a_string_target_is_skipped(self) -> None:
        tree = {("role", VOLUMES): {"broken": {"mounts": [{"service": "app"}, "x"]}}}
        with self.serve(tree):
            self.assertEqual(sweep.mount_targets("role", {"app"}), set())


class TestDeclaredTargets(_Tree, unittest.TestCase):
    def test_a_mount_under_the_proxy_service_key_is_found(self) -> None:
        tree = {
            ("role", SERVICES): {"app": {"proxy": {"service_key": "web"}}},
            ("role", VOLUMES): _mounts(("web", "/config")),
        }
        with self.serve(tree):
            self.assertEqual(sweep.declared_targets("role", "app"), {"/config"})

    def test_the_entry_key_and_the_proxy_key_both_contribute(self) -> None:
        tree = {
            ("role", SERVICES): {"app": {"proxy": {"service_key": "nginx"}}},
            ("role", VOLUMES): _mounts(("app", "/data"), ("nginx", "/www")),
        }
        with self.serve(tree):
            self.assertEqual(sweep.declared_targets("role", "app"), {"/data", "/www"})

    def test_an_rdbms_key_reads_its_provider_role(self) -> None:
        tree = {("svc-db-mariadb", VOLUMES): _mounts(("mariadb", "/var/lib/mysql"))}
        with self.serve(tree):
            self.assertEqual(
                sweep.declared_targets("role", "mariadb"), {"/var/lib/mysql"}
            )

    def test_the_provider_widens_rather_than_replaces(self) -> None:
        tree = {
            ("role", VOLUMES): _mounts(("postgres", "/etc/postgres.conf")),
            ("svc-db-postgres", VOLUMES): _mounts(("postgres", "/var/lib/postgresql")),
        }
        with self.serve(tree):
            self.assertEqual(
                sweep.declared_targets("role", "postgres"),
                {"/etc/postgres.conf", "/var/lib/postgresql"},
            )

    def test_a_key_that_names_no_engine_reaches_no_provider(self) -> None:
        tree = {("svc-db-mariadb", VOLUMES): _mounts(("mariadb", "/var/lib/mysql"))}
        with self.serve(tree):
            self.assertEqual(sweep.declared_targets("role", "redis"), set())


class TestProviderRoles(unittest.TestCase):
    def test_every_engine_key_names_a_role_that_exists(self) -> None:
        self.assertEqual(set(sweep.RDBMS_PROVIDERS), set(RDBMS_SERVICE_KEYS))
        missing = [
            provider
            for provider in sweep.RDBMS_PROVIDERS.values()
            if not (
                PROJECT_ROOT / "roles" / provider / ROLE_FILE_META_VOLUMES
            ).is_file()
        ]
        self.assertEqual(missing, [], "no such provider role declares the mounts")


class TestRepositoryAttribution(unittest.TestCase):
    """The sweep skips without a mirror, so the repository side is pinned here."""

    def test_the_formerly_misattributed_entries_resolve(self) -> None:
        unresolved = [
            f"{role}:{service} {target}"
            for role, service, target in MISATTRIBUTED
            if target not in sweep.declared_targets(role, service)
        ]
        self.assertEqual(
            unresolved,
            [],
            "the image declares this path as a VOLUME and the role mounts it, "
            "so a sweep reporting it would be reporting its own attribution",
        )


if __name__ == "__main__":
    unittest.main()
