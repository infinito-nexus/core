from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.contributing.update.opentofu.__main__ import main
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import opentofu

ROLE_FILES = PROJECT_ROOT / "roles" / "web-app-semaphore" / "files"
BUILD = ROLE_FILES / "shell" / "opentofu" / "build.sh"
SHIM = """#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
cwd = pathlib.Path.cwd()
if args and args[0].startswith("-chdir="):
    cwd = pathlib.Path(args.pop(0).split("=", 1)[1])
with open(os.environ["FAKE_TOFU_LOG"], "a") as handle:
    handle.write(json.dumps(args) + "\\n")
if args[:2] == ["providers", "lock"]:
    pins = json.loads((cwd / "versions.tf.json").read_text())
    blocks = "".join(
        f'provider "registry.opentofu.org/{{pin["source"]}}" {{{{\\n'
        f'  version     = "{{pin["version"]}}"\\n'
        f'  constraints = "{{pin["version"]}}"\\n}}}}\\n\\n'
        for pin in pins["terraform"]["required_providers"].values()
    )
    (cwd / ".terraform.lock.hcl").write_text(blocks)
"""
URLS = {
    "amd64": "https://example.org/tofu_{version}_linux_amd64.tar.gz",
    "arm64": "https://example.org/tofu_{version}_linux_arm64.tar.gz",
}
MACHINES = {"amd64": "x86_64", "arm64": "aarch64"}
DNS = "https://registry.opentofu.org/v1/providers/hashicorp/dns/versions"
TLS = "https://registry.opentofu.org/v1/providers/hashicorp/tls/versions"


def _versions(*versions):
    return json.dumps({"versions": [{"version": v} for v in versions]}).encode()


def _archive():
    data = SHIM.format(python=sys.executable).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("tofu")
        info.size, info.mode = len(data), 0o755
        bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


ARCHIVE = _archive()


