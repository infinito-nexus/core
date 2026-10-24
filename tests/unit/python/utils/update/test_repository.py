from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_SERVICES
from utils.update import repository as module
from utils.update.repository import (
    RepositoryRefEntry,
    RepositoryRefUpdate,
    apply_updates,
    collect_entries,
    find_outdated_updates,
    git_ls_remote_head,
    is_commit_sha,
    suppressed_ref_lines,
    update_config_refs,
    walk_repo_ref_pairs,
)


class TestWalkRepoRefPairs(unittest.TestCase):
    def test_finds_top_level_entity(self) -> None:
        data = {
            "bookwyrm": {
                "repository": "https://github.com/bookwyrm-social/bookwyrm.git",
                "ref": "v0.8.5",
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(
            pairs,
            [
                (
                    ("bookwyrm",),
                    "https://github.com/bookwyrm-social/bookwyrm.git",
                    "v0.8.5",
                ),
            ],
        )

    def test_descends_into_nested_plugin_map(self) -> None:
        data = {
            "discourse": {
                "plugins": {
                    "discourse-ldap-auth": {
                        "repository": "https://github.com/jonmbake/discourse-ldap-auth.git",
                        "ref": "master",
                    },
                    "discourse-prometheus": {
                        "repository": "https://github.com/discourse/discourse-prometheus.git",
                        "ref": "v1.0.0",
                    },
                },
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))
        entity_paths = {pair[0] for pair in pairs}

        self.assertIn(("discourse", "plugins", "discourse-ldap-auth"), entity_paths)
        self.assertIn(("discourse", "plugins", "discourse-prometheus"), entity_paths)

    def test_skips_when_only_repository_or_only_ref(self) -> None:
        data = {
            "only-repo": {"repository": "https://example.invalid/x.git"},
            "only-ref": {"ref": "v1.0.0"},
            "both": {
                "repository": "https://example.invalid/y.git",
                "ref": "v2.0.0",
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], ("both",))

    def test_walks_lists(self) -> None:
        data = {
            "repos": [
                {
                    "repository": "https://example.invalid/a.git",
                    "ref": "v1",
                },
                {
                    "repository": "https://example.invalid/b.git",
                    "ref": "v2",
                },
            ],
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][0], ("repos", "[0]"))
        self.assertEqual(pairs[1][0], ("repos", "[1]"))


class TestUpdateConfigRefs(unittest.TestCase):
    def test_rewrites_target_line_and_preserves_others(self) -> None:
        original = """plugin-a:
  repository: https://example.invalid/a.git
  ref: v1.0.0
plugin-b:
  repository: https://example.invalid/b.git
  ref: v2.0.0
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {3: "v1.1.0"})

            self.assertTrue(changed)
            updated = read_text(str(config_path))
            self.assertIn("  ref: v1.1.0\n", updated)
            self.assertIn("  ref: v2.0.0\n", updated)

    def test_preserves_quoting_and_trailing_comment(self) -> None:
        original = '  ref: "v0.7.5"  # pin\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {1: "v0.8.5"})

            self.assertTrue(changed)
            self.assertEqual(
                read_text(str(config_path)),
                '  ref: "v0.8.5"  # pin\n',
            )

    def test_no_op_when_target_value_already_matches(self) -> None:
        original = "  ref: v1.0.0\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {1: "v1.0.0"})

            self.assertFalse(changed)
            self.assertEqual(read_text(str(config_path)), original)

    def test_skips_out_of_range_line_numbers(self) -> None:
        original = "  ref: v1.0.0\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {99: "v2.0.0"})

            self.assertFalse(changed)
            self.assertEqual(read_text(str(config_path)), original)


class TestSuppressedRefLines(unittest.TestCase):
    def test_recognises_line_above_marker(self) -> None:
        content = """plugin-a:
  repository: https://example.invalid/a.git
  # nocheck: repository-version
  ref: v1.0.0
plugin-b:
  repository: https://example.invalid/b.git
  ref: v2.0.0
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(content, encoding="utf-8")

            suppressed = suppressed_ref_lines(config_path)

            self.assertEqual(suppressed, {4})


class TestApplyUpdates(unittest.TestCase):
    def test_groups_updates_per_config_file(self) -> None:
        file_a_content = "  ref: v1.0.0\n"
        file_b_content = "  ref: v2.0.0\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_a = Path(tmpdir) / "a" / "services.yml"
            config_b = Path(tmpdir) / "b" / "services.yml"
            config_a.parent.mkdir()
            config_b.parent.mkdir()
            config_a.write_text(file_a_content, encoding="utf-8")
            config_b.write_text(file_b_content, encoding="utf-8")

            updates = [
                RepositoryRefUpdate(
                    entry=RepositoryRefEntry(
                        role="role-a",
                        entity_path=("plugin-a",),
                        repository="https://example.invalid/a.git",
                        ref="v1.0.0",
                        config_path=config_a,
                        line=1,
                    ),
                    latest="v1.1.0",
                ),
                RepositoryRefUpdate(
                    entry=RepositoryRefEntry(
                        role="role-b",
                        entity_path=("plugin-b",),
                        repository="https://example.invalid/b.git",
                        ref="v2.0.0",
                        config_path=config_b,
                        line=1,
                    ),
                    latest="v2.1.0",
                ),
            ]

            changed = apply_updates(updates)

            self.assertEqual(set(changed), {config_a, config_b})
            self.assertEqual(read_text(str(config_a)), "  ref: v1.1.0\n")
            self.assertEqual(read_text(str(config_b)), "  ref: v2.1.0\n")


SOURCED_FIRST = (
    "sourced:\n"
    "  repository: https://example.test/a.git\n"
    "  ref: v1.0.0\n"
    "  update:\n"
    "    key: ref\n"
    "    type: http_regex\n"
    "    url: https://example.test/tags\n"
    "    pattern: 'a (v[0-9.]+)'\n"
    "plain:\n"
    "  repository: https://example.test/b.git\n"
    "  ref: v1.0.0\n"
)


class TestSourcedRef(unittest.TestCase):
    def test_a_sourced_ref_is_skipped_and_keeps_its_own_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
            config.parent.mkdir(parents=True)
            config.write_text(SOURCED_FIRST, encoding="utf-8")

            entries = collect_entries(root)

            self.assertEqual(
                [(entry.entity_path, entry.line) for entry in entries],
                [(("plain",), 11)],
            )

            apply_updates([RepositoryRefUpdate(entry=entries[0], latest="v1.1.0")])

            written = config.read_text()  # nocheck: cache-read  just rewritten here
            lines = written.splitlines()
            self.assertEqual(lines[2], "  ref: v1.0.0")
            self.assertEqual(lines[10], "  ref: v1.1.0")


class TestCollectEntriesCoversAddons(unittest.TestCase):
    def _role(self, root: Path) -> Path:
        role = root / "roles" / "web-app-example"
        (role / ROLE_DIR_META_ADDONS).mkdir(parents=True)
        return role

    def test_addon_ref_is_collected_beside_the_service_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role = self._role(root)
            (role / ROLE_FILE_META_SERVICES).write_text(
                "app:\n  repository: https://example.test/app.git\n  ref: v1.0.0\n",
                encoding="utf-8",
            )
            (role / ROLE_DIR_META_ADDONS / "plug.yml").write_text(
                "config:\n  repository: https://example.test/plug.git\n  ref: v2.0.0\n",
                encoding="utf-8",
            )

            by_ref = {entry.ref: entry for entry in collect_entries(root)}

            self.assertEqual(set(by_ref), {"v1.0.0", "v2.0.0"})
            addon = by_ref["v2.0.0"]
            self.assertEqual(addon.entity_path[:2], ("addons", "plug"))
            self.assertEqual(addon.config_path.name, "plug.yml")

    def test_addon_ref_honours_its_own_suppression_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role = self._role(root)
            (role / ROLE_DIR_META_ADDONS / "plug.yml").write_text(
                "config:\n"
                "  repository: https://example.test/plug.git\n"
                "  # nocheck: repository-version\n"
                "  ref: v2.0.0\n",
                encoding="utf-8",
            )

            self.assertEqual(collect_entries(root), [])

    def test_refs_of_an_eol_role_are_not_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role = self._role(root)
            (role / ROLE_FILE_META_SERVICES).write_text(
                "example:\n"
                "  lifecycle: eol\n"
                "  repository: https://example.test/app.git\n"
                "  ref: v1.0.0\n",
                encoding="utf-8",
            )
            (role / ROLE_DIR_META_ADDONS / "plug.yml").write_text(
                "config:\n  repository: https://example.test/plug.git\n  ref: v2.0.0\n",
                encoding="utf-8",
            )

            self.assertEqual(collect_entries(root), [])


OLD_SHA = "c623b753" * 5
TIP_SHA = "0f4e2a9c" * 5
SHA_REPO = "https://example.test/oidc.git"
TAG_REPO = "https://example.test/app.git"


class _LsRemote:
    """Stand-in for ``subprocess.run`` answering ``git ls-remote``.

    Args:
        heads: default-branch tip per repository URL.
        tags: tag names per repository URL.
        returncode: exit status every call reports.
    """

    def __init__(
        self,
        heads: dict[str, str] | None = None,
        tags: dict[str, list[str]] | None = None,
        returncode: int = 0,
    ) -> None:
        self.heads = heads or {}
        self.tags = tags or {}
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], **_kwargs) -> subprocess.CompletedProcess:
        args = tuple(argv[2:])
        self.calls.append(args)
        if args[0] == "--tags":
            stdout = "".join(
                f"{'1' * 40}\trefs/tags/{tag}\n" for tag in self.tags.get(args[1], [])
            )
        else:
            head = self.heads.get(args[0])
            stdout = f"{head}\tHEAD\n" if head else ""
        return subprocess.CompletedProcess(argv, self.returncode, stdout, "")


