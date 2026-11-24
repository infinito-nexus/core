from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import repository_files
from utils.cache.yaml import load_yaml_any
from utils.update.docker import collect_entries, compose_files

from . import PROJECT_ROOT

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "cron-update.yml"
JOB = "update-compose-image-versions"
UPDATE = "scripts/github/update/image_versions.sh"
CHECK = "scripts/github/resolve/check_git_changes.sh"
OPEN_PR = "scripts/github/update/open/pr.sh"
EXEMPLAR = "compose/infra.yml"
UNTOUCHED = ".pre-commit-config.yaml"
PINNED = "services:\n  registry-cache:\n    image: rpardini/docker-registry-proxy:{}\n"
GH_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "${GH_STUB_LOG}"
if [[ "$1 $2" == "pr list" ]]; then
	prefix="$(printf '%s' "$*" | sed -nE 's/.*startswith\("([^"]+)"\).*/\1/p')"
	if [[ -n "${prefix}" && "${GH_STUB_BRANCH}" == "${prefix}"* ]]; then
		printf '7\tfalse\t%s\n' "${GH_STUB_BRANCH}"
	fi
fi
"""


def _jobs() -> dict:
    return load_yaml_any(str(WORKFLOW))["jobs"]


def _step(job: dict, script: str) -> dict:
    return next(step for step in job["steps"] if script in str(step.get("run", "")))


def _args(step: dict, script: str) -> list[str]:
    argv = shlex.split(step["run"])
    return argv[argv.index(script) + 1 :]


def _prefixes() -> dict[str, str]:
    return {
        name: step["env"]["UPDATE_BRANCH_PREFIX"]
        for name, job in _jobs().items()
        for step in job.get("steps", [])
        if "UPDATE_BRANCH_PREFIX" in (step.get("env") or {})
    }


def _owned() -> list[str]:
    return compose_files(PROJECT_ROOT, repository_files())


class TestComposeUpdateJob(unittest.TestCase):
    def test_compose_bumps_open_one_pr_on_a_branch_prefix_of_their_own(self):
        job = _jobs()[JOB]
        self.assertEqual(_args(_step(job, UPDATE), UPDATE), ["--compose"])
        self.assertIn(OPEN_PR, _step(job, OPEN_PR)["run"])
        prefixes = _prefixes()
        own = prefixes.pop(JOB)
        clashes = {
            name: prefix
            for name, prefix in prefixes.items()
            if prefix.startswith(own) or own.startswith(prefix)
        }
        self.assertEqual(clashes, {})

    def test_the_change_check_and_the_pr_cover_every_compose_file(self):
        job = _jobs()[JOB]
        pathspecs = _args(_step(job, OPEN_PR), OPEN_PR)
        self.assertEqual(_args(_step(job, CHECK), CHECK), pathspecs)
        owned = _owned()
        self.assertIn(EXEMPLAR, owned)
        self.assertEqual(
            [
                rel
                for rel in owned
                if not any(fnmatch.fnmatchcase(rel, spec) for spec in pathspecs)
            ],
            [],
        )

    def test_no_file_is_bumped_by_both_docker_updaters(self):
        role_files = {
            entry.config_path.relative_to(PROJECT_ROOT).as_posix()
            for entry in collect_entries(PROJECT_ROOT)
        }
        self.assertTrue(role_files)
        self.assertEqual(set(_owned()) & role_files, set())


class ComposePrFixture:
    """A throwaway repo whose compose pin the job bumped, run through the job's PR step.

    Args:
        tmp: directory that holds the repo and the ``gh`` stub.
    """

    def __init__(self, tmp: str) -> None:
        self.repo = Path(tmp) / "repo"
        stub_dir = Path(tmp) / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "gh"
        stub.write_text(GH_STUB)
        stub.chmod(0o755)
        self.step = _step(_jobs()[JOB], OPEN_PR)
        self.prefix = self.step["env"]["UPDATE_BRANCH_PREFIX"]
        inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        job_env = {
            key: value
            for key, value in self.step["env"].items()
            if key not in {"GH_TOKEN", "APP_SLUG"}
        }
        self.env = {
            **inherited,
            **job_env,
            "PATH": os.pathsep.join(
                [str(stub_dir), str(Path(sys.executable).parent), os.environ["PATH"]]
            ),
            "PYTHONPATH": str(PROJECT_ROOT),
            "GH_STUB_LOG": str(Path(tmp) / "gh.log"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ALLOW_PROTOCOL": "file",
            "GH_TOKEN": "unused",
            "UPDATE_BRANCH_SUFFIX": "20261123",
        }
        pinned = self.repo / EXEMPLAR
        pinned.parent.mkdir(parents=True)
        self.git("init", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        pinned.write_text(PINNED.format("0.6.5"))
        (self.repo / UNTOUCHED).write_text("repos: []\n")
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "init",
        )
        pinned.write_text(PINNED.format("0.8.0"))

    def git(self, *args: str, stdin: str | None = None) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def fingerprint(self) -> str:
        blob = self.git("hash-object", EXEMPLAR)
        return self.git("hash-object", "--stdin", stdin=f"{blob}\t{EXEMPLAR}\n")

    def open_pr(self, open_branch: str) -> subprocess.CompletedProcess:
        """Run the job's PR step while ``gh`` knows one open PR.

        Args:
            open_branch: head branch of that PR; ``gh`` lists it only when it
                starts with the prefix the step filters on.
        """
        return subprocess.run(
            ["bash", str(PROJECT_ROOT / OPEN_PR), *_args(self.step, OPEN_PR)],
            cwd=self.repo,
            env={**self.env, "GH_STUB_BRANCH": open_branch},
            capture_output=True,
            text=True,
            check=False,
        )


class TestComposePrDedupe(unittest.TestCase):
    def test_an_open_pr_carrying_the_same_bump_is_not_opened_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ComposePrFixture(tmp)
            fp = fixture.fingerprint()[:7]
            result = fixture.open_pr(f"{fixture.prefix}-20261122-{fp}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Open PR #7 already carries this exact change", result.stdout)
        self.assertNotIn("Pushing change to branch", result.stdout)

    def test_an_open_role_pr_does_not_hold_back_the_compose_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ComposePrFixture(tmp)
            fp = fixture.fingerprint()[:7]
            role_branch = f"update/docker-image-versions-svc-x-20261122-{fp}"
            result = fixture.open_pr(role_branch)
        self.assertNotIn("already carries this exact change", result.stdout)
        self.assertIn(
            f"Pushing change to branch {fixture.prefix}-20261123-{fp}", result.stdout
        )

    def test_an_open_pr_of_another_bump_does_not_hold_back_this_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ComposePrFixture(tmp)
            fp = fixture.fingerprint()[:7]
            result = fixture.open_pr(f"{fixture.prefix}-20261122-0000000")
        self.assertIn("head unfetchable; treating as non-duplicate", result.stdout)
        self.assertIn(
            f"Pushing change to branch {fixture.prefix}-20261123-{fp}", result.stdout
        )


if __name__ == "__main__":
    unittest.main()
