"""Carrying a compose flavor homeserver over to the ansible flavor."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, meta

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-matrix"
SCRIPT = ROLE / "files" / "flavor" / "ansible" / "carry_over_compose_data.sh"
TASK = ROLE / "tasks" / "flavor" / "ansible" / "01_carry_over_compose_data.yml"
MDAD_VARS = ROLE / "templates" / "flavor" / "ansible" / "vars.yml.j2"
HOMESERVER = (
    ROLE / "templates" / "flavor" / "compose" / "synapse" / "homeserver.yaml.j2"
)

FIXED: dict[str, str] = {
    "application_id": "web-app-matrix",
    "MATRIX_SERVER_NAME": "example.org",
    "MATRIX_SYNAPSE_DOMAIN": "matrix.example.org",
}

COMPOSE_KEY = "ed25519 a_CoMp c2VlZC1vZi10aGUtY29tcG9zZS1rZXk\n"
MDAD_KEY = "ed25519 a_MdAd c2VlZC1vZi10aGUtbWRhZC1rZXk\n"
MEDIA_FILE = Path("local_content") / "ab" / "cd" / "efghijklmnop"

CONTAINER_STUB = """#!/bin/sh
case "$1 $2" in
"volume ls")
\t[ -z "$STUB_FAIL_LISTING" ] || exit 1
\tname="${5#name=^}"
\tname="${name%\\$}"
\t[ ! -d "$STUB_VOLUMES/$name" ] || echo "$name"
\t;;
"volume inspect")
\t[ -d "$STUB_VOLUMES/$5" ] || exit 1
\techo "$STUB_VOLUMES/$5"
\t;;
"volume create")
\tmkdir -p "$STUB_VOLUMES/$3"
\techo "$3"
\t;;
*) exit 1 ;;
esac
"""

CHOWN_STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
"""


def _volume(application_id: str, name: str) -> dict[str, str]:
    """Answer ``lookup('volume', application_id, name)`` from meta/volumes.yml.

    Args:
        application_id: must be the role under test.
        name: the semantic volume key.
    """
    if application_id != FIXED["application_id"]:
        raise AssertionError(f"unexpected application {application_id!r}")
    entry = load_yaml(str(ROLE / ROLE_FILE_META_VOLUMES))[name]
    (target,) = {mount["target"] for mount in entry["mounts"]}
    return {"name": entry.get("name") or name, "target": target}


def _lookup(kind: str, *terms: str) -> dict[str, str]:
    if kind != "volume":
        raise AssertionError(f"unexpected lookup {kind!r}")
    return _volume(*terms)


def _environment() -> Environment:
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders ansible expressions, not markup
    env.filters["path_join"] = lambda parts: str(Path(*parts))
    env.globals["lookup"] = _lookup
    return env


def _resolve(name: str):
    if name in FIXED:
        return FIXED[name]
    value = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[name]
    return _render(value) if isinstance(value, str) else value


def _render(template: str) -> str:
    env = _environment()
    names = meta.find_undeclared_variables(env.parse(template)) - set(env.globals)
    return env.from_string(template).render({n: _resolve(n) for n in names})


def _task_environment() -> dict[str, str]:
    task = load_yaml_any(str(TASK), default_if_missing=[])[0]
    return {key: _render(value) for key, value in task["environment"].items()}


