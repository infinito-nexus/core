import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SPEC = (
    PROJECT_ROOT
    / "roles"
    / "web-app-gitlab"
    / "files"
    / "playwright"
    / "test-2fa-enrollment.js"
)
PROBE_USERNAME = re.compile(r"\busername:\s*`([^`]+)`")
GROUP_PATH = re.compile(r"/api/v4/groups`.*?\bpath:\s*`([^`]+)`", re.DOTALL)


def namespace_findings(source: str) -> list[str]:
    """
    Args:
        source: text of the GitLab 2FA enrollment spec.

    Returns:
        One finding per group path that is missing or equal to a probe username.
    """
    usernames = set(PROBE_USERNAME.findall(source))
    paths = GROUP_PATH.findall(source)
    findings = [] if usernames else ["no probe username template found"]
    findings.extend([] if paths else ["no group path template found"])
    findings.extend(
        f"group path {path} is the probe username"
        for path in paths
        if path in usernames
    )
    return findings


class TestTheProbeGroupNamespace(unittest.TestCase):
    def test_the_group_path_differs_from_the_probe_username(self) -> None:
        self.assertEqual(
            namespace_findings(read_text(str(SPEC))),
            [],
            "GitLab keeps users and groups in one namespace path space, so a group path equal to the probe username answers 400 path has already been taken",
        )

    def test_control_a_group_path_equal_to_the_username_fails(self) -> None:
        source = read_text(str(SPEC))
        username = PROBE_USERNAME.search(source).group(1)
        path = GROUP_PATH.search(source).group(1)
        planted = source.replace(f"path: `{path}`", f"path: `{username}`", 1)
        self.assertNotEqual(namespace_findings(planted), [])


if __name__ == "__main__":
    unittest.main()
