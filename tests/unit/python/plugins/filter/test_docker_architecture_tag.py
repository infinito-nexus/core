import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.docker.architecture_tag import docker_architecture_tag
from utils.docker.image.architecture_tags import architecture_tags

COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
VERSION = f"main-{COMMIT}"
REWRITES = {"arm64": {"prefix": "main-", "replacement": "main-arm64-"}}


class TestDockerArchitectureTag(unittest.TestCase):
    def test_arm64_pulls_the_rewritten_tag_of_the_same_commit(self) -> None:
        self.assertEqual(
            f"main-arm64-{COMMIT}", docker_architecture_tag(VERSION, "arm64", REWRITES)
        )

    def test_an_architecture_without_a_rewrite_pulls_the_pin(self) -> None:
        self.assertEqual(VERSION, docker_architecture_tag(VERSION, "amd64", REWRITES))

    def test_a_service_without_rewrites_pulls_the_pin_everywhere(self) -> None:
        for rewrites in (None, {}):
            with self.subTest(rewrites=rewrites):
                self.assertEqual(
                    VERSION, docker_architecture_tag(VERSION, "arm64", rewrites)
                )

    def test_a_bump_to_a_tag_without_the_prefix_fails_instead_of_guessing(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            docker_architecture_tag("v1.9.6", "arm64", REWRITES)

    def test_a_malformed_rewrite_fails(self) -> None:
        for rewrites in (
            ["arm64"],
            {"arm64": "main-arm64-"},
            {"arm64": {"prefix": "main-"}},
            {"arm64": {"prefix": "", "replacement": "main-arm64-"}},
        ):
            with self.subTest(rewrites=rewrites), self.assertRaises(AnsibleFilterError):
                docker_architecture_tag(VERSION, "arm64", rewrites)

    def test_every_rewritten_architecture_gets_its_tag(self) -> None:
        self.assertEqual(
            {"arm64": f"main-arm64-{COMMIT}"}, architecture_tags(VERSION, REWRITES)
        )
        self.assertEqual({}, architecture_tags(VERSION, None))


if __name__ == "__main__":
    unittest.main()