def _template_values(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    """Render the value of each top-level ``key: {{ ... }}`` line of a template.

    Args:
        path: the Jinja template to read.
        keys: the keys whose value must be rendered; a missing one fails.
    """
    found = {}
    for line in read_text(str(path)).splitlines():
        match = re.match(r'^(?P<key>[a-z_]+):\s*"?(?P<value>\{\{[^}]*\}\})"?\s*$', line)
        if match and match["key"] in keys:
            found[match["key"]] = _render(match["value"])
    missing = set(keys) - set(found)
    if missing:
        raise AssertionError(f"{path.name} sets none of {sorted(missing)}")
    return found


def _content(path: Path) -> str:
    return path.read_text()  # nocheck: cache-read tempdir fixture the script just wrote


class _CarryOverCase(unittest.TestCase):
    params: ClassVar[dict[str, str]] = _task_environment()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.volumes = self.tmp / "volumes"
        self.volumes.mkdir()
        self.log = self.tmp / "chown.log"
        self.log.touch()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("container", CONTAINER_STUB), ("chown", CHOWN_STUB)):
            stub = self.bin / name
            stub.write_text(body)
            stub.chmod(0o755)

    def _on(self, volume: str, mount: str, path: str) -> Path:
        relative = Path(self.params[path]).relative_to(self.params[mount])
        return self.volumes / self.params[volume] / relative

    def compose(self, param: str) -> Path:
        return self._on("MATRIX_COMPOSE_VOLUME", "MATRIX_COMPOSE_MOUNT", param)

    def mdad(self, param: str) -> Path:
        return self._on("MATRIX_MDAD_VOLUME", "MATRIX_MDAD_MOUNT", param)

    def seed_compose(self, *, key: bool = True, media: bool = True) -> None:
        (self.volumes / self.params["MATRIX_COMPOSE_VOLUME"]).mkdir(exist_ok=True)
        if key:
            self.compose("MATRIX_COMPOSE_SIGNING_KEY").write_text(COMPOSE_KEY)
        if media:
            media_file = self.compose("MATRIX_COMPOSE_MEDIA_STORE") / MEDIA_FILE
            media_file.parent.mkdir(parents=True)
            media_file.write_text("compose media")

    def run_script(self, *, fail_listing: bool = False) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            **self.params,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STUB_VOLUMES": str(self.volumes),
            "STUB_LOG": str(self.log),
            "STUB_FAIL_LISTING": "1" if fail_listing else "",
        }
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class TestAFreshHostIsLeftAlone(_CarryOverCase):
    def test_no_compose_volume_is_skipped(self) -> None:
        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SKIPPED", result.stdout)
        self.assertNotIn("COPIED", result.stdout)

    def test_no_compose_volume_creates_no_mdad_volume(self) -> None:
        self.run_script()

        self.assertFalse((self.volumes / self.params["MATRIX_MDAD_VOLUME"]).exists())

    def test_an_empty_compose_volume_creates_no_mdad_volume(self) -> None:
        self.seed_compose(key=False, media=False)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.volumes / self.params["MATRIX_MDAD_VOLUME"]).exists())


class TestASwitchCarriesTheHomeserverOver(_CarryOverCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_compose()

    def test_the_signing_key_keeps_its_key_id(self) -> None:
        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_content(self.mdad("MATRIX_MDAD_SIGNING_KEY")), COMPOSE_KEY)
        self.assertIn("COPIED: signing key ed25519:a_CoMp", result.stdout)

    def test_the_media_store_is_copied(self) -> None:
        self.run_script()

        self.assertEqual(
            _content(self.mdad("MATRIX_MDAD_MEDIA_STORE") / MEDIA_FILE),
            "compose media",
        )

    def test_the_compose_volume_keeps_its_data(self) -> None:
        self.run_script()

        self.assertEqual(
            _content(self.compose("MATRIX_COMPOSE_SIGNING_KEY")), COMPOSE_KEY
        )
        self.assertTrue(
            (self.compose("MATRIX_COMPOSE_MEDIA_STORE") / MEDIA_FILE).is_file()
        )

    def test_no_staging_copy_is_left_behind(self) -> None:
        self.run_script()

        for param in ("MATRIX_MDAD_SIGNING_KEY", "MATRIX_MDAD_MEDIA_STORE"):
            with self.subTest(param=param):
                staging = self.mdad(param).with_name(
                    self.mdad(param).name + ".carry-over"
                )
                self.assertFalse(staging.exists())

    def test_the_copies_are_handed_to_the_synapse_user(self) -> None:
        self.run_script()

        owner = (
            f"{self.params['MATRIX_SYNAPSE_UID']}:{self.params['MATRIX_SYNAPSE_GID']}"
        )
        calls = _content(self.log).splitlines()
        key = f"{self.mdad('MATRIX_MDAD_SIGNING_KEY')}.carry-over"
        media = f"{self.mdad('MATRIX_MDAD_MEDIA_STORE')}.carry-over"
        self.assertIn(f"-- {owner} {key}", calls)
        self.assertIn(f"-R -- {owner} {media}", calls)
        self.assertIn(
            f"-- {owner} {self.mdad('MATRIX_MDAD_SIGNING_KEY').parent}", calls
        )

    def test_a_second_run_changes_nothing(self) -> None:
        self.run_script()

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("COPIED", result.stdout)


