import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

ENTRYPOINT = PROJECT_ROOT / "roles/web-app-xwiki/files/shell/xwiki-entrypoint.sh"
DATA_DIR = "/usr/local/xwiki/data"
WEBAPPS_DIR = "/usr/local/tomcat/webapps"
LDAP_SWITCH = "xwiki.authentication.ldap"
AUTHCLASS = "xwiki.authentication.authclass"
CONTRIB_LDAP_AUTHCLASS = "org.xwiki.contrib.ldap.XWikiLDAPAuthServiceImpl"
LEGACY_LDAP_AUTHCLASS = "com.xpn.xwiki.user.impl.LDAP.XWikiLDAPAuthServiceImpl"
STOCK_CFG = f"# {AUTHCLASS}=com.xpn.xwiki.user.impl.xwiki.XWikiAuthServiceImpl\n"
STUB = "#!/bin/sh\nexit 0\n"
LDAP_ENV = {
    "XWIKI_CFG_LDAP_SERVER": "openldap",
    "XWIKI_CFG_LDAP_PORT": "389",
    "XWIKI_CFG_LDAP_BASE_DN": "dc=example,dc=test",
    "XWIKI_CFG_LDAP_BIND_DN": "cn=reader,dc=example,dc=test",
    "XWIKI_CFG_LDAP_BIND_PASS": "stub",
    "XWIKI_CFG_LDAP_FIELDS_MAPPING": "first_name=givenName",
    "XWIKI_CFG_LDAP_GROUP_MAPPING": "XWiki.XWikiAdminGroup=cn=admins,dc=example,dc=test",
    "XWIKI_CFG_LDAP_TRYLOCAL": "0",
    "XWIKI_CFG_LDAP_UID_ATTR": "uid",
}


class TestXWikiEntrypointLdapSwitch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        source = read_text(str(ENTRYPOINT))
        for literal in (DATA_DIR, WEBAPPS_DIR):
            self.assertIn(literal, source)
        self.script = root / "xwiki-entrypoint.sh"
        source = source.replace(DATA_DIR, str(root / "data"))
        self.script.write_text(source.replace(WEBAPPS_DIR, str(root / "webapps")))
        self.cfgs = (root / "data/xwiki.cfg", root / "webapps/ROOT/WEB-INF/xwiki.cfg")
        for cfg in self.cfgs:
            cfg.parent.mkdir(parents=True)
            cfg.write_text(STOCK_CFG)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker-entrypoint.sh"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "XWIKI_PROPERTIES_SOURCE": str(root / "absent/xwiki.properties"),
        }

    def start(self, env):
        done = subprocess.run(
            ["sh", str(self.script), "xwiki"],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def cfg_lines(self, cfg):
        text = cfg.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return text.splitlines()

    def key_lines(self, cfg, key):
        prefix = f"{key}="
        return [
            line for line in self.cfg_lines(cfg) if line.lstrip("# ").startswith(prefix)
        ]

    def switch_lines(self, cfg):
        return self.key_lines(cfg, LDAP_SWITCH)

    def core_authclass(self, cfg):
        """
        Args:
            cfg: path of the xwiki.cfg copy to read.

        Returns:
            The class XWiki.getAuthServiceClass loads by reflection, or None
            when core hands the choice to security.authentication.authService.
        """
        active = dict(
            line.split("=", 1)
            for line in self.cfg_lines(cfg)
            if "=" in line and not line.startswith("#")
        )
        if active.get(AUTHCLASS):
            return active[AUTHCLASS]
        if active.get(LDAP_SWITCH) == "1":
            return LEGACY_LDAP_AUTHCLASS
        return None

    def test_an_ldap_server_turns_the_ldap_authenticator_on_in_both_cfg_copies(self):
        self.start(LDAP_ENV)
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [f"{LDAP_SWITCH}=1"], cfg)

    def test_an_ldap_server_makes_core_load_the_installed_contrib_authenticator(self):
        self.start(LDAP_ENV)
        for cfg in self.cfgs:
            self.assertEqual(self.core_authclass(cfg), CONTRIB_LDAP_AUTHCLASS, cfg)

    def test_a_restart_keeps_exactly_one_switch_and_drops_a_stale_one(self):
        for cfg in self.cfgs:
            cfg.write_text(f"{STOCK_CFG}# {LDAP_SWITCH}=1\n{LDAP_SWITCH}=0\n")
        self.start(LDAP_ENV)
        self.start(LDAP_ENV)
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [f"{LDAP_SWITCH}=1"], cfg)
            self.assertEqual(
                self.key_lines(cfg, AUTHCLASS),
                [f"{AUTHCLASS}={CONTRIB_LDAP_AUTHCLASS}"],
                cfg,
            )

    def test_leaving_ldap_hands_the_choice_back_to_the_auth_service_property(self):
        self.start(LDAP_ENV)
        self.start({})
        for cfg in self.cfgs:
            self.assertIsNone(self.core_authclass(cfg), cfg)
            self.assertEqual(self.switch_lines(cfg), [], cfg)
            self.assertEqual(self.key_lines(cfg, AUTHCLASS), [], cfg)

    def test_without_an_ldap_server_the_switch_stays_off(self):
        self.start({})
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [], cfg)
            self.assertIsNone(self.core_authclass(cfg), cfg)


if __name__ == "__main__":
    unittest.main()
