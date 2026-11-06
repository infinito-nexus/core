import tempfile
import unittest
from pathlib import Path

from utils.roles.garbage_collector import (
    GARBAGE_COLLECTOR_INSTALLER,
    GARBAGE_COLLECTOR_SCRIPT,
    UNBOUNDED_EXEC,
    garbage_collector_findings,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TASKS_MAIN

VALID_SCRIPT = """#!/bin/bash
case "${1:-}" in
routine) age=2 ;;
pressure) age=1 ;;
*)
	echo "usage" >&2
	exit 64
	;;
esac
"""

BOUNDED_EXEC = """container exec -u git "${GARBAGE_COLLECTOR_ADDRESS:?}" timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT:?}" \\
	find /data -mmin "+${age}" -delete
"""
UNBOUNDED_EXEC_LINE = """# container exec in a comment is no command
container exec -u git "${GARBAGE_COLLECTOR_ADDRESS:?}" \\
	find /data -mmin "+${age}" -delete
"""

INSTALLER_TASK = f"""---
- include_tasks: "{{{{ lookup('path_absolute', '{GARBAGE_COLLECTOR_INSTALLER}') }}}}"
"""


class GcFindingsCase:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.role = Path(self._tmp.name) / "web-app-demo"
        (self.role / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def declare(self, block: str, *, head: str = "") -> None:
        (self.role / ROLE_FILE_META_SERVICES).write_text(
            "---\n" + head + "demo:\n  lifecycle: beta\n" + block
        )

    def ship(self, body: str = VALID_SCRIPT, mode: int = 0o755) -> None:
        script = self.role / GARBAGE_COLLECTOR_SCRIPT
        script.parent.mkdir(parents=True)
        script.write_text(body)
        script.chmod(mode)

    def register(self) -> None:
        tasks = self.role / ROLE_FILE_TASKS_MAIN
        tasks.parent.mkdir()
        tasks.write_text(INSTALLER_TASK)

    def findings(self, *, required: bool = True) -> list[str]:
        return garbage_collector_findings(self.role, required=required)


class TestGcDeclarationsThatPass(GcFindingsCase, unittest.TestCase):
    def test_a_nocheck_marker_with_a_reason_passes(self) -> None:
        self.declare(
            "", head="# nocheck: garbage-collector-required  static files only\n"
        )
        self.assertEqual(self.findings(), [])

    def test_native_naming_its_setting_passes(self) -> None:
        self.declare(
            '  garbage_collector:\n    type: native\n    setting: "RETENTION_DAYS"\n'
        )
        self.assertEqual(self.findings(), [])

    def test_a_registered_script_honouring_the_contract_passes(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship()
        self.register()
        self.assertEqual(self.findings(), [])

    def test_a_container_exec_under_the_in_container_timeout_passes(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship(VALID_SCRIPT + BOUNDED_EXEC)
        self.register()
        self.assertEqual(self.findings(), [])

    def test_an_optional_role_without_declaration_passes(self) -> None:
        self.declare("")
        self.assertEqual(self.findings(required=False), [])


class TestGcDeclarationsThatFail(GcFindingsCase, unittest.TestCase):
    def test_a_missing_declaration_fails(self) -> None:
        self.declare("")
        self.assertEqual(self.findings(), ["declares no garbage_collector"])

    def test_an_unknown_type_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: sometimes\n")
        self.assertIn("garbage_collector.type must be one of", self.findings()[0])

    def test_the_retired_none_type_fails(self) -> None:
        self.declare('  garbage_collector:\n    type: none\n    reason: "nothing"\n')
        self.assertIn(
            "garbage_collector.type must be one of script, native", self.findings()[0]
        )

    def test_a_bare_nocheck_marker_fails(self) -> None:
        self.declare("", head="# nocheck: garbage-collector-required\n")
        self.assertEqual(
            self.findings(), ["nocheck: garbage-collector-required names no reason"]
        )

    def test_a_declaration_beside_a_nocheck_marker_fails(self) -> None:
        self.declare(
            '  garbage_collector:\n    type: native\n    setting: "RETENTION_DAYS"\n',
            head="# nocheck: garbage-collector-required  static files only\n",
        )
        self.assertEqual(
            self.findings(),
            [
                "declares garbage_collector and carries nocheck: garbage-collector-required"
            ],
        )

    def test_a_nocheck_marker_does_not_excuse_a_shipped_script(self) -> None:
        self.declare(
            "", head="# nocheck: garbage-collector-required  static files only\n"
        )
        self.ship()
        self.assertEqual(
            self.findings(),
            [
                "ships files/shell/garbage_collector.sh but declares no garbage_collector"
            ],
        )

    def test_native_without_a_setting_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: native\n")
        self.assertEqual(
            self.findings(),
            [
                "garbage_collector.type native needs a non-empty garbage_collector.setting"
            ],
        )

    def test_script_without_a_garbage_collector_script_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.register()
        self.assertEqual(
            self.findings(),
            [
                "declares garbage_collector.type script but ships no files/shell/garbage_collector.sh"
            ],
        )

    def test_a_garbage_collector_script_under_another_type_fails(self) -> None:
        self.declare(
            '  garbage_collector:\n    type: native\n    setting: "RETENTION_DAYS"\n'
        )
        self.ship()
        self.assertEqual(
            self.findings(),
            [
                "ships files/shell/garbage_collector.sh but declares garbage_collector.type native"
            ],
        )

    def test_a_garbage_collector_script_without_declaration_fails_even_when_optional(
        self,
    ) -> None:
        self.declare("")
        self.ship()
        self.assertEqual(
            self.findings(required=False),
            [
                "ships files/shell/garbage_collector.sh but declares no garbage_collector"
            ],
        )

    def test_a_script_accepting_any_mode_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship('#!/bin/bash\ncase "$1" in\nroutine) ;;\npressure) ;;\n*) ;;\nesac\n')
        self.register()
        self.assertEqual(
            self.findings(),
            ["garbage_collector.sh's '*)' branch does not exit non-zero"],
        )

    def test_a_script_missing_the_pressure_mode_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship(VALID_SCRIPT.replace("pressure) age=1 ;;\n", ""))
        self.register()
        self.assertEqual(
            self.findings(),
            ["garbage_collector.sh has no case branch for mode 'pressure'"],
        )

    def test_a_script_that_is_not_executable_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship(mode=0o644)
        self.register()
        self.assertEqual(self.findings(), ["garbage_collector.sh is not executable"])

    def test_a_container_exec_without_the_in_container_timeout_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship(VALID_SCRIPT + UNBOUNDED_EXEC_LINE)
        self.register()
        self.assertEqual(self.findings(), [UNBOUNDED_EXEC])

    def test_an_unregistered_script_fails(self) -> None:
        self.declare("  garbage_collector:\n    type: script\n")
        self.ship()
        self.assertEqual(
            self.findings(),
            [
                f"declares garbage_collector.type script but no task includes {GARBAGE_COLLECTOR_INSTALLER}"
            ],
        )


if __name__ == "__main__":
    unittest.main()
