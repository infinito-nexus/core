from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cli.contributing.role.skeleton.__main__ as skeleton_main
from cli.contributing.role.skeleton.render import RenderError
from utils.cache import PROJECT_ROOT

MANIFEST = {
    "name": "notes",
    "description": "Self-hosted note taking web application",
    "homepage": "https://example.org/",
    "license": "MIT",
    "image": "ghcr.io/example/notes:1.2.3",
    "port": 8080,
}
ALLOWED_THIRD_PARTY = {"cli", "utils", "jinja2", "markupsafe", "yaml", "_yaml"}
SITE_HOOKS = {"sitecustomize", "usercustomize"}
SITE_HOOK_PREFIXES = ("_", "sphinxcontrib", "cython")


def _run(argv: list[str], stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(stdin)),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = skeleton_main.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestSchema(unittest.TestCase):
    def test_schema_prints_every_field_with_name_help_and_type(self):
        _, out, _ = _run(["schema"])
        entries = json.loads(out)
        self.assertTrue(
            all({"name", "help", "type", "kinds"} <= set(entry) for entry in entries)
        )

    def test_schema_types_are_string_or_integer(self):
        _, out, _ = _run(["schema"])
        self.assertEqual(
            {"string", "integer"}, {entry["type"] for entry in json.loads(out)}
        )

    def test_schema_marks_choices_multiple_and_default(self):
        _, out, _ = _run(["schema"])
        features = next(
            entry for entry in json.loads(out) if entry["name"] == "features"
        )
        self.assertEqual(
            (["email", "redis"], True, []),
            (features["choices"], features["multiple"], features["default"]),
        )


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name)

    def test_render_prints_only_the_role_directory(self):
        role_dir = self.target / "web-app-cst-notes"
        with mock.patch.object(skeleton_main, "render", return_value=role_dir):
            code, out, err = _run(
                ["render", "--target", str(self.target)], json.dumps(MANIFEST)
            )
        self.assertEqual((0, f"{role_dir}\n", ""), (code, out, err))

    def test_a_yaml_manifest_is_accepted(self):
        text = "".join(
            f"{key}: {json.dumps(value)}\n" for key, value in MANIFEST.items()
        )
        with mock.patch.object(
            skeleton_main, "render", return_value=self.target
        ) as render:
            _run(["render", "--target", str(self.target)], text)
        self.assertEqual("notes", render.call_args.args[0].name)

    def test_force_reaches_the_renderer(self):
        with mock.patch.object(
            skeleton_main, "render", return_value=self.target
        ) as render:
            _run(
                ["render", "--target", str(self.target), "--force"],
                json.dumps(MANIFEST),
            )
        self.assertTrue(render.call_args.kwargs["force"])

    def test_an_invalid_manifest_exits_2_with_one_line_per_error(self):
        code, out, err = _run(
            ["render", "--target", str(self.target)],
            json.dumps({**MANIFEST, "port": 0, "database": "sqlite"}),
        )
        self.assertEqual((2, ""), (code, out))
        self.assertEqual(
            ["port", "database"], [line.split(":", 1)[0] for line in err.splitlines()]
        )

    def test_an_invalid_manifest_writes_nothing(self):
        _run(
            ["render", "--target", str(self.target)],
            json.dumps({**MANIFEST, "port": 0}),
        )
        self.assertEqual([], list(self.target.iterdir()))

    def test_unparsable_input_exits_2(self):
        code, _, err = _run(["render", "--target", str(self.target)], "name: [")
        self.assertEqual((2, 1), (code, len(err.splitlines())))

    def test_a_render_error_exits_2_with_its_lines(self):
        error = RenderError(
            ["name: entity name 'notes' collides with the in-tree role web-app-notes"]
        )
        with mock.patch.object(skeleton_main, "render", side_effect=error):
            code, _, err = _run(
                ["render", "--target", str(self.target)], json.dumps(MANIFEST)
            )
        self.assertEqual((2, f"{error.errors[0]}\n"), (code, err))


class TestDependencies(unittest.TestCase):
    def test_the_renderer_imports_only_the_standard_library_jinja2_and_pyyaml(self):
        probe = (
            "import sys, cli.contributing.role.skeleton.__main__; "
            "print(' '.join(sorted({name.split('.')[0] for name in sys.modules})))"
        )
        loaded = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        foreign = {
            name
            for name in loaded
            if name not in sys.stdlib_module_names
            and name not in ALLOWED_THIRD_PARTY
            and name not in SITE_HOOKS
            and not name.startswith(SITE_HOOK_PREFIXES)
        }
        self.assertEqual(set(), foreign)


if __name__ == "__main__":
    unittest.main()
