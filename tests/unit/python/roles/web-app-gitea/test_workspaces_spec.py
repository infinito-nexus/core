from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

SPEC = (
    PROJECT_ROOT
    / "roles"
    / "web-app-gitea"
    / "files"
    / "playwright"
    / "test-workspaces.js"
)
TOKEN_TITLE = "gitea workspaces: the store token carries exactly three scopes"
PROTECTED_MAIN_TITLE = "gitea workspaces: only the store writes main"
MEMBERS_TITLE = "gitea workspaces: members read and billing sees nothing"
TEST_START = re.compile(r'^\s*test\(\s*"([^"]+)"', re.MULTILINE)
KEY_FILE = re.compile(r'sshKey\(\s*directory\s*,\s*"([^"]+)"\s*\)')
DIRECTORY_ENTRY = re.compile(r'path\.join\(\s*directory\s*,\s*"([^"]+)"\s*\)')
ROTATION_SKIP = "test.skip(!workspacesApply"
ROTATION_RUN = "runTemplateTask(sem, null, ROTATION_RUN_MS"
VIEWER_PUSH = 'httpsGit(["push", "origin", "HEAD"], clone, auth)'


def spec_bodies(source: str) -> dict[str, str]:
    """
    Args:
        source: the text of a Playwright spec.

    Returns:
        Each test title mapped to its source, up to the start of the next test.
    """
    starts = list(TEST_START.finditer(source))
    ends = [match.start() for match in starts[1:]] + [len(source)]
    return {
        match.group(1): source[match.start() : end]
        for match, end in zip(starts, ends, strict=True)
    }


def key_collisions(source: str) -> dict[str, list[str]]:
    """
    Args:
        source: the text of a Playwright spec.

    Returns:
        Per test title, the entries of its temporary directory that hold an
        SSH key file of `sshKey` and that the same test also uses as a path,
        such as a clone target.
    """
    found = {}
    for title, body in spec_bodies(source).items():
        keys = set(KEY_FILE.findall(body))
        keys |= {f"{name}.pub" for name in keys}
        clashes = sorted(keys & set(DIRECTORY_ENTRY.findall(body)))
        if clashes:
            found[title] = clashes
    return found


def receive_pack_probes(source: str) -> list[str]:
    """
    Args:
        source: the text of a Playwright spec.

    Returns:
        The titles of the tests that read the receive-pack advertisement of
        info/refs, which Gitea serves a reader with 200.
    """
    return sorted(
        title
        for title, body in spec_bodies(source).items()
        if "info/refs" in body and "git-receive-pack" in body
    )


def rotation_gates(source: str) -> dict[str, bool]:
    """
    Args:
        source: the text of a Playwright spec.

    Returns:
        Whether the store token test skips a deployment without
        `rotate store credentials` and runs that rotation itself.
    """
    body = spec_bodies(source)[TOKEN_TITLE]
    return {"skip": ROTATION_SKIP in body, "rotation": ROTATION_RUN in body}


class TestWorkspacesSpec(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read_text(str(SPEC))
        self.bodies = spec_bodies(self.source)

    def test_the_spec_holds_the_tests_these_checks_read(self) -> None:
        for title in (TOKEN_TITLE, PROTECTED_MAIN_TITLE, MEMBERS_TITLE):
            with self.subTest(title=title):
                self.assertIn(title, self.bodies)

    def test_no_test_clones_onto_its_own_key_file(self) -> None:
        self.assertEqual(
            key_collisions(self.source),
            {},
            "sshKey writes <name> and <name>.pub into the directory, so a clone "
            "into the same <name> fails with 'destination path already exists'",
        )

    def test_negative_control_a_clone_onto_a_key_file_is_caught(self) -> None:
        planted = self.source.replace(
            'path.join(directory, "store-clone")', 'path.join(directory, "store")'
        )
        self.assertNotEqual(planted, self.source)
        self.assertEqual(key_collisions(planted), {PROTECTED_MAIN_TITLE: ["store"]})

    def test_a_push_refusal_is_proven_by_a_push(self) -> None:
        self.assertEqual(
            receive_pack_probes(self.source),
            [],
            "Gitea checks only read access on info/refs?service=git-receive-pack "
            "while git supports proc-receive and refuses a reader in its "
            "pre-receive hook, so only a real push proves the refusal",
        )
        self.assertIn(VIEWER_PUSH, self.bodies[MEMBERS_TITLE])

    def test_negative_control_a_receive_pack_advertisement_probe_is_caught(
        self,
    ) -> None:
        planted = self.source.replace(
            VIEWER_PUSH,
            "request.get(`${repoUrl}/info/refs?service=git-receive-pack`)",
        )
        self.assertNotEqual(planted, self.source)
        self.assertEqual(receive_pack_probes(planted), [MEMBERS_TITLE])

    def test_the_store_token_check_runs_beside_its_rotation(self) -> None:
        self.assertEqual(
            rotation_gates(self.source),
            {"skip": True, "rotation": True},
            "only rotate store credentials mints the store token, so the test "
            "skips a deployment without Semaphore Workspaces and runs the "
            "rotation when no store token exists yet",
        )

    def test_negative_control_an_ungated_store_token_check_is_caught(self) -> None:
        body = self.bodies[TOKEN_TITLE]
        unskipped = self.source.replace(
            body, body.replace(ROTATION_SKIP, "test.skip(!enabled")
        )
        unrotated = self.source.replace(
            body,
            body.replace(ROTATION_RUN, "Promise.resolve(sem, null, ROTATION_RUN_MS"),
        )
        self.assertEqual(rotation_gates(unskipped), {"skip": False, "rotation": True})
        self.assertEqual(rotation_gates(unrotated), {"skip": True, "rotation": False})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