def _write_role(
    root: Path, services: str, addons: dict[str, str] | None = None
) -> Path:
    role = root / "roles" / "web-app-example"
    (role / ROLE_DIR_META_ADDONS).mkdir(parents=True)
    config = role / ROLE_FILE_META_SERVICES
    config.write_text(services, encoding="utf-8")
    for stem, body in (addons or {}).items():
        (role / ROLE_DIR_META_ADDONS / f"{stem}.yml").write_text(body, encoding="utf-8")
    return config


def _find(root: Path, ls_remote: _LsRemote) -> list[RepositoryRefUpdate]:
    with (
        mock.patch.object(module, "resolve_max_fetch_workers", return_value=2),
        mock.patch.object(module.subprocess, "run", side_effect=ls_remote),
    ):
        return find_outdated_updates(root)


SHA_PINNED = (
    "sso:\n"
    "  oidc:\n"
    f"    repository: {SHA_REPO}\n"
    f'    ref: "{OLD_SHA}"  # pinned commit\n'
)

ADDON_SHAPED = (
    "---\n"
    "enabled: true\n"
    "mechanism: plugin\n"
    "source: upstream\n"
    "update:\n"
    "  monitored: true\n"
    "  catalog: discourse-meta\n"
    "  upstream_id: docker_manager\n"
    "config:\n"
    f"  repository: {SHA_REPO}\n"
    f"  ref: {OLD_SHA}\n"
)


