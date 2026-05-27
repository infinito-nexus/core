"""Unit tests for `utils.cleanup.nginx_vhosts`."""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import utils.cleanup.nginx_vhosts as mod
from utils.cache.yaml import _reset_cache_for_tests, dump_yaml
from utils.cleanup.nginx_vhosts import (
    iter_vhost_files_for_entity,
    main,
    purge_vhost_files_for_entities,
)
from utils.roles.mapping import ROLE_FILE_META_SERVER, ROLE_FILE_VARS_MAIN


class NginxVhostsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self.tmp = Path(tempfile.mkdtemp(prefix="nginx_vhosts_test_"))

        # Roles tree (with categories.yml so `get_entity_name` resolves).
        self.roles_dir = self.tmp / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        dump_yaml(
            self.roles_dir / "categories.yml",
            {
                "roles": {
                    "web": {
                        "app": {"title": "Applications", "invokable": True},
                        "svc": {"title": "Services", "invokable": True},
                    }
                }
            },
        )

        # Fake nginx tree: /etc/nginx/conf.d/servers/{http,https}/
        self.nginx_dir = self.tmp / "etc-nginx"
        self.servers_dir = self.nginx_dir / "conf.d" / "servers"
        (self.servers_dir / "http").mkdir(parents=True, exist_ok=True)
        (self.servers_dir / "https").mkdir(parents=True, exist_ok=True)

        # categories.yml resolution leans on cwd → pin it to the tmp tree.
        self._cwd = Path.cwd()
        os.chdir(self.tmp)
        self.addCleanup(lambda: os.chdir(self._cwd))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _mk_role(
        self,
        name: str,
        *,
        application_id: str,
        canonical: list[str],
        aliases: list[str] | None = None,
    ) -> None:
        rd = self.roles_dir / name
        (rd / "vars").mkdir(parents=True, exist_ok=True)
        (rd / "meta").mkdir(parents=True, exist_ok=True)
        dump_yaml(rd / ROLE_FILE_VARS_MAIN, {"application_id": application_id})
        domains_block: dict = {"canonical": canonical}
        if aliases is not None:
            domains_block["aliases"] = aliases
        dump_yaml(
            rd / ROLE_FILE_META_SERVER,
            {"domains": domains_block},
        )

    def _touch_vhost(self, domain: str, protocol: str = "https") -> Path:
        f = self.servers_dir / protocol / f"{domain}.conf"
        f.write_text("# fake vhost\n", encoding="utf-8")
        return f


