from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.development.extra_mounts import (
    OVERRIDE,
    parse_mounts,
    write_mounts_override,
)
from utils.cache.yaml import load_yaml


class TestParseMounts(unittest.TestCase):
    def test_existing_absolute_directories_are_returned(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            self.assertEqual(
                parse_mounts(f"{first}, {second},"), [Path(first), Path(second)]
            )

    def test_empty_value_mounts_nothing(self) -> None:
        self.assertEqual(parse_mounts(""), [])

    def test_relative_entry_is_rejected_naming_it(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            parse_mounts("relative/dir")
        self.assertIn("relative/dir", str(ctx.exception.code))

    def test_missing_directory_is_rejected_naming_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit) as ctx:
            parse_mounts(str(Path(tmp) / "absent"))
        self.assertIn("absent", str(ctx.exception.code))


class TestWriteMountsOverride(unittest.TestCase):
    def test_each_directory_is_bound_read_only_at_its_own_path(self) -> None:
        with tempfile.TemporaryDirectory() as repo:
            relative = write_mounts_override(
                Path(repo), [Path("/srv/gui")], service="infinito", override=OVERRIDE
            )
            override = load_yaml(Path(repo) / relative)
        self.assertEqual(relative, OVERRIDE)
        self.assertEqual(
            override,
            {
                "services": {
                    "infinito": {
                        "volumes": [
                            {
                                "type": "bind",
                                "source": "/srv/gui",
                                "target": "/srv/gui",
                                "read_only": True,
                            }
                        ]
                    }
                }
            },
        )

    def test_the_infra_runner_gets_only_its_own_override(self) -> None:
        with tempfile.TemporaryDirectory() as repo:
            relative = write_mounts_override(
                Path(repo),
                [Path("/srv/a"), Path("/srv/b")],
                service="runner",
                override="build/compose/infra-roots.override.yml",
            )
            override = load_yaml(Path(repo) / relative)
            self.assertFalse((Path(repo) / OVERRIDE).exists())
        self.assertEqual(list(override["services"]), ["runner"])
        self.assertEqual(
            [volume["target"] for volume in override["services"]["runner"]["volumes"]],
            ["/srv/a", "/srv/b"],
        )


if __name__ == "__main__":
    unittest.main()