class TestIsCommitSha(unittest.TestCase):
    def test_only_a_full_lowercase_sha_counts(self) -> None:
        self.assertTrue(is_commit_sha(OLD_SHA))
        self.assertFalse(is_commit_sha(OLD_SHA[:7]))
        self.assertFalse(is_commit_sha(OLD_SHA + "0"))
        self.assertFalse(is_commit_sha("main"))
        self.assertFalse(is_commit_sha("v1.0.0"))


class TestGitLsRemoteHead(unittest.TestCase):
    def test_returns_the_head_commit(self) -> None:
        ls_remote = _LsRemote(heads={SHA_REPO: TIP_SHA})
        with mock.patch.object(module.subprocess, "run", side_effect=ls_remote):
            self.assertEqual(git_ls_remote_head(SHA_REPO), TIP_SHA)
        self.assertEqual(ls_remote.calls, [(SHA_REPO, "HEAD")])

    def test_a_failed_lookup_returns_none(self) -> None:
        for failure in (
            _LsRemote(heads={SHA_REPO: TIP_SHA}, returncode=128),
            subprocess.TimeoutExpired(["git"], 30),
            FileNotFoundError("git"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                mock.patch.object(module.subprocess, "run", side_effect=failure),
            ):
                self.assertIsNone(git_ls_remote_head(SHA_REPO))

    def test_an_empty_answer_returns_none(self) -> None:
        with mock.patch.object(module.subprocess, "run", side_effect=_LsRemote()):
            self.assertIsNone(git_ls_remote_head(SHA_REPO))


class TestCommitShaPins(unittest.TestCase):
    def test_an_outdated_sha_is_rewritten_to_the_tip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = _write_role(root, SHA_PINNED)

            updates = _find(root, _LsRemote(heads={SHA_REPO: TIP_SHA}))

            self.assertEqual(
                [(u.entry.entity_path, u.entry.ref, u.latest) for u in updates],
                [(("sso", "oidc"), OLD_SHA, TIP_SHA)],
            )
            self.assertEqual(apply_updates(updates), [config])
            written = config.read_text()  # nocheck: cache-read  just rewritten here
            self.assertEqual(
                written, SHA_PINNED.replace(f'"{OLD_SHA}"', f'"{TIP_SHA}"')
            )

    def test_a_current_sha_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(root, SHA_PINNED)

            self.assertEqual(_find(root, _LsRemote(heads={SHA_REPO: OLD_SHA})), [])

    def test_short_shas_and_branches_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root,
                "short:\n"
                "  repository: https://example.test/short.git\n"
                f"  ref: {OLD_SHA[:7]}\n"
                "branch:\n"
                "  repository: https://example.test/branch.git\n"
                "  ref: main\n",
            )
            ls_remote = _LsRemote()

            self.assertEqual(collect_entries(root), [])
            self.assertEqual(_find(root, ls_remote), [])
            self.assertEqual(ls_remote.calls, [])

    def test_a_suppressed_sha_is_not_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root,
                "app:\n"
                f"  repository: {SHA_REPO}\n"
                "  # nocheck: repository-version\n"
                f"  ref: {OLD_SHA}\n",
            )

            self.assertEqual(collect_entries(root), [])

    def test_a_sha_that_names_its_own_source_is_not_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root,
                "app:\n"
                f"  repository: {SHA_REPO}\n"
                f"  ref: {OLD_SHA}\n"
                "  update:\n"
                "    key: ref\n"
                "    type: script\n"
                "    path: files/ref.sh\n",
            )

            self.assertEqual(collect_entries(root), [])

    def test_a_failed_lookup_leaves_every_pin_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root,
                SHA_PINNED + f"app:\n  repository: {TAG_REPO}\n  ref: v1.0.0\n",
            )
            ls_remote = _LsRemote(
                heads={SHA_REPO: TIP_SHA},
                tags={TAG_REPO: ["v1.0.0", "v1.2.0"]},
                returncode=128,
            )

            self.assertEqual(_find(root, ls_remote), [])
            self.assertEqual(len(ls_remote.calls), 2)

    def test_each_repository_is_queried_once_per_lookup_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root,
                SHA_PINNED + f"app:\n  repository: {TAG_REPO}\n  ref: v1.0.0\n",
                addons={"docker_manager": ADDON_SHAPED},
            )
            ls_remote = _LsRemote(
                heads={SHA_REPO: TIP_SHA},
                tags={TAG_REPO: ["v1.0.0", "v1.2.0"]},
            )

            updates = _find(root, ls_remote)

            self.assertEqual(
                sorted(ls_remote.calls),
                [("--tags", TAG_REPO), (SHA_REPO, "HEAD")],
            )
            self.assertEqual(
                sorted((u.entry.entity_path, u.latest) for u in updates),
                [
                    (("addons", "docker_manager", "config"), TIP_SHA),
                    (("app",), "v1.2.0"),
                    (("sso", "oidc"), TIP_SHA),
                ],
            )


class TestAddonConfigShaPin(unittest.TestCase):
    def test_the_addon_config_ref_is_walked_and_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_role(
                root, "app:\n  image: nginx\n", {"docker_manager": ADDON_SHAPED}
            )
            addon = root / "roles" / "web-app-example" / ROLE_DIR_META_ADDONS
            addon /= "docker_manager.yml"

            entries = collect_entries(root)

            self.assertEqual(
                [(e.entity_path, e.ref, e.line) for e in entries],
                [(("addons", "docker_manager", "config"), OLD_SHA, 11)],
            )

            updates = _find(root, _LsRemote(heads={SHA_REPO: TIP_SHA}))
            self.assertEqual(apply_updates(updates), [addon])
            written = addon.read_text()  # nocheck: cache-read  just rewritten here
            self.assertEqual(written, ADDON_SHAPED.replace(OLD_SHA, TIP_SHA))


if __name__ == "__main__":
    unittest.main()