class TestIterVhostFiles(NginxVhostsTestBase, unittest.TestCase):
    def test_yields_existing_files_only(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
        )
        existing = self._touch_vhost("matomo.infinito.example", "https")
        # http variant intentionally absent on disk

        got = list(
            iter_vhost_files_for_entity(
                "matomo",
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(got, [existing])

    def test_includes_aliases(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
            aliases=["stats.infinito.example"],
        )
        f1 = self._touch_vhost("matomo.infinito.example", "https")
        f2 = self._touch_vhost("stats.infinito.example", "https")

        got = sorted(
            iter_vhost_files_for_entity(
                "matomo",
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(got, sorted([f1, f2]))

    def test_unknown_entity_is_empty(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
        )
        self._touch_vhost("matomo.infinito.example", "https")

        got = list(
            iter_vhost_files_for_entity(
                "no-such-entity",
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(got, [])

    def test_yields_www_redirect_variant(self) -> None:
        self._mk_role(
            "web-svc-cdn",
            application_id="web-svc-cdn",
            canonical=["cdn.infinito.example"],
        )
        bare = self._touch_vhost("cdn.infinito.example", "https")
        redirect = self._touch_vhost("www.cdn.infinito.example", "https")

        got = sorted(
            iter_vhost_files_for_entity(
                "cdn",
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(got, sorted([bare, redirect]))

    def test_www_prefixed_domain_not_double_prefixed(self) -> None:
        self._mk_role(
            "web-opt-rdr-www",
            application_id="web-opt-rdr-www",
            canonical=["www.w3redirect.infinito.example"],
        )
        existing = self._touch_vhost("www.w3redirect.infinito.example", "https")
        self._touch_vhost("www.www.w3redirect.infinito.example", "https")

        got = list(
            iter_vhost_files_for_entity(
                "opt-rdr-www",
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(got, [existing])


class TestPurgeVhostFiles(NginxVhostsTestBase, unittest.TestCase):
    def test_removes_only_matching_vhosts(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
        )
        self._mk_role(
            "web-app-dashboard",
            application_id="web-app-dashboard",
            canonical=["dashboard.infinito.example"],
        )

        matomo_https = self._touch_vhost("matomo.infinito.example", "https")
        dashboard_https = self._touch_vhost("dashboard.infinito.example", "https")
        unrelated = self._touch_vhost("unrelated.infinito.example", "https")

        removed = purge_vhost_files_for_entities(
            ["dashboard"],
            nginx_dir=self.nginx_dir,
            domain_primary="infinito.example",
            roles_dir=self.roles_dir,
        )

        self.assertEqual(removed, [dashboard_https])
        self.assertFalse(dashboard_https.exists())
        self.assertTrue(matomo_https.exists())
        self.assertTrue(unrelated.exists())

    def test_no_match_returns_empty(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
        )
        # No vhost files placed on disk.

        removed = purge_vhost_files_for_entities(
            ["matomo"],
            nginx_dir=self.nginx_dir,
            domain_primary="infinito.example",
            roles_dir=self.roles_dir,
        )
        self.assertEqual(removed, [])

    def test_removes_www_redirect_variant(self) -> None:
        self._mk_role(
            "web-svc-cdn",
            application_id="web-svc-cdn",
            canonical=["cdn.infinito.example"],
        )
        bare = self._touch_vhost("cdn.infinito.example", "https")
        redirect = self._touch_vhost("www.cdn.infinito.example", "https")
        unrelated = self._touch_vhost("www.unrelated.infinito.example", "https")

        removed = sorted(
            purge_vhost_files_for_entities(
                ["cdn"],
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )

        self.assertEqual(removed, sorted([bare, redirect]))
        self.assertFalse(bare.exists())
        self.assertFalse(redirect.exists())
        self.assertTrue(unrelated.exists())

    def test_multiple_entities_in_one_call(self) -> None:
        self._mk_role(
            "web-app-matomo",
            application_id="web-app-matomo",
            canonical=["matomo.infinito.example"],
        )
        self._mk_role(
            "web-app-dashboard",
            application_id="web-app-dashboard",
            canonical=["dashboard.infinito.example"],
        )

        matomo_https = self._touch_vhost("matomo.infinito.example", "https")
        dashboard_https = self._touch_vhost("dashboard.infinito.example", "https")

        removed = sorted(
            purge_vhost_files_for_entities(
                ["matomo", "dashboard"],
                nginx_dir=self.nginx_dir,
                domain_primary="infinito.example",
                roles_dir=self.roles_dir,
            )
        )
        self.assertEqual(removed, sorted([matomo_https, dashboard_https]))
        self.assertFalse(matomo_https.exists())
        self.assertFalse(dashboard_https.exists())


class TestMainShim(NginxVhostsTestBase, unittest.TestCase):
    def test_no_argv_prints_usage_and_returns_2(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            rc = main([])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", stderr.getvalue())

    def test_main_reports_noop_when_nothing_to_remove(self) -> None:
        stdout = io.StringIO()
        # No roles, no vhost files — main MUST still return 0 with a no-op message.
        with patch.object(mod, "ROLES_DIR", self.roles_dir), redirect_stdout(stdout):
            rc = main(["nonexistent"])
        self.assertEqual(rc, 0)
        self.assertIn("No nginx vhost files to remove", stdout.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
