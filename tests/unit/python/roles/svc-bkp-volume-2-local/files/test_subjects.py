"""probe/subjects.sh: a volume baudolo skips is no backup subject.

baudolo skips a volume named in --volumes-no-backup-required, and one whose
running containers all run an image of --images-no-backup-required, without
leaving a trace in the generation. CI run 43777013536 (Loki #1) deployed only
docs_docs_sites and loki_data, both ``backup: false``; the forced run stamped
an empty generation and the drill, which counted every volume as a subject,
failed it with 'contains no volume payload'.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local"
TEST_DIR = ROLE / "files" / "test"
SCRIPT = TEST_DIR / "probe" / "subjects.sh"
DRILL = TEST_DIR / "test.sh"
TEST_ENV = ROLE / "templates" / "test.env.j2"
VARS = ROLE / ROLE_FILE_VARS_MAIN
LOKI_HOST = "docs_docs_sites,loki_data"
IGNORED = "registry.local:5000/grafana/promtail:3.4"
KEPT = "registry.local:5000/grafana/loki:3.4"
STUB = """#!/usr/bin/env bash
if [[ -n "${STUB_FAIL:-}" ]]; then
    exit 1
fi
rows() {
    tr ',' '\\n' <<<"${STUB_CONTAINERS:-}" | sed '/^$/d'
}
if [[ "$*" == "volume ls -q" ]]; then
    tr ',' '\\n' <<<"${STUB_VOLUMES}" | sed '/^$/d'
elif [[ "$1 $2 $3" == "ps -q --filter" && "$#" == 4 ]]; then
    rows | awk -F'|' -v volume="${4#volume=}" '$2 == volume { print $1 }'
elif [[ "$1 $2 $3" == "inspect --format {{.Config.Image}}" ]]; then
    shift 3
    for id in "$@"; do
        rows | awk -F'|' -v id="${id}" '$1 == id { print $3 }'
    done
else
    exit 64
fi
"""


def _subjects(
    volumes: str,
    declared: str,
    *,
    images: str = "",
    containers: str = "",
    fail: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the probe against a stub engine.

    Args:
        volumes: comma-separated names the stub's ``volume ls -q`` reports.
        declared: the value of BKP_TEST_VOLUMES_NO_BACKUP.
        images: the value of BKP_TEST_IMAGES_NO_BACKUP.
        containers: comma-separated ``id|volume|image`` rows, one per running
            container and mounted volume.
        fail: make the stub engine exit non-zero.

    Returns:
        The finished probe.
    """
    with tempfile.TemporaryDirectory() as bin_dir:
        stub = Path(bin_dir) / "container"
        stub.write_text(STUB, encoding="utf-8")
        stub.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_VOLUMES": volumes,
            "STUB_CONTAINERS": containers,
            "BKP_TEST_VOLUMES_NO_BACKUP": declared,
            "BKP_TEST_IMAGES_NO_BACKUP": images,
        }
        if fail:
            env["STUB_FAIL"] = "1"
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


def _listed(volumes: str, declared: str, **engine: str) -> list[str]:
    result = _subjects(volumes, declared, **engine)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.split()


class TestSubjects(unittest.TestCase):
    def test_a_host_holding_only_declared_volumes_has_no_subject(self) -> None:
        self.assertEqual(_listed(LOKI_HOST, LOKI_HOST), [])

    def test_a_host_without_volumes_has_no_subject(self) -> None:
        self.assertEqual(_listed("", ""), [])

    def test_negative_control_an_undeclared_volume_is_a_subject(self) -> None:
        self.assertEqual(_listed(LOKI_HOST, ""), ["docs_docs_sites", "loki_data"])

    def test_only_the_declared_volume_is_dropped(self) -> None:
        self.assertEqual(_listed(LOKI_HOST, "loki_data"), ["docs_docs_sites"])

    def test_a_name_is_matched_whole_not_as_a_prefix(self) -> None:
        self.assertEqual(
            _listed(LOKI_HOST, "loki,docs"), ["docs_docs_sites", "loki_data"]
        )

    def test_an_engine_failure_is_not_read_as_an_empty_host(self) -> None:
        result = _subjects(LOKI_HOST, "", fail=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "")


class TestIgnoredImages(unittest.TestCase):
    def test_a_volume_only_ignored_images_run_on_is_no_subject(self) -> None:
        self.assertEqual(
            _listed(
                "promtail_positions",
                "",
                images=IGNORED,
                containers=f"a|promtail_positions|{IGNORED},b|promtail_positions|{IGNORED}",
            ),
            [],
        )

    def test_negative_control_one_kept_image_keeps_the_volume(self) -> None:
        self.assertEqual(
            _listed(
                "loki_data",
                "",
                images=IGNORED,
                containers=f"a|loki_data|{IGNORED},b|loki_data|{KEPT}",
            ),
            ["loki_data"],
        )

    def test_a_volume_no_container_runs_on_stays_a_subject(self) -> None:
        self.assertEqual(_listed("loki_data", "", images=IGNORED), ["loki_data"])

    def test_an_image_ref_is_matched_whole_not_as_a_prefix(self) -> None:
        self.assertEqual(
            _listed(
                "loki_data",
                "",
                images="registry.local:5000/grafana/loki",
                containers=f"a|loki_data|{KEPT}",
            ),
            ["loki_data"],
        )

    def test_the_two_skips_combine(self) -> None:
        self.assertEqual(
            _listed(
                "docs_docs_sites,promtail_positions,loki_data",
                "docs_docs_sites",
                images=IGNORED,
                containers=(
                    f"a|promtail_positions|{IGNORED},"
                    f"b|loki_data|{KEPT},"
                    f"c|docs_docs_sites|{KEPT}"
                ),
            ),
            ["loki_data"],
        )


class TestWiring(unittest.TestCase):
    def _rendered(self, key: str, **variables: list[str]) -> str:
        line = next(
            line
            for line in read_text(str(TEST_ENV)).splitlines()
            if line.startswith(f"{key}=")
        )
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        return env.from_string(line).render(**variables)

    def test_the_drill_reads_the_volume_list_baudolo_gets(self) -> None:
        self.assertEqual(
            self._rendered(
                "BKP_TEST_VOLUMES_NO_BACKUP",
                BKP_VOLUME_2_LOCAL_VOLUMES_DISABLED=["docs_docs_sites", "loki_data"],
            ),
            f"BKP_TEST_VOLUMES_NO_BACKUP={LOKI_HOST}",
        )
        self.assertIn(
            "--volumes-no-backup-required {{ BKP_VOLUME_2_LOCAL_VOLUMES_DISABLED",
            read_text(str(VARS)),
        )

    def test_the_drill_reads_the_image_list_baudolo_gets(self) -> None:
        self.assertEqual(
            self._rendered(
                "BKP_TEST_IMAGES_NO_BACKUP",
                BKP_VOLUME_2_LOCAL_DISABLED=[IGNORED, KEPT],
            ),
            f"BKP_TEST_IMAGES_NO_BACKUP={IGNORED},{KEPT}",
        )
        self.assertIn(
            "--images-no-backup-required {{ BKP_VOLUME_2_LOCAL_DISABLED",
            read_text(str(VARS)),
        )

    def test_the_drill_judges_an_empty_generation_by_the_probe(self) -> None:
        drill = read_text(str(DRILL))
        self.assertIn('SUBJECTS="$(bash "${DIR}/probe/subjects.sh")"', drill)
        self.assertIn('if [[ -z "${SUBJECTS}" ]]; then', drill)
        self.assertNotIn("COMPOSE_CONTAINERS", drill)


if __name__ == "__main__":
    unittest.main()
