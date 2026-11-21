"""Unit test: the agent pre-push guard, installed as a git hook in a workspace
with a ``fork`` and an ``upstream`` bare remote, lets a clean push to the fork
through and stops a push to the upstream and a push of a seeded secret, so
nothing reaches either remote."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils import PROJECT_ROOT
from utils.agents.pre_push import bound, push_verdict, refusals, secret_hits
from utils.agents.redact import MASK
from utils.cache.yaml import load_yaml

ROLES_FILE = PROJECT_ROOT / "agents" / "firewall" / "roles.yml"
CONTRIBUTOR = "autonomous-contributor"
SEEDED = "ghp_" + "a" * 36
HOOK = """#!/usr/bin/env bash
exec {python} -m utils.agents.pre_push --role {role} -- "$@"
"""
GIT_ENV = {
    "GIT_AUTHOR_NAME": "agent",
    "GIT_AUTHOR_EMAIL": "agent@example.invalid",
    "GIT_COMMITTER_NAME": "agent",
    "GIT_COMMITTER_EMAIL": "agent@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "PYTHONPATH": str(PROJECT_ROOT),
}


class _Workspace:
    def __init__(self, root: Path, *, role: str | None) -> None:
        self.root = root
        self.env = {**os.environ, **GIT_ENV}
        self.work = root / "work"
        self._git(root, "init", "-q", "-b", "main", str(self.work))
        for remote in ("fork", "upstream"):
            self._git(root, "init", "-q", "--bare", str(root / f"{remote}.git"))
            self._git(self.work, "remote", "add", remote, str(root / f"{remote}.git"))
        if role:
            hook = self.work / ".git" / "hooks" / "pre-push"
            hook.write_text(HOOK.format(python=sys.executable, role=role))
            hook.chmod(0o755)

    def _git(self, cwd: Path, *args: str, check: bool = True):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            check=check,
        )

    def commit(self, name: str, content: str) -> None:
        (self.work / name).write_text(content)
        self._git(self.work, "add", name)
        self._git(self.work, "commit", "-q", "--no-gpg-sign", "-m", name)

    def push(self, remote: str) -> subprocess.CompletedProcess:
        return self._git(self.work, "push", remote, "main", check=False)

    def landed(self, remote: str) -> str:
        bare = self.root / f"{remote}.git"
        return self._git(bare, "for-each-ref", "--format=%(refname)").stdout.strip()


class TestPrePushHook(unittest.TestCase):
    def _workspace(self, role: str | None = CONTRIBUTOR) -> _Workspace:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return _Workspace(Path(tmp.name), role=role)

    def test_clean_push_to_the_fork_lands(self) -> None:
        ws = self._workspace()
        ws.commit("README.md", "clean\n")
        result = ws.push("fork")
        self.assertEqual((result.returncode, ws.landed("fork")), (0, "refs/heads/main"))

    def test_push_to_the_upstream_is_refused_and_nothing_lands(self) -> None:
        ws = self._workspace()
        ws.commit("README.md", "clean\n")
        result = ws.push("upstream")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("firewall deny: app(upstream/push):create", result.stderr)
        self.assertEqual(ws.landed("upstream"), "")

    def test_seeded_secret_is_refused_masked_and_nothing_lands(self) -> None:
        ws = self._workspace()
        ws.commit("README.md", "clean\n")
        ws.commit("env.sh", f"export GH={SEEDED}\n")
        result = ws.push("fork")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"secret in the diff: export GH={MASK}", result.stderr)
        self.assertNotIn(SEEDED, result.stderr)
        self.assertEqual(ws.landed("fork"), "")

    def test_only_unpushed_commits_are_scanned(self) -> None:
        ws = self._workspace(role=None)
        ws.commit("env.sh", f"export GH={SEEDED}\n")
        ws.push("fork")
        ws._git(ws.work, "fetch", "-q", "fork")
        hook = ws.work / ".git" / "hooks" / "pre-push"
        hook.write_text(HOOK.format(python=sys.executable, role=CONTRIBUTOR))
        hook.chmod(0o755)
        ws.commit("README.md", "clean\n")
        self.assertEqual(ws.push("fork").returncode, 0)

    def test_negative_control_without_the_hook_the_secret_lands(self) -> None:
        ws = self._workspace(role=None)
        ws.commit("env.sh", f"export GH={SEEDED}\n")
        result = ws.push("fork")
        self.assertEqual((result.returncode, ws.landed("fork")), (0, "refs/heads/main"))


class TestVerdictAndScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.roles = load_yaml(ROLES_FILE)

    def test_contributor_may_push_to_the_fork_only(self) -> None:
        firewall = bound(self.roles, [CONTRIBUTOR])
        verdicts = {
            r: push_verdict(firewall, r) for r in ("fork", "upstream", "origin")
        }
        self.assertEqual(
            verdicts, {"fork": "allow", "upstream": "deny", "origin": "deny"}
        )

    def test_bound_roles_fold_and_deny_wins(self) -> None:
        firewall = bound(self.roles, ["counsel", CONTRIBUTOR])
        self.assertEqual(push_verdict(firewall, "fork"), "deny")

    def test_removed_lines_and_clean_lines_are_no_hit(self) -> None:
        patch = f"--- a/x\n+++ b/x\n-export GH={SEEDED}\n+clean line\n"
        self.assertEqual(secret_hits(patch), [])

    def test_added_private_key_is_one_masked_hit(self) -> None:
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
        patch = "".join(f"+{line}\n" for line in key.splitlines())
        self.assertEqual(secret_hits(patch), [MASK])

    def test_unknown_role_denies_and_no_update_line_is_no_scan(self) -> None:
        firewall = bound(self.roles, ["no-such-role"])
        self.assertEqual(
            refusals(firewall, "fork", io.StringIO("")),
            ["firewall deny: app(fork/push):create"],
        )

    def test_a_local_ref_with_spaces_is_still_scanned(self) -> None:
        firewall = bound(self.roles, [CONTRIBUTOR])
        update = f"HEAD@{{1 day ago}} {'a' * 40} refs/heads/x {'0' * 40}\n"
        with mock.patch(
            "utils.agents.pre_push.outgoing_patch",
            return_value=f"+export GH={SEEDED}\n",
        ):
            reasons = refusals(firewall, "fork", io.StringIO(update))
        self.assertEqual(
            reasons, [f"HEAD@{{1 day ago}}: secret in the diff: export GH={MASK}"]
        )

    def test_an_unreadable_update_line_refuses_the_push(self) -> None:
        firewall = bound(self.roles, [CONTRIBUTOR])
        self.assertEqual(
            refusals(firewall, "fork", io.StringIO("garbage\n")),
            ["unreadable ref update: garbage"],
        )


if __name__ == "__main__":
    unittest.main()