class FakeRepository:
    """Args:
    sha256: ``{architecture: sum}`` of the OpenTofu archives the fake role pins.
    machine: what ``platform.machine()`` answers on the updating host.
    """

    def __init__(self, sha256, machine="x86_64"):
        self.root = Path(tempfile.mkdtemp(prefix="opentofu-update-test-"))
        self.log = self.root / "tofu.log"
        self.machine = machine
        self.fetched = []
        self.role = self._role("web-app-tofu", "stable", sha256)
        self.eol = self._role("web-app-old", "eol", sha256)
        self.registry = {
            DNS: _versions("3.6.2", "3.7.0", "3.8.0-beta1"),
            TLS: _versions("4.4.2"),
            **{url.format(version="1.13.9"): ARCHIVE for url in URLS.values()},
        }

    def _role(self, name, stage, sha256):
        role = self.root / "roles" / name
        (role / "meta").mkdir(parents=True)
        runner = {
            "opentofu_version": "1.13.9",
            **{f"opentofu_url_{arch}": url for arch, url in URLS.items()},
            **{f"opentofu_sha256_{arch}": value for arch, value in sha256.items()},
            "opentofu_platforms": ["linux_amd64", "linux_arm64"],
        }
        services = {
            name.removeprefix("web-app-"): {"lifecycle": stage},
            "runner": runner,
        }
        (role / ROLE_FILE_META_SERVICES).write_text(dump_yaml_str(services))
        opentofu = role / "files" / "opentofu"
        for root in ("roots/a", "records"):
            directory = opentofu / root
            directory.mkdir(parents=True)
            providers = {
                "dns": {"source": "hashicorp/dns", "version": "3.6.2"},
                "tls": {"source": "hashicorp/tls", "version": "4.4.2"},
            }
            document = {"terraform": {"required_providers": providers}}
            (directory / "versions.tf.json").write_text(json.dumps(document))
            (directory / ".terraform.lock.hcl").write_text(
                'provider "registry.opentofu.org/hashicorp/dns" {\n  version     = "3.6.2"\n}\n'
                'provider "registry.opentofu.org/hashicorp/tls" {\n  version     = "4.4.2"\n}\n'
            )
        (opentofu / "modules" / "dns-knot").mkdir(parents=True)
        (opentofu / "modules" / "dns-knot" / "main.tf.json").write_text("{}")
        build = role / "files" / "shell" / "opentofu"
        build.mkdir(parents=True)
        shutil.copy2(BUILD, build / "build.sh")
        return role

    def get(self, url):
        self.fetched.append(url)
        return self.registry[url]

    def pin(self, role, root):
        path = role / "files" / "opentofu" / root / "versions.tf.json"
        document = json.loads(path.read_text())  # nocheck: cache-read tempdir fixture
        return document["terraform"]["required_providers"]["dns"]["version"]

    def calls(self):
        if not self.log.is_file():
            return []
        lines = self.log.read_text().splitlines()  # nocheck: cache-read  stub call log
        return [json.loads(line) for line in lines]

    def main(self, *arguments):
        with (
            mock.patch.dict(os.environ, {"FAKE_TOFU_LOG": str(self.log)}),
            mock.patch.object(opentofu.platform, "machine", return_value=self.machine),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return main(["--repo-root", str(self.root), *arguments], self.get)


SUMS = dict.fromkeys(URLS, hashlib.sha256(ARCHIVE).hexdigest())


class UpdateCase(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository(SUMS)
        self.addCleanup(shutil.rmtree, self.repository.root, True)


class TestBump(UpdateCase):
    def test_the_opentofu_updater_bumps_every_pin(self):
        self.assertEqual(self.repository.main(), 0)
        for root in ("roots/a", "records"):
            self.assertEqual(self.repository.pin(self.repository.role, root), "3.7.0")

    def test_a_pre_release_is_ignored(self):
        self.assertEqual(
            opentofu.latest_release("hashicorp/dns", self.repository.get), "3.7.0"
        )

    def test_an_eol_role_is_untouched(self):
        self.repository.main()
        for root in ("roots/a", "records"):
            self.assertEqual(self.repository.pin(self.repository.eol, root), "3.6.2")

    def test_a_dry_run_writes_nothing(self):
        self.assertEqual(self.repository.main("--dry-run"), 0)
        self.assertEqual(self.repository.pin(self.repository.role, "roots/a"), "3.6.2")
        self.assertEqual(self.repository.calls(), [])
        self.assertEqual(opentofu.stale_locks(self.repository.root), [])


class TestLock(UpdateCase):
    def test_the_lock_files_follow_the_pins(self):
        self.repository.main()
        locks = [c for c in self.repository.calls() if c[:2] == ["providers", "lock"]]
        self.assertEqual(len(locks), 2)
        for call in locks:
            self.assertEqual(
                call[2:], ["-platform=linux_amd64", "-platform=linux_arm64"]
            )
        self.assertEqual(opentofu.stale_locks(self.repository.root), [])

    def test_negative_control_without_the_lock_step_the_lock_is_stale(self):
        updates = opentofu.find_outdated_updates(
            self.repository.root, self.repository.get
        )
        opentofu.apply_updates(updates)
        self.assertEqual(len(opentofu.stale_locks(self.repository.root)), 2)

    def test_an_archive_off_its_pin_is_refused(self):
        repository = FakeRepository(dict.fromkeys(URLS, "0" * 64))
        self.addCleanup(shutil.rmtree, repository.root, True)
        with self.assertRaisesRegex(ValueError, "does not match its pin"):
            repository.main()


class TestHostArchitecture(unittest.TestCase):
    def run_on(self, architecture, sums):
        repository = FakeRepository(sums, MACHINES[architecture])
        self.addCleanup(shutil.rmtree, repository.root, True)
        repository.main()
        return [url for url in repository.fetched if "tofu_" in url]

    def test_each_host_fetches_the_tofu_of_its_own_architecture(self):
        for architecture, url in URLS.items():
            with self.subTest(architecture=architecture):
                fetched = self.run_on(architecture, SUMS)
                self.assertEqual(set(fetched), {url.format(version="1.13.9")})

    def test_negative_control_a_wrong_sum_of_the_host_architecture_is_refused(self):
        for architecture in URLS:
            with self.subTest(architecture=architecture):
                sums = {**SUMS, architecture: "0" * 64}
                with self.assertRaisesRegex(ValueError, architecture):
                    self.run_on(architecture, sums)

    def test_an_unmapped_machine_is_refused(self):
        with (
            mock.patch.object(opentofu.platform, "machine", return_value="s390x"),
            self.assertRaisesRegex(ValueError, "maps no architecture for 's390x'"),
        ):
            opentofu.host_architecture()


class TestReadme(unittest.TestCase):
    def test_the_update_readme_names_the_opentofu_updater(self):
        readme = read_text(
            str(PROJECT_ROOT / "cli" / "contributing" / "update" / "README.md")
        )
        for phrase in (
            "python -m cli.contributing.update.opentofu",
            "versions.tf.json",
            "tofu providers lock",
            "opentofu_platforms",
            "scripts/github/update/opentofu_pins.sh",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)


if __name__ == "__main__":
    unittest.main()