class TestExistingMdadDataIsNeverOverwritten(_CarryOverCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_compose()

    def test_an_mdad_signing_key_is_kept(self) -> None:
        target = self.mdad("MATRIX_MDAD_SIGNING_KEY")
        target.parent.mkdir(parents=True)
        target.write_text(MDAD_KEY)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_content(target), MDAD_KEY)
        self.assertIn("KEPT", result.stdout)
        self.assertIn("ed25519:a_MdAd", result.stdout)
        self.assertIn("ed25519:a_CoMp", result.stdout)

    def test_mdad_media_is_kept(self) -> None:
        own = self.mdad("MATRIX_MDAD_MEDIA_STORE") / "local_content" / "mdad"
        own.parent.mkdir(parents=True)
        own.write_text("mdad media")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_content(own), "mdad media")
        self.assertFalse((self.mdad("MATRIX_MDAD_MEDIA_STORE") / MEDIA_FILE).exists())

    def test_an_empty_media_store_mdad_created_is_filled(self) -> None:
        self.mdad("MATRIX_MDAD_MEDIA_STORE").mkdir(parents=True)

        self.run_script()

        self.assertTrue((self.mdad("MATRIX_MDAD_MEDIA_STORE") / MEDIA_FILE).is_file())

    def test_a_staging_copy_of_an_interrupted_run_is_replaced(self) -> None:
        target = self.mdad("MATRIX_MDAD_MEDIA_STORE")
        stale = target.with_name(target.name + ".carry-over") / "half-copied"
        stale.parent.mkdir(parents=True)
        stale.write_text("partial")

        self.run_script()

        self.assertTrue((target / MEDIA_FILE).is_file())
        self.assertFalse((target / "half-copied").exists())
        self.assertFalse(stale.parent.exists())


class TestTheScriptFailsLoudly(_CarryOverCase):
    def test_a_failing_volume_listing_is_not_read_as_a_fresh_host(self) -> None:
        self.seed_compose()

        result = self.run_script(fail_listing=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SKIPPED", result.stdout)

    def test_it_refuses_to_run_without_its_parameters(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env={"PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MATRIX_COMPOSE_VOLUME", result.stderr)


class TestTheScriptReadsAndWritesWhereSynapseDoes(unittest.TestCase):
    params: ClassVar[dict[str, str]] = _task_environment()

    def test_mdad_reads_the_signing_key_where_it_is_copied_to(self) -> None:
        mdad = _template_values(
            MDAD_VARS, ("matrix_synapse_config_dir_path", "matrix_server_fqn_matrix")
        )

        self.assertEqual(
            str(
                Path(mdad["matrix_synapse_config_dir_path"])
                / f"{mdad['matrix_server_fqn_matrix']}.signing.key"
            ),
            self.params["MATRIX_MDAD_SIGNING_KEY"],
        )

    def test_mdad_serves_the_media_store_it_is_copied_to(self) -> None:
        mdad = _template_values(
            MDAD_VARS,
            ("matrix_synapse_storage_path", "matrix_synapse_media_store_path"),
        )

        self.assertEqual(
            mdad["matrix_synapse_media_store_path"],
            self.params["MATRIX_MDAD_MEDIA_STORE"],
        )
        self.assertEqual(
            str(Path(mdad["matrix_synapse_media_store_path"]).parent),
            mdad["matrix_synapse_storage_path"],
        )

    def test_the_copies_belong_to_the_user_mdad_runs_synapse_as(self) -> None:
        mdad = _template_values(MDAD_VARS, ("matrix_user_uid", "matrix_user_gid"))

        self.assertEqual(
            (self.params["MATRIX_SYNAPSE_UID"], self.params["MATRIX_SYNAPSE_GID"]),
            (mdad["matrix_user_uid"], mdad["matrix_user_gid"]),
        )

    def test_mdad_keeps_its_data_on_the_volume_it_is_copied_to(self) -> None:
        mdad = _template_values(MDAD_VARS, ("matrix_base_data_path",))

        self.assertEqual(
            mdad["matrix_base_data_path"], self.params["MATRIX_MDAD_MOUNT"]
        )

    def test_the_compose_homeserver_wrote_where_it_is_copied_from(self) -> None:
        compose = _template_values(HOMESERVER, ("signing_key_path", "media_store_path"))

        self.assertEqual(
            compose["signing_key_path"], self.params["MATRIX_COMPOSE_SIGNING_KEY"]
        )
        self.assertEqual(
            compose["media_store_path"], self.params["MATRIX_COMPOSE_MEDIA_STORE"]
        )


class TestTheCarryOverRunsBeforeMdadStarts(unittest.TestCase):
    def test_it_precedes_every_step_that_can_start_the_mdad_playbook(self) -> None:
        steps = [
            task["include_tasks"]
            for task in load_yaml_any(
                str(ROLE / "tasks" / "flavor" / "ansible" / "main.yml"),
                default_if_missing=[],
            )
        ]

        position = steps.index(TASK.name)
        for starter in ("03_render_inventory.yml", "05_run_playbook.yml"):
            with self.subTest(starter=starter):
                self.assertLess(position, steps.index(starter))


if __name__ == "__main__":
    unittest.main()
