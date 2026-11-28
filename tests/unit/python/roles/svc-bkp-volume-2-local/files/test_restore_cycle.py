from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local"
SCRIPT = ROLE / "files" / "test" / "restore_cycle.sh"
TEST_ENV = ROLE / "templates" / "test.env.j2"
VARS = ROLE / ROLE_FILE_VARS_MAIN
ENV_KEY = "BKP_TEST_VOLUMES_CODE_DERIVED"
APP = "app_data"
DOCS = "docs_docs_sites"
LOKI = "loki_data"
CONTAINERS = f"app|app|{APP},docs|docs|{DOCS},loki|loki|{LOKI}"
EMPTIED = "STUB-EMPTIED "
CONTAINER_STUB = r"""#!/usr/bin/env bash
rows() {
    tr ',' '\n' <<<"${STUB_CONTAINERS}" | sed '/^$/d'
}
case "$1" in
    info)
        echo inactive
        ;;
    ps)
        if [[ "$*" == *working_dir* ]]; then
            rows | awk -F'|' -v dir="${STUB_WORKDIR}" '{ print $1 "|" $2 "|" dir }'
        else
            rows | awk -F'|' '{ print $1 "|" $2 }'
        fi
        ;;
    inspect)
        if [[ "$4" != "-f" ]]; then
            exit 1
        fi
        case "$5" in
            *Mounts*) rows | awk -F'|' -v name="$6" '$1 == name { print $3 }' ;;
            *NetworkSettings*) echo "net " ;;
            *ExitCode*) echo "running 0 healthy" ;;
            *State.Status*) echo exited ;;
            *) exit 64 ;;
        esac
        ;;
    run)
        src="${4#*src=}"
        echo "STUB-EMPTIED ${src%%,*}"
        ;;
    volume)
        ;;
    image)
        [[ -z "${STUB_IMAGE_MISSING}" ]]
        ;;
    pull)
        echo STUB-PULLED >&2
        [[ -z "${STUB_PULL_FAILS}" ]]
        ;;
    *)
        exit 64
        ;;
esac
"""
COMPOSE_STUB = "#!/usr/bin/env bash\nexit 0\n"
SLEEP_STUB = "#!/usr/bin/env bash\necho STUB-SLEPT >&2\n"
LOCAL, REACHABLE, DOWN = "local", "reachable", "down"
REGISTRY = {
    LOCAL: {"STUB_IMAGE_MISSING": "", "STUB_PULL_FAILS": ""},
    REACHABLE: {"STUB_IMAGE_MISSING": "1", "STUB_PULL_FAILS": ""},
    DOWN: {"STUB_IMAGE_MISSING": "1", "STUB_PULL_FAILS": "1"},
}
STUBS = (
    ("container", CONTAINER_STUB),
    ("compose", COMPOSE_STUB),
    ("sleep", SLEEP_STUB),
)


