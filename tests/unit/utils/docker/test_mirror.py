from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.docker import mirror

_CONFIG_WITH_FORK = """\
[core]
\trepositoryformatversion = 0
[remote "origin"]
\turl = git@github.com:upstream-org/core.git
[remote "fork"]
\turl = https://github.com/a-user/a-repo.git
[remote]
\tpushDefault = fork
[branch "main"]
\tvscode-merge-base = origin/main
\tvscode-merge-base = fork/main
"""

_CONFIG_ORIGIN_ONLY = """\
[remote "origin"]
\turl = git@github.com:upstream-org/core.git
"""


class _RepoConfig(unittest.TestCase):
    def _with_config(self, body: str | None):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        if body is not None:
            git_dir = Path(root.name) / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text(body, encoding="utf-8")
        return mock.patch.object(mirror, "PROJECT_ROOT", Path(root.name))


class TestRemoteUrl(_RepoConfig, unittest.TestCase):
    def test_push_default_wins_over_origin(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK):
            self.assertEqual(
                mirror._remote_url(), "https://github.com/a-user/a-repo.git"
            )

    def test_origin_is_used_without_a_push_default(self) -> None:
        with self._with_config(_CONFIG_ORIGIN_ONLY):
            self.assertEqual(
                mirror._remote_url(), "git@github.com:upstream-org/core.git"
            )

    def test_duplicate_keys_do_not_break_parsing(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK):
            self.assertIn("branch.main.vscode-merge-base", mirror._git_config())

    def test_missing_config_yields_no_url(self) -> None:
        with self._with_config(None):
            self.assertIsNone(mirror._remote_url())


class TestOwnerAndRepository(_RepoConfig, unittest.TestCase):
    def test_github_environment_wins(self) -> None:
        with (
            self._with_config(_CONFIG_WITH_FORK),
            mock.patch.dict(
                mirror.os.environ,
                {"GITHUB_REPOSITORY": "Env-Owner/Env-Repo"},
                clear=True,
            ),
        ):
            self.assertEqual(mirror._owner_and_repository(), ("env-owner", "env-repo"))

    def test_repository_owner_wins_over_the_slug(self) -> None:
        with (
            self._with_config(_CONFIG_WITH_FORK),
            mock.patch.dict(
                mirror.os.environ,
                {
                    "GITHUB_REPOSITORY": "Env-Owner/Env-Repo",
                    "GITHUB_REPOSITORY_OWNER": "Explicit-Owner",
                },
                clear=True,
            ),
        ):
            self.assertEqual(
                mirror._owner_and_repository(), ("explicit-owner", "env-repo")
            )

    def test_ssh_remote_is_parsed(self) -> None:
        with (
            self._with_config(_CONFIG_ORIGIN_ONLY),
            mock.patch.dict(mirror.os.environ, {}, clear=True),
        ):
            self.assertEqual(mirror._owner_and_repository(), ("upstream-org", "core"))

    def test_https_remote_is_parsed(self) -> None:
        with (
            self._with_config(_CONFIG_WITH_FORK),
            mock.patch.dict(mirror.os.environ, {}, clear=True),
        ):
            self.assertEqual(mirror._owner_and_repository(), ("a-user", "a-repo"))


class TestMirrorImage(_RepoConfig, unittest.TestCase):
    def _env(self, **overrides):
        env = {"INFINITO_GHCR_MIRROR_PREFIX": "mirror"}
        env.update(overrides)
        return mock.patch.dict(mirror.os.environ, env, clear=True)

    def test_implicit_docker_hub_image(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK), self._env():
            self.assertEqual(
                mirror.mirror_image("postgres"),
                "ghcr.io/a-user/a-repo/mirror/docker.io/postgres",
            )

    def test_explicit_registry_is_kept_in_the_path(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK), self._env():
            self.assertEqual(
                mirror.mirror_image("quay.io/keycloak/keycloak"),
                "ghcr.io/a-user/a-repo/mirror/quay.io/keycloak/keycloak",
            )

    def test_docker_hub_aliases_normalise(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK), self._env():
            self.assertEqual(
                mirror.mirror_image("docker.io/library/nginx"),
                "ghcr.io/a-user/a-repo/mirror/docker.io/library/nginx",
            )

    def test_no_prefix_means_no_mirror(self) -> None:
        with (
            self._with_config(_CONFIG_WITH_FORK),
            self._env(INFINITO_GHCR_MIRROR_PREFIX=""),
        ):
            self.assertIsNone(mirror.mirror_image("postgres"))

    def test_unresolvable_namespace_means_no_mirror(self) -> None:
        with self._with_config(None), self._env():
            self.assertIsNone(mirror.mirror_image("postgres"))

    def test_malformed_image_means_no_mirror(self) -> None:
        with self._with_config(_CONFIG_WITH_FORK), self._env():
            self.assertIsNone(mirror.mirror_image("Not A Valid Image"))


if __name__ == "__main__":
    unittest.main()
