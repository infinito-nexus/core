import unittest

from cli.contributing.changelog.extract.pins import (
    collection_pins,
    compare,
    dockerfile_pins,
    meta_pins,
    pyproject_pins,
    url_version,
)


class TestReaders(unittest.TestCase):
    def test_meta_pins_skip_jinja_and_name_list_items(self) -> None:
        text = (
            "a:\n  version: 1.0\n  image_ref: '{{ X }}'\n"
            "plugins:\n  - name: oidc\n    tag: v2.0.0\n"
        )
        self.assertEqual(
            meta_pins(text), {"a.version": "1.0", "plugins.oidc.tag": "v2.0.0"}
        )

    def test_collection_pins(self) -> None:
        text = (
            "collections:\n  - name: ansible.posix\n    version: 2.2.2\n  - name: x\n"
        )
        self.assertEqual(collection_pins(text), {"ansible.posix": "2.2.2"})

    def test_pyproject_pins_read_specifiers_and_urls(self) -> None:
        text = (
            '[build-system]\nrequires = ["setuptools>=68"]\n'
            '[project]\nversion = "16.2.3"\ndependencies = ["Babel", "baudolo==8.0.0"]\n'
            '[project.optional-dependencies]\ndeploy = ["gen @ https://x.invalid/v0.3.0.zip"]\n'
        )
        self.assertEqual(
            pyproject_pins(text),
            {"setuptools": "68", "baudolo": "8.0.0", "gen": "v0.3.0"},
        )

    def test_dockerfile_pins_skip_build_arguments(self) -> None:
        text = (
            "ARG BASE_VERSION\nFROM ${BASE}:${BASE_VERSION}\n"
            "ARG TOOL_VERSION=1.4.0\nENV LC_ALL=C.UTF-8\n"
            "RUN pip install \\\n  oauthlib==3.2.2\n"
            "RUN curl -O https://x.invalid/download/v2.1.0/tool.tgz\n"
        )
        self.assertEqual(
            dockerfile_pins(text),
            {
                "TOOL_VERSION": "1.4.0",
                "oauthlib": "3.2.2",
                "https://x.invalid/download/*/tool.tgz": "v2.1.0",
            },
        )

    def test_url_version_reads_the_first_url_only(self) -> None:
        self.assertEqual(url_version("see https://x.invalid/a-1.2.3.tar.gz"), "1.2.3")
        self.assertIsNone(url_version("version 1.2.3 without a link"))


class TestCompare(unittest.TestCase):
    def test_changed_renamed_and_added(self) -> None:
        old = {"a.version": "1.0", "b.webui.version": "v1.0", "c.version": "2.0"}
        new = {"a.version": "1.1", "b.web.version": "v2.0", "d.version": "3.0"}
        self.assertEqual(
            compare(old, new),
            [
                ("a.version", None, "1.0", "1.1"),
                ("b.web.version", "b.webui.version", "v1.0", "v2.0"),
                ("d.version", None, None, "3.0"),
            ],
        )

    def test_a_pin_that_only_left_or_kept_its_value_is_no_jump(self) -> None:
        self.assertEqual(compare({"a.version": "1.0"}, {}), [])
        self.assertEqual(compare({"a.old": "v1.0"}, {"a.new": "v1.0"}), [])


if __name__ == "__main__":
    unittest.main()
