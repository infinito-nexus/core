import unittest

from plugins.filter.docker.build_digest import docker_build_digest

BUILD = """\
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        VERSION: "11.11.0"
    ports:
      - "8065:8065"
  db:
    image: postgres:18
"""


class TestDockerBuildDigest(unittest.TestCase):
    def test_a_change_outside_the_build_sections_keeps_the_digest(self):
        self.assertEqual(
            docker_build_digest(BUILD),
            docker_build_digest(BUILD.replace("8065:8065", "9000:8065")),
        )

    def test_a_changed_build_argument_changes_the_digest(self):
        self.assertNotEqual(
            docker_build_digest(BUILD),
            docker_build_digest(BUILD.replace("11.11.0", "11.12.0")),
        )

    def test_a_project_without_builds_has_one_constant_digest(self):
        self.assertEqual(
            docker_build_digest("services:\n  db:\n    image: postgres:18\n"),
            docker_build_digest("services:\n  web:\n    image: nginx:1.29\n"),
        )


if __name__ == "__main__":
    unittest.main()
