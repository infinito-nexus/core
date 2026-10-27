import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-wazuh/files/shell/certs-entrypoint.sh"
TOOL_VERSION = "4.14"
NODES = ("wazuh.indexer", "wazuh.manager", "wazuh.dashboard")
CERTS_YML = "nodes:\n" + "".join(
    f"  {group}:\n    - name: {node}\n      ip: {node}\n"
    for group, node in zip(("indexer", "server", "dashboard"), NODES, strict=True)
)
CURL_STUB = "#!/usr/bin/env bash\necho curl-called >&2\nexit 22\n"


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def issue(out, name, ca, days):
    """Write <name>.pem and <name>-key.pem signed by the CA at <ca>.pem/<ca>.key.

    Args:
        out: directory the certificates live in.
        name: file stem of the issued certificate.
        ca: file stem of the signing CA.
        days: validity of the issued certificate.
    """
    key = out / f"{name}-key.pem"
    csr = out / f"{name}.csr"
    openssl(
        "genpkey",
        "-algorithm",
        "EC",
        "-pkeyopt",
        "ec_paramgen_curve:prime256v1",
        "-out",
        str(key),
    )
    openssl("req", "-new", "-key", str(key), "-subj", f"/CN={name}", "-out", str(csr))
    openssl(
        "x509",
        "-req",
        "-in",
        str(csr),
        "-CA",
        str(out / f"{ca}.pem"),
        "-CAkey",
        str(out / f"{ca}.key"),
        "-CAcreateserial",
        "-days",
        str(days),
        "-out",
        str(out / f"{name}.pem"),
    )
    csr.unlink()


class TestCertsEntrypoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / "certificates"
        self.out.mkdir()
        self.config = root / "certs.yml"
        self.config.write_text(CERTS_YML)
        self.stub = root / "bin"
        self.stub.mkdir()
        (self.stub / "curl").write_text(CURL_STUB)
        (self.stub / "curl").chmod(0o755)
        openssl(
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(self.out / "root-ca.key"),
            "-out",
            str(self.out / "root-ca.pem"),
            "-subj",
            "/CN=root-ca",
            "-days",
            "3650",
        )
        for suffix in ("pem", "key"):
            shutil.copyfile(
                self.out / f"root-ca.{suffix}", self.out / f"root-ca-manager.{suffix}"
            )
        for name in ("admin", *NODES):
            issue(self.out, name, "root-ca", 365)
        digest = hashlib.sha256(CERTS_YML.encode()).hexdigest()
        (self.out / ".certs.sha256").write_text(f"{digest} {TOOL_VERSION}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_entrypoint(self):
        env = dict(os.environ)
        env.update(
            PATH=f"{self.stub}{os.pathsep}{env['PATH']}",
            CERT_TOOL_VERSION=TOOL_VERSION,
            WAZUH_MANAGER_NODE="wazuh.manager",
            CERTS_CONFIG=str(self.config),
            CERTS_OUT_DIR=str(self.out),
            CERTS_MIN_VALID_DAYS="30",
        )
        return subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
        )

    def assert_regenerates(self, reason):
        result = self.run_entrypoint()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"Regenerating Wazuh certificates: {reason}", result.stdout)
        self.assertIn("curl-called", result.stderr)

    def test_current_certs_are_kept(self):
        result = self.run_entrypoint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("are current; skipping generation", result.stdout)
        self.assertNotIn("curl-called", result.stderr)

    def test_missing_marker_regenerates(self):
        (self.out / ".certs.sha256").unlink()
        self.assert_regenerates("the certs config or the tool version changed")

    def test_changed_config_regenerates(self):
        self.config.write_text(CERTS_YML + "  extra: true\n")
        self.assert_regenerates("the certs config or the tool version changed")

    def test_changed_tool_version_regenerates(self):
        (self.out / ".certs.sha256").write_text("0" * 64 + " 4.13\n")
        self.assert_regenerates("the certs config or the tool version changed")

    def test_missing_key_regenerates(self):
        (self.out / "wazuh.manager-key.pem").unlink()
        self.assert_regenerates(
            "wazuh.manager.pem or wazuh.manager-key.pem is missing or empty"
        )

    def test_missing_ca_key_regenerates(self):
        (self.out / "root-ca-manager.key").unlink()
        self.assert_regenerates(
            "root-ca-manager.pem or root-ca-manager.key is missing or empty"
        )

    def test_expiring_cert_regenerates(self):
        issue(self.out, "wazuh.indexer", "root-ca", 10)
        self.assert_regenerates("wazuh.indexer.pem expires within 30 days")

    def test_mismatched_key_regenerates(self):
        shutil.copyfile(
            self.out / "wazuh.dashboard-key.pem", self.out / "admin-key.pem"
        )
        self.assert_regenerates("admin-key.pem does not match admin.pem")

    def test_cert_from_another_ca_regenerates(self):
        openssl(
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(self.out / "other-ca.key"),
            "-out",
            str(self.out / "other-ca.pem"),
            "-subj",
            "/CN=other",
            "-days",
            "3650",
        )
        issue(self.out, "wazuh.dashboard", "other-ca", 365)
        self.assert_regenerates(
            "wazuh.dashboard.pem does not verify against root-ca.pem"
        )


if __name__ == "__main__":
    unittest.main()
