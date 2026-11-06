import tempfile
import unittest
from pathlib import Path

from utils.roles.gc import GC_INSTALLER, GC_SCRIPT, UNBOUNDED_EXEC, gc_findings
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

BOUNDED_EXEC = """container exec -u git "${GC_ADDRESS:?}" timeout "${GC_APP_TIMEOUT:?}" \\
	find /data -mmin "+${age}" -delete
"""
UNBOUNDED_EXEC_LINE = """# container exec in a comment is no command
container exec -u git "${GC_ADDRESS:?}" \\
	find /data -mmin "+${age}" -delete
"""

INSTALLER_TASK = f"""---
- include_tasks: "{{{{ lookup('path_absolute', '{GC_INSTALLER}') }}}}"
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
        script = self.role / GC_SCRIPT
        script.parent.mkdir(parents=True)
        script.write_text(body)
        script.chmod(mode)

    def register(self) -> None:
        tasks = self.role / ROLE_FILE_TASKS_MAIN
        tasks.parent.mkdir()
        tasks.write_text(INSTALLER_TASK)

    def findings(self, *, required: bool = True) -> list[str]:
        return gc_findings(self.role, required=required)


class TestGcDeclarationsThatPass(GcFindingsCase, unittest.TestCase):
    def test_a_nocheck_marker_with_a_reason_passes(self) -> None:
        self.declare("", head="# nocheck: gc-required  static files only\n")
        self.assertEqual(self.findings(), [])

    def test_native_naming_its_setting_passes(self) -> None:
        self.declare('  gc:\n    type: native\n    setting: "RETENTION_DAYS"\n')
        self.assertEqual(self.findings(), [])

    def test_a_registered_script_honouring_the_contract_passes(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship()
        self.register()
        self.assertEqual(self.findings(), [])

    def test_a_container_exec_under_the_in_container_timeout_passes(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship(VALID_SCRIPT + BOUNDED_EXEC)
        self.register()
        self.assertEqual(self.findings(), [])

    def test_an_optional_role_without_declaration_passes(self) -> None:
        self.declare("")
        self.assertEqual(self.findings(required=False), [])


class TestGcDeclarationsThatFail(GcFindingsCase, unittest.TestCase):
    def test_a_missing_declaration_fails(self) -> None:
        self.declare("")
        self.assertEqual(self.findings(), ["declares no gc"])

    def test_an_unknown_type_fails(self) -> None:
        self.declare("  gc:\n    type: sometimes\n")
        self.assertIn("gc.type must be one of", self.findings()[0])

    def test_the_retired_none_type_fails(self) -> None:
        self.declare('  gc:\n    type: none\n    reason: "nothing"\n')
        self.assertIn("gc.type must be one of script, native", self.findings()[0])

    def test_a_bare_nocheck_marker_fails(self) -> None:
        self.declare("", head="# nocheck: gc-required\n")
        self.assertEqual(self.findings(), ["nocheck: gc-required names no reason"])

    def test_a_declaration_beside_a_nocheck_marker_fails(self) -> None:
        self.declare(
            '  gc:\n    type: native\n    setting: "RETENTION_DAYS"\n',
            head="# nocheck: gc-required  static files only\n",
        )
        self.assertEqual(
            self.findings(), ["declares gc and carries nocheck: gc-required"]
        )

    def test_a_nocheck_marker_does_not_excuse_a_shipped_script(self) -> None:
        self.declare("", head="# nocheck: gc-required  static files only\n")
        self.ship()
        self.assertEqual(
            self.findings(), ["ships files/shell/gc.sh but declares no gc"]
        )

    def test_native_without_a_setting_fails(self) -> None:
        self.declare("  gc:\n    type: native\n")
        self.assertEqual(
            self.findings(), ["gc.type native needs a non-empty gc.setting"]
        )

    def test_script_without_a_gc_script_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.register()
        self.assertEqual(
            self.findings(),
            ["declares gc.type script but ships no files/shell/gc.sh"],
        )

    def test_a_gc_script_under_another_type_fails(self) -> None:
        self.declare('  gc:\n    type: native\n    setting: "RETENTION_DAYS"\n')
        self.ship()
        self.assertEqual(
            self.findings(), ["ships files/shell/gc.sh but declares gc.type native"]
        )

    def test_a_gc_script_without_declaration_fails_even_when_optional(self) -> None:
        self.declare("")
        self.ship()
        self.assertEqual(
            self.findings(required=False),
            ["ships files/shell/gc.sh but declares no gc"],
        )

    def test_a_script_accepting_any_mode_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship('#!/bin/bash\ncase "$1" in\nroutine) ;;\npressure) ;;\n*) ;;\nesac\n')
        self.register()
        self.assertEqual(
            self.findings(), ["gc.sh's '*)' branch does not exit non-zero"]
        )

    def test_a_script_missing_the_pressure_mode_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship(VALID_SCRIPT.replace("pressure) age=1 ;;\n", ""))
        self.register()
        self.assertEqual(
            self.findings(), ["gc.sh has no case branch for mode 'pressure'"]
        )

    def test_a_script_that_is_not_executable_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship(mode=0o644)
        self.register()
        self.assertEqual(self.findings(), ["gc.sh is not executable"])

    def test_a_container_exec_without_the_in_container_timeout_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship(VALID_SCRIPT + UNBOUNDED_EXEC_LINE)
        self.register()
        self.assertEqual(self.findings(), [UNBOUNDED_EXEC])

    def test_an_unregistered_script_fails(self) -> None:
        self.declare("  gc:\n    type: script\n")
        self.ship()
        self.assertEqual(
            self.findings(),
            [f"declares gc.type script but no task includes {GC_INSTALLER}"],
        )


if __name__ == "__main__":
    unittest.main()