def _drill(code_derived: str | None, registry: str) -> subprocess.CompletedProcess[str]:
    """
    Args:
        code_derived: the value of BKP_TEST_VOLUMES_CODE_DERIVED, or None to
            leave it unset.
        registry: LOCAL when the scratch image is already on the host,
            REACHABLE when it must be pulled, DOWN when every pull fails.

    Returns:
        The finished drill.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in STUBS:
            stub = bin_dir / name
            stub.write_text(body, encoding="utf-8")
            stub.chmod(0o755)
        checkout = root / "checkout"
        (checkout / "cli" / "administration" / "recover").mkdir(parents=True)
        workdir = root / "compose"
        workdir.mkdir()
        (root / "repo" / "gen" / APP / "files").mkdir(parents=True)
        env = {key: value for key, value in os.environ.items() if key != ENV_KEY}
        env.update(
            {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_CONTAINERS": CONTAINERS,
                "STUB_WORKDIR": str(workdir),
                "BKP_TEST_HEALTH_TIMEOUT": "5",
                "BKP_TEST_PYTHON": "true",
                "BKP_TEST_REPO_ROOT": str(checkout),
                "BKP_TEST_SCRATCH_IMAGE": "scratch:stub",
                "BKP_TEST_WORKSPACES": "false",
                "DR_TOKEN": "dr-stub",
                "REPO_DIR": str(root / "repo"),
                "NEWEST_GENERATION": "gen",
                **REGISTRY[registry],
            }
        )
        if code_derived is not None:
            env[ENV_KEY] = code_derived
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


def _emptied(result: subprocess.CompletedProcess[str]) -> list[str]:
    return sorted(
        line.removeprefix(EMPTIED)
        for line in result.stdout.splitlines()
        if line.startswith(EMPTIED)
    )


class TestCodeDerivedVolumes(unittest.TestCase):
    def _passed(self, code_derived: str) -> subprocess.CompletedProcess[str]:
        result = _drill(code_derived, LOCAL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_a_code_derived_volume_is_kept(self) -> None:
        result = self._passed(DOCS)
        self.assertEqual(_emptied(result), [APP, LOKI])
        self.assertIn(
            f"OK: 1 volume(s) derived from code are kept: {DOCS};", result.stdout
        )

    def test_a_plain_backup_false_volume_is_still_emptied(self) -> None:
        result = self._passed(DOCS)
        self.assertIn(LOKI, _emptied(result))
        self.assertIn(f"must be rebuilt by their own service: {LOKI}", result.stdout)

    def test_negative_control_an_undeclared_volume_is_emptied(self) -> None:
        result = self._passed("")
        self.assertEqual(_emptied(result), [APP, DOCS, LOKI])
        self.assertNotIn("derived from code", result.stdout)

    def test_a_name_is_matched_whole_not_as_a_prefix(self) -> None:
        self.assertEqual(_emptied(self._passed("docs,sites")), [APP, DOCS, LOKI])

    def test_several_names_are_split_on_commas(self) -> None:
        self.assertEqual(_emptied(self._passed(f"{LOKI},{DOCS}")), [APP])

    def test_an_unset_list_fails_before_the_teardown(self) -> None:
        result = _drill(None, LOCAL)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(_emptied(result), [])
        self.assertNotIn("Stopping every subject", result.stdout)


class TestScratchImage(unittest.TestCase):
    def test_a_local_image_is_not_pulled(self) -> None:
        result = _drill(DOCS, LOCAL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr.count("STUB-PULLED"), 0)

    def test_a_missing_image_is_pulled_before_the_teardown(self) -> None:
        result = _drill(DOCS, REACHABLE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr.count("STUB-PULLED"), 1)
        self.assertLess(
            result.stdout.index("OK: scratch image scratch:stub is local"),
            result.stdout.index("Stopping every subject"),
        )

    def test_an_unpullable_image_fails_before_the_teardown(self) -> None:
        result = _drill(DOCS, DOWN)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr.count("STUB-PULLED"), 3)
        self.assertEqual(result.stderr.count("STUB-SLEPT"), 2)
        self.assertIn("nothing was torn down", result.stdout)
        self.assertNotIn("Stopping every subject", result.stdout)
        self.assertEqual(_emptied(result), [])


class TestWiring(unittest.TestCase):
    def test_the_env_renders_the_list_the_lookup_selects(self) -> None:
        line = next(
            line
            for line in read_text(str(TEST_ENV)).splitlines()
            if line.startswith(f"{ENV_KEY}=")
        )
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        self.assertEqual(
            env.from_string(line).render(
                BKP_VOLUME_2_LOCAL_VOLUMES_CODE_DERIVED=[DOCS, LOKI]
            ),
            f"{ENV_KEY}={DOCS},{LOKI}",
        )
        self.assertEqual(
            load_yaml_any(str(VARS))["BKP_VOLUME_2_LOCAL_VOLUMES_CODE_DERIVED"],
            "{{ lookup('backup_volume', 'derived') }}",
        )

    def test_the_docs_site_volume_is_declared_code_derived(self) -> None:
        volumes = load_yaml_any(
            str(PROJECT_ROOT / "roles" / "web-app-docs" / ROLE_FILE_META_VOLUMES)
        )
        self.assertEqual(volumes["docs_sites"].get("derived"), "code")
        self.assertIs(volumes["docs_sites"].get("backup"), False)


if __name__ == "__main__":
    unittest.main()
