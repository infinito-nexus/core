from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import cli.contributing.role.skeleton.samples.__main__ as samples
from cli.administration.roles.marker import is_placed
from cli.contributing.role.skeleton.manifest import DATABASES, KINDS, LOGINS, validate
from utils.cache.yaml import load_yaml_any


def _manifests():
    return [
        validate(load_yaml_any(str(path)))[0]
        for path in sorted(samples.SAMPLES_DIR.glob("*.yml"))
    ]


class TestSamples(unittest.TestCase):
    def test_every_sample_validates(self):
        for path in sorted(samples.SAMPLES_DIR.glob("*.yml")):
            with self.subTest(sample=path.name):
                self.assertEqual([], validate(load_yaml_any(str(path)))[1])

    def test_the_samples_cover_every_database_choice(self):
        self.assertEqual(
            set(DATABASES), {manifest.database for manifest in _manifests()}
        )

    def test_the_samples_cover_every_login_choice(self):
        self.assertEqual(set(LOGINS), {manifest.login for manifest in _manifests()})

    def test_the_samples_cover_every_kind(self):
        self.assertEqual(set(KINDS), {manifest.kind for manifest in _manifests()})


class TestPlace(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roles = Path(tmp.name)

    def test_a_placed_sample_carries_the_pull_marker(self):
        sample = min(samples.SAMPLES_DIR.glob("*.yml"))
        self.assertTrue(is_placed(samples.place(sample, self.roles)))

    def test_main_prints_every_placed_role(self):
        with (
            mock.patch.object(samples, "ROLES_DIR", self.roles),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(0, samples.main([]))
        self.assertEqual(
            sorted(str(path) for path in self.roles.iterdir()),
            sorted(out.getvalue().splitlines()),
        )


if __name__ == "__main__":
    unittest.main()
