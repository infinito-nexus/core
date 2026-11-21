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
STOCK_CFG = "xwiki.authentication.authclass=com.xpn.xwiki.user.impl.xwiki.XWikiAuthServiceImpl\n"
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

    def switch_lines(self, cfg):
        text = cfg.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        prefix = f"{LDAP_SWITCH}="
        return [
            line for line in text.splitlines() if line.lstrip("# ").startswith(prefix)
        ]

    def test_an_ldap_server_turns_the_ldap_authenticator_on_in_both_cfg_copies(self):
        self.start(LDAP_ENV)
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [f"{LDAP_SWITCH}=1"], cfg)

    def test_a_restart_keeps_exactly_one_switch_and_drops_a_stale_one(self):
        for cfg in self.cfgs:
            cfg.write_text(f"{STOCK_CFG}# {LDAP_SWITCH}=1\n{LDAP_SWITCH}=0\n")
        self.start(LDAP_ENV)
        self.start(LDAP_ENV)
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [f"{LDAP_SWITCH}=1"], cfg)

    def test_without_an_ldap_server_the_switch_stays_off(self):
        self.start({})
        for cfg in self.cfgs:
            self.assertEqual(self.switch_lines(cfg), [], cfg)


if __name__ == "__main__":
    unittest.main()
