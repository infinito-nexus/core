from __future__ import annotations

import io
import json
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from utils.cache.files import PROJECT_ROOT

HELPER = PROJECT_ROOT / "roles/web-app-semaphore/files/python/release/host.py"
GUARD = PROJECT_ROOT / "roles/web-app-semaphore/files/python/lockout_guard.py"
LOGIN = "admin"
ACCOUNTS = (LOGIN, "root", "app-control", "backup")
DIGEST = "/etc/infinito.nexus/federation.sha256"


def load(path, name):
    """Args:
    path: a helper file.
    name: the module name.

    Returns:
        The loaded module.
    """
    spec = spec_from_file_location(name, str(path))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def public_key():
    """Returns:
    A fresh ``<type> <base64>`` public key line.
    """
    return (
        ed25519.Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
    )


def blob(line):
    """Args:
    line: a ``<type> <base64>`` public key line.

    Returns:
        Its ``(type, base64)``.
    """
    key_type, data = line.split()[:2]
    return key_type, data


class ReleaseHost:
    """Args:
    case: the running test case; the scratch host closes with it.
    """

    def __init__(self, case):
        scratch = tempfile.TemporaryDirectory()
        case.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.sudoers = self.root / "sudoers.d"
        self.sudoers.mkdir()
        for user in ACCOUNTS:
            (self.root / user / ".ssh").mkdir(parents=True)

    def home(self, user):
        directory = self.root / user
        return str(directory) if directory.is_dir() else None

    def keys(self, user):
        return self.root / user / ".ssh" / "authorized_keys"

    def write(self, path, lines, mode=0o600):
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        path.chmod(mode)

    def snapshot(self):
        """Returns:
        ``{path: (bytes, mode)}`` of every file of the scratch host.
        """
        snapshot = {}
        for path in sorted(self.root.rglob("*")):  # nocheck: project-walk tempdir host
            if path.is_file():
                body = path.read_bytes()  # nocheck: cache-read tempdir
                snapshot[str(path)] = (body, path.stat().st_mode)
        return snapshot


class ReleaseHostTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(HELPER, "release_host")
        self.host = ReleaseHost(self)
        self.agent = public_key()
        self.customer = public_key()
        self.other = public_key()
        self.second = public_key()
        self.agent_blob = self.agent.split()[1]

    def release(self, login=LOGIN):
        stdout = io.StringIO()
        arguments = self.mod.parser().parse_args(
            [
                "apply",
                "--login",
                login,
                "--app-control-user",
                "app-control",
                "--backup-user",
                "backup",
                "--agent-key",
                *blob(self.agent),
                "--federation-digest",
                DIGEST,
                "--monitoring",
            ]
        )
        code = self.mod.release(
            arguments,
            stdout,
            self.host.home,
            str(self.host.sudoers),
            self.mod.keygen_accepts,
            self.mod.Monitoring(self.host.root / "rootfs", arguments.federation_digest),
        )
        return code, json.loads(stdout.getvalue().splitlines()[-1])

    def quoted_customer_line(self):
        return (
            f'command="/bin/echo {self.agent} ",restrict,from="192.0.2.0/24" '
            f"{self.customer} customer@laptop"
        )

    def plant_platform(self, login_lines):
        self.host.write(self.host.keys(LOGIN), login_lines)
        self.host.write(
            self.host.keys("root"),
            [f"{self.agent} workspace", f'restrict,command="uptime" {self.other} ops'],
        )
        self.host.write(
            self.host.keys("app-control"),
            [f'restrict,command="/usr/bin/app-control ssh" {self.other} app-control'],
            0o644,
        )
        self.host.write(self.host.sudoers / "app-control", ["app-control ALL=(root)"])
        self.host.write(self.host.sudoers / "backup", ["backup ALL=(root) NOPASSWD:"])
        self.host.write(
            self.host.keys("backup"),
            [f'command="/home/backup/ssh-wrapper.sh" {self.other} backup'],
        )

    def test_release_drops_every_platform_key_and_keeps_the_customer_keys(self):
        quoted = self.quoted_customer_line()
        desk = f'from="203.0.113.0/24" {self.second} customer@desk'
        self.plant_platform(
            [
                f'from="198.51.100.7",restrict {self.agent} workspace',
                "# the customer's own keys",
                quoted,
                desk,
            ]
        )
        code, result = self.release()
        self.assertEqual(code, 0)
        self.assertEqual(
            result,
            {
                "kept": 1,
                "removed": {
                    "agent_keys": 2,
                    "app_control_keys": 1,
                    "app_control_sudoers": 1,
                    "backup_keys": 1,
                    "backup_sudoers": 1,
                    "federation_token": 0,
                    "monitoring_agent": 0,
                    "monitoring_key": 0,
                },
            },
        )
        self.assertEqual(
            self.host.keys(LOGIN).read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            ),
            f"# the customer's own keys\n{quoted}\n{desk}\n",
        )
        self.assertFalse((self.host.sudoers / "backup").exists())
        self.assertEqual(
            self.host.keys("root").read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            ),
            f'restrict,command="uptime" {self.other} ops\n',
        )
        self.assertFalse(self.host.keys("app-control").exists())
        self.assertFalse((self.host.sudoers / "app-control").exists())
        self.assertEqual(
            self.host.keys("backup").read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            ),
            "",
        )
        for user in (LOGIN, "root", "backup"):
            with self.subTest(user=user):
                self.assertEqual(self.host.keys(user).stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            sorted(p.name for p in self.host.keys(LOGIN).parent.iterdir()),
            ["authorized_keys"],
        )

    def test_release_refuses_before_any_write_when_no_customer_key_remains(self):
        cases = {
            "agent key only": [f"{self.agent} workspace"],
            "a broken key": [f"{self.agent} workspace", "ssh-ed25519 notakey x"],
            "an unterminated quote": [
                f"{self.agent} workspace",
                f'command="echo {self.customer}',
            ],
            "a forced command only": [
                f"{self.agent} workspace",
                self.quoted_customer_line(),
            ],
            "restrict only": [f"{self.agent} workspace", f"restrict {self.customer}"],
            "an upper-case Command only": [
                f"{self.agent} workspace",
                f'from="a,b",Command="uptime" {self.customer}',
            ],
        }
        for case, lines in cases.items():
            with self.subTest(case):
                self.plant_platform(lines)
                before = self.host.snapshot()
                code, result = self.release()
                self.assertEqual(code, 2)
                self.assertEqual(
                    result,
                    {
                        "refused": "admin would keep no customer key ssh-keygen "
                        "accepts without command= or restrict"
                    },
                )
                self.assertEqual(self.host.snapshot(), before)

    def test_release_refuses_a_platform_login_and_a_linked_key_file(self):
        self.plant_platform([f"{self.agent} workspace", self.customer])
        before = self.host.snapshot()
        code, result = self.release(login="backup")
        self.assertEqual(
            (code, result),
            (2, {"refused": "the login user backup is a platform account"}),
        )
        self.assertEqual(self.host.snapshot(), before)
        backup = self.host.keys("backup")
        backup.unlink()
        backup.symlink_to(self.host.keys(LOGIN))
        before = self.host.snapshot()
        code, result = self.release()
        self.assertEqual(code, 2)
        self.assertIn("is no file the release reads", result["refused"])
        self.assertEqual(self.host.snapshot(), before)

    def test_a_second_release_writes_nothing_and_keeps_the_same_keys(self):
        self.plant_platform([f"{self.agent} workspace", self.customer])
        self.assertEqual(self.release()[0], 0)
        after = self.host.snapshot()
        code, result = self.release()
        self.assertEqual(code, 0)
        self.assertEqual(
            result,
            {"kept": 1, "removed": dict.fromkeys(self.mod.COUNTS, 0)},
        )
        self.assertEqual(self.host.snapshot(), after)

    def test_root_as_login_keeps_its_customer_key(self):
        self.plant_platform([self.customer])
        self.host.write(
            self.host.keys("root"), [f"{self.agent} workspace", self.customer]
        )
        code, result = self.release(login="root")
        self.assertEqual(code, 0)
        self.assertEqual(result["removed"]["agent_keys"], 1)
        self.assertEqual(
            self.host.keys("root").read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            ),
            f"{self.customer}\n",
        )

    def test_quoted_options_are_parsed_as_sshd_parses_them(self):
        agent = blob(self.agent)
        customer = blob(self.customer)
        cases = {
            self.agent: agent,
            f"  {self.agent} comment with spaces": agent,
            f'restrict,command="echo \\" {self.customer}" {self.agent} c': agent,
            self.quoted_customer_line(): customer,
            f'environment="X=a b",cert-authority {self.customer}': customer,
            f'command="echo {self.agent}': None,
            f"# {self.agent}": None,
            "": None,
        }
        for line, expected in cases.items():
            with self.subTest(line=line[:40]):
                self.assertEqual(self.mod.key_blob(line), expected)

    def test_carriage_returns_stay_and_a_commented_key_stays_off(self):
        self.plant_platform([self.customer])
        kept = f"{self.customer} customer\r\n# note\r{self.other} x\r\n"
        self.host.keys(LOGIN).write_bytes(f"{self.agent} workspace\r\n{kept}".encode())
        code, result = self.release()
        self.assertEqual((code, result["kept"]), (0, 1))
        self.assertEqual(result["removed"]["agent_keys"], 2)
        self.assertEqual(
            self.host.keys(LOGIN).read_bytes(),  # nocheck: cache-read tempdir
            kept.encode(),
        )

    def test_an_rsa_key_written_as_rsa_sha2_is_matched_by_its_blob(self):
        rsa_key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .public_key()
            .public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
            )
            .decode()
        )
        data = rsa_key.split()[1]
        self.agent = rsa_key
        self.plant_platform(
            [
                f"rsa-sha2-512 {data} workspace",
                f"rsa-sha2-256 {data} again",
                self.customer,
            ]
        )
        self.host.write(self.host.keys("root"), [f"rsa-sha2-256 {data} root"])
        code, result = self.release()
        self.assertEqual((code, result["kept"]), (0, 1))
        self.assertEqual(result["removed"]["agent_keys"], 3)
        self.assertEqual(
            self.host.keys(LOGIN).read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            ),
            f"{self.customer}\n",
        )

    def test_an_rsa_sha2_customer_key_counts_as_kept(self):
        rsa_key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .public_key()
            .public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
            )
            .decode()
        )
        self.plant_platform(
            [f"{self.agent} workspace", f"rsa-sha2-512 {rsa_key.split()[1]} c"]
        )
        code, result = self.release()
        self.assertEqual((code, result["kept"]), (0, 1))

    def test_negative_control_a_token_split_reads_the_agent_key_in_a_customer_line(
        self,
    ):
        guard = load(GUARD, "lockout_guard")
        line = self.quoted_customer_line()
        self.assertEqual(guard.key_blobs([line]), {blob(self.agent)})
        self.assertEqual(self.mod.key_blob(line), blob(self.customer))


if __name__ == "__main__":
    unittest.main()
