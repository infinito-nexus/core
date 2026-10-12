"""Every release tag must sit on the subject the push workflow recognises.

``entry-push-latest.yml`` lets a push to main cancel the running pipeline only
when its head commit starts with the release subject pkgmgr writes. A tag on any
other subject is a release whose push queued behind an unrelated run.

Six tags between v10.1.0 and v11.6.0 sit on ``Release X.Y.Z``; the subject has
been uniform since v13.0.0, so the check starts there.
"""

import re
import subprocess
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

PUSH_ENTRY = PROJECT_ROOT / ".github" / "workflows" / "entry-push-latest.yml"
TAG_SCRIPT = PROJECT_ROOT / "scripts" / "github" / "resolve" / "release" / "tag.sh"
FIRST_UNIFORM_RELEASE = (13, 0, 0)
TAG_FORMAT = (
    "%(refname:strip=2)%00%(if)%(*objectname)%(then)%(*subject)%(else)%(subject)%(end)"
)


def release_prefix() -> str:
    match = re.search(
        r"startsWith\(github\.event\.head_commit\.message, '([^']+)'\)",
        read_text(str(PUSH_ENTRY)),
    )
    if match is None:
        raise AssertionError(f"{PUSH_ENTRY.name} no longer names a release subject")
    return match.group(1)


def release_schema() -> re.Pattern[str]:
    match = re.search(r"grep -E '([^']+)'", read_text(str(TAG_SCRIPT)))
    if match is None:
        raise AssertionError(f"{TAG_SCRIPT.name} no longer names a release tag schema")
    return re.compile(match.group(1))


def tag_subjects() -> dict[str, str]:
    out = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(PROJECT_ROOT),
            "for-each-ref",
            f"--format={TAG_FORMAT}",
            "refs/tags",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return dict(line.split("\0", 1) for line in out.splitlines())


def version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag[1:].split("."))


class TestReleaseTagCommitSubject(unittest.TestCase):
    def test_every_release_tag_sits_on_a_release_subject(self) -> None:
        prefix = release_prefix()
        schema = release_schema()
        releases = {
            tag: subject
            for tag, subject in tag_subjects().items()
            if schema.search(tag) and version(tag) >= FIRST_UNIFORM_RELEASE
        }
        if not releases:
            self.skipTest(
                f"no release tag from v{'.'.join(map(str, FIRST_UNIFORM_RELEASE))} "
                "on in this checkout; forks and tagless clones carry none"
            )
        for tag, subject in sorted(releases.items(), key=lambda item: version(item[0])):
            with self.subTest(tag=tag):
                self.assertEqual(
                    subject,
                    f"{prefix}{tag[1:]}",
                    f"{tag} sits on a commit whose subject does not start with "
                    f"{prefix!r}: its push to main neither cancels the running "
                    "run nor matches what pkgmgr writes",
                )


if __name__ == "__main__":
    unittest.main()
