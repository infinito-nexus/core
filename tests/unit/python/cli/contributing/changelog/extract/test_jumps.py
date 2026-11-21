import tempfile
import unittest
from pathlib import Path

from cli.contributing.changelog.extract.jumps import Jump, extract, lines, section
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from ._repo import FixtureRepo

SERVICES = f"roles/web-app-demo/{ROLE_FILE_META_SERVICES}"


class TestExtract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = FixtureRepo(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _release(self, before: dict[str, str], after: dict[str, str]) -> list[Jump]:
        for path, text in before.items():
            self.repo.write(path, text)
        self.repo.commit("base")
        self.repo.tag("v1.0.0")
        for path, text in after.items():
            self.repo.write(path, text)
        self.repo.commit("next")
        return extract(self.repo.root, "v1.0.0", "HEAD")

    def test_role_meta_pins_jump(self) -> None:
        jumps = self._release(
            {SERVICES: "demo:\n  version: 1.0.0\n  ref: '{{ X }}'\n"},
            {SERVICES: "demo:\n  version: 1.2.0\n  ref: '{{ Y }}'\n"},
        )
        self.assertEqual(jumps, [Jump("web-app-demo", "demo", "1.0.0", "1.2.0")])

    def test_only_the_net_jump_counts(self) -> None:
        self.repo.write(SERVICES, "demo:\n  version: 1.0.0\n")
        self.repo.commit("base")
        self.repo.tag("v1.0.0")
        self.repo.write(SERVICES, "demo:\n  version: 1.1.0\n")
        self.repo.commit("bump")
        self.repo.write(SERVICES, "demo:\n  version: 1.0.0\n")
        self.repo.commit("revert")
        self.assertEqual(extract(self.repo.root, "v1.0.0", "HEAD"), [])

    def test_requirements_collections_jump(self) -> None:
        path = "requirements/requirements.galaxy.yml"
        jumps = self._release(
            {path: "collections:\n  - name: community.general\n    version: 13.5.0\n"},
            {path: "collections:\n  - name: community.general\n    version: 14.0.0\n"},
        )
        self.assertEqual(
            jumps, [Jump("Ansible", "community.general", "13.5.0", "14.0.0")]
        )

    def test_pyproject_pins_jump_and_a_new_pin_is_added(self) -> None:
        jumps = self._release(
            {
                "pyproject.toml": '[project]\ndependencies = ["ruff==0.1.0", "ansible"]\n'
            },
            {
                "pyproject.toml": '[project]\ndependencies = ["ruff==0.2.0", "ansible==14.4.0"]\n'
            },
        )
        self.assertEqual(
            jumps,
            [
                Jump("Python", "ansible", None, "14.4.0"),
                Jump("Python", "ruff", "0.1.0", "0.2.0"),
            ],
        )

    def test_role_dockerfile_pins_jump(self) -> None:
        path = "roles/web-app-demo/files/Dockerfile"
        jumps = self._release(
            {path: "FROM python:3.12-slim\nRUN pip install aiosmtpd==1.4.5\n"},
            {path: "FROM python:3.13-slim\nRUN pip install aiosmtpd==1.4.6\n"},
        )
        self.assertEqual(
            jumps,
            [
                Jump("web-app-demo", "aiosmtpd", "1.4.5", "1.4.6"),
                Jump("web-app-demo", "python", "3.12-slim", "3.13-slim"),
            ],
        )

    def test_a_renamed_role_compares_its_old_path(self) -> None:
        stable = "".join(f"  key_{index}: value {index}\n" for index in range(12))
        jumps = self._release(
            {
                f"roles/web-svc-css/{ROLE_FILE_META_SERVICES}": f"css:\n{stable}  version: 1.0.0\n"
            },
            {},
        )
        self.assertEqual(jumps, [])
        self.repo.git("mv", "roles/web-svc-css", "roles/web-svc-design")
        self.repo.write(
            f"roles/web-svc-design/{ROLE_FILE_META_SERVICES}",
            f"css:\n{stable}  version: 1.1.0\n",
        )
        self.repo.commit("rename")
        self.assertEqual(
            extract(self.repo.root, "v1.0.0", "HEAD"),
            [Jump("web-svc-design", "css", "1.0.0", "1.1.0")],
        )

    def test_a_renamed_pin_key_keeps_its_old_value(self) -> None:
        jumps = self._release(
            {SERVICES: "demo:\n  webui:\n    version: v1.0.11\n"},
            {SERVICES: "demo:\n  web:\n    version: v2.0.5\n"},
        )
        self.assertEqual(
            jumps,
            [Jump("web-app-demo", "demo.web (was demo.webui)", "v1.0.11", "v2.0.5")],
        )

    def test_a_version_inside_a_url_jumps(self) -> None:
        jumps = self._release(
            {SERVICES: "demo:\n  archive: https://example.invalid/demo/v0.3.0.zip\n"},
            {SERVICES: "demo:\n  archive: https://example.invalid/demo/v0.4.0.zip\n"},
        )
        self.assertEqual(
            jumps, [Jump("web-app-demo", "demo.archive", "v0.3.0", "v0.4.0")]
        )

    def test_a_new_role_adds_no_rows(self) -> None:
        jumps = self._release(
            {SERVICES: "demo:\n  version: 1.0.0\n"},
            {
                f"roles/web-app-new/{ROLE_FILE_META_SERVICES}": "new:\n  version: 2.0.0\n"
            },
        )
        self.assertEqual(jumps, [])


class TestLines(unittest.TestCase):
    def test_one_line_per_role_with_the_main_group_unnamed(self) -> None:
        jumps = [
            Jump("web-app-gitea", "gitea", "28.2.0", "28.3.0"),
            Jump("web-app-gitea", "mcp", "1.10.0", "1.13.0"),
            Jump("web-app-gitlab", "shell", "v19.5.1", "v19.5.3"),
            Jump("web-app-gitlab", "sidekiq", "v19.5.1", "v19.5.3"),
        ]
        self.assertEqual(
            lines(jumps),
            [
                "- *web-app-gitea*: 28.2.0 to 28.3.0, mcp 1.10.0 to 1.13.0",
                "- *web-app-gitlab*: v19.5.1 to v19.5.3",
            ],
        )

    def test_a_shared_variant_suffix_is_dropped(self) -> None:
        jumps = [Jump("svc-db-redis", "redis", "8.10.2-alpine", "8.10.3-alpine")]
        self.assertEqual(lines(jumps), ["- *svc-db-redis*: 8.10.2 to 8.10.3"])

    def test_added_pins_and_commits_read_plainly(self) -> None:
        jumps = [
            Jump("Python", "ansible", None, "14.4.0"),
            Jump("web-app-discourse", "discourse", "main", "7" * 40),
        ]
        self.assertEqual(
            lines(jumps),
            [
                "- Python: ansible new at 14.4.0",
                "- *web-app-discourse*: main to commit 7777777",
            ],
        )

    def test_section_names_the_base_version(self) -> None:
        text = section([Jump("pkgmgr", "pkgmgr", "v2.0.4", "v2.4.0")], "v16.2.3")
        self.assertTrue(text.startswith("Version jumps (net since 16.2.3):\n\n"))


if __name__ == "__main__":
    unittest.main()
