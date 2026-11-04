import contextlib
import importlib.util
import io
import struct
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-jira/files/python/build_guard.py"
_SPEC = importlib.util.spec_from_file_location("jira_build_guard", SCRIPT)
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)

IMAGE = "atlassian/jira-software:11.3.12"


class _Pool:
    def __init__(self) -> None:
        self.entries: list[bytes] = []
        self.slots = 0

    def add(self, entry: bytes, wide: bool = False) -> int:
        self.entries.append(entry)
        self.slots += 2 if wide else 1
        return self.slots - (1 if wide else 0)

    def utf8(self, text: str) -> int:
        data = text.encode("utf-8")
        return self.add(b"\x01" + struct.pack(">H", len(data)) + data)

    def ref(self, tag: int, index: int) -> int:
        return self.add(bytes([tag]) + struct.pack(">H", index))


def class_file(strings: dict[str, str], ints: dict[str, int]) -> bytes:
    pool = _Pool()
    this = pool.ref(7, pool.utf8("com/atlassian/jira/util/BuildUtils"))
    parent = pool.ref(7, pool.utf8("java/lang/Object"))
    constant_value = pool.utf8("ConstantValue")
    string_type = pool.utf8("Ljava/lang/String;")
    int_type = pool.utf8("I")
    pool.add(b"\x05" + struct.pack(">q", 70100), wide=True)
    fields = []
    for name, value in strings.items():
        fields.append((pool.utf8(name), string_type, pool.ref(8, pool.utf8(value))))
    for name, value in ints.items():
        fields.append(
            (pool.utf8(name), int_type, pool.add(b"\x03" + struct.pack(">i", value)))
        )
    body = struct.pack(">IHHH", 0xCAFEBABE, 0, 65, pool.slots + 1)
    body += b"".join(pool.entries)
    body += struct.pack(">HHHHH", 0x21, this, parent, 0, len(fields))
    for name, descriptor, value in fields:
        body += struct.pack(">HHHH", 0x19, name, descriptor, 1)
        body += struct.pack(">HIH", constant_value, 2, value)
    return body + struct.pack(">HH", 0, 0)


class TestBuildGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.install = Path(self._tmp.name) / "install"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _image(self, build: str, version: str) -> None:
        target = self.install / guard.BUILD_CLASS
        target.parent.mkdir(parents=True)
        target.write_bytes(
            class_file(
                {
                    guard.BUILD_FIELD: build,
                    guard.VERSION_FIELD: version,
                    "COMMIT_ID": "d514d74",
                },
                {"SERIAL": 7},
            )
        )

    def _run(self, data_build: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.main([data_build, str(self.install), "jira", IMAGE])
        return code, out.getvalue(), err.getvalue()

    def test_string_constants_reads_static_final_strings_only(self) -> None:
        constants = guard.string_constants(
            class_file(
                {"BUILD_NUMBER": "11030013", "VERSION": "11.3.12"}, {"SERIAL": 7}
            )
        )
        self.assertEqual(constants, {"BUILD_NUMBER": "11030013", "VERSION": "11.3.12"})

    def test_string_constants_rejects_a_non_class_file(self) -> None:
        with self.assertRaises(ValueError):
            guard.string_constants(b"PK\x03\x04 not a class")

    def test_image_build_reads_build_utils_of_the_installation(self) -> None:
        self._image("11030013", "11.3.12")
        self.assertEqual(guard.image_build(self.install), (11030013, "11.3.12"))

    def test_newer_data_stops_with_both_build_numbers(self) -> None:
        self._image("11030011", "11.3.10")

        code, out, _ = self._run("11030013")

        self.assertEqual(code, guard.DOWNGRADE_EXIT)
        self.assertIn("written by Jira build 11030013", out)
        self.assertIn(f"{IMAGE} is Jira 11.3.10 build 11030011", out)

    def test_equal_data_passes(self) -> None:
        self._image("11030013", "11.3.12")

        code, out, _ = self._run("11030013")

        self.assertEqual(code, 0)
        self.assertIn(f"build 11030013 <= {IMAGE} build 11030013", out)

    def test_older_data_passes_for_the_upgrade(self) -> None:
        self._image("11030013", "11.3.12")

        code, _, _ = self._run("10030000")

        self.assertEqual(code, 0)

    def test_data_without_a_recorded_build_passes(self) -> None:
        self._image("11030013", "11.3.12")

        code, out, _ = self._run("")

        self.assertEqual(code, 0)
        self.assertIn("build - <=", out)

    def test_wrong_argument_count_is_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main([]), 2)


if __name__ == "__main__":
    unittest.main()
