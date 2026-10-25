from __future__ import annotations

import base64
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from baudolo.databases import DatabasesCsvError, validate_database
from baudolo.seed.__main__ import check_and_add_entry

from plugins.filter.baudolo_seed import (
    FilterModule,
    _database,
    baudolo_seed_apply,
    baudolo_seed_current,
    baudolo_seeded,
)

HEADER = "instance;database;username;password\n"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _seeded(text: str) -> dict:
    return baudolo_seeded(_b64(text))


STABLE = [
    ("central-postgres", "nextcloud", "nextcloud", "pw-1"),
    ("central-mariadb", "wordpress", "wordpress", "pa;ss"),
    ("central-postgres", "", "postgres", 'quo"te'),
    ("central-mariadb", "matomo", "matomo", "multi\nline"),
    ("central-postgres", " keycloak ", "keycloak", " spaced "),
    ("central-postgres", "gitea", "gitea", ""),
    ("central-postgres", "listmonk", "listmonk", "ünïcode"),
]
ENTRIES = [
    *STABLE[:5],
    ("central-postgres", "nextcloud", "nextcloud", "pw-2"),
    ("central-mariadb", "wordpress", "wordpress", "pa;ss"),
    *STABLE[5:],
]


def _argv(entry) -> tuple[str, str, str, str]:
    instance, name, username, password = entry
    return instance, name or "*", username, password


def _bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    return path.read_bytes()  # nocheck: cache-read baudolo-seed rewrites the tempfile


def _b64_of(path: Path) -> str:
    return base64.b64encode(_bytes(path)).decode("ascii")


def _seed(path: Path, argv) -> None:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        check_and_add_entry(str(path), *argv)


class TestBaudoloSeedEquivalence(unittest.TestCase):
    def _per_entry(self, path: Path, entries) -> int:
        for entry in entries:
            _seed(path, _argv(entry))
        return len(entries)

    def _skipping(self, path: Path, entries) -> int:
        state = baudolo_seeded(_b64_of(path))
        calls = 0
        for entry in entries:
            argv = _argv(entry)
            current = baudolo_seed_current(state, *argv)
            state = baudolo_seed_apply(state, *argv)
            if not current:
                _seed(path, argv)
                calls += 1
        return calls

    def _run_both(self, start: bytes | None, entries):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.csv"
            new = Path(tmp) / "new.csv"
            if start is not None:
                old.write_bytes(start)
                new.write_bytes(start)
            old_calls = self._per_entry(old, entries)
            new_calls = self._skipping(new, entries)
            return _bytes(old), _bytes(new), old_calls, new_calls

    def test_fresh_file_matches_and_skips_only_repeats(self):
        old, new, old_calls, new_calls = self._run_both(None, ENTRIES)
        self.assertEqual(old, new)
        self.assertEqual(old_calls, len(ENTRIES))
        self.assertEqual(new_calls, len(ENTRIES) - 1)

    def test_empty_file_from_touch_matches(self):
        old, new, _, _ = self._run_both(b"", ENTRIES)
        self.assertEqual(old, new)

    def _converged(self, entries) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.csv"
            self._per_entry(first, entries)
            return _bytes(first)

    def test_converged_file_needs_no_call_and_keeps_its_bytes(self):
        converged = self._converged(STABLE)
        old, new, _, new_calls = self._run_both(converged, STABLE)
        self.assertEqual(old, new)
        self.assertEqual(new, converged)
        self.assertEqual(new_calls, 0)

    def test_entries_that_overwrite_each_other_are_seeded_every_time(self):
        converged = self._converged(ENTRIES)
        old, new, _, new_calls = self._run_both(converged, ENTRIES)
        self.assertEqual(old, new)
        self.assertEqual(new_calls, 2)

    def test_rotated_password_is_seeded_again(self):
        converged = self._converged(STABLE)
        rotated = [*STABLE[:-1], ("central-postgres", "listmonk", "listmonk", "rot")]
        old, new, _, new_calls = self._run_both(converged, rotated)
        self.assertEqual(old, new)
        self.assertEqual(new_calls, 1)

    def test_new_consumer_is_appended_after_the_converged_rows(self):
        converged = self._converged(STABLE)
        grown = [*STABLE, ("central-mariadb", "pixelfed", "pixelfed", "x")]
        old, new, _, new_calls = self._run_both(converged, grown)
        self.assertEqual(old, new)
        self.assertEqual(new_calls, 1)

    def test_invalid_database_name_still_reaches_baudolo(self):
        entry = ("central-postgres", "bad name", "u", "p")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "databases.csv"
            self._per_entry(path, STABLE)
            with self.assertRaises(DatabasesCsvError):
                self._skipping(path, [entry])

    def test_hand_edited_file_falls_back_to_one_call_per_entry(self):
        hand = (HEADER + "central-postgres;nextcloud;nextcloud;pw-2\r\n").encode()
        old, new, old_calls, new_calls = self._run_both(hand, ENTRIES)
        self.assertEqual(old, new)
        self.assertEqual(new_calls, old_calls)

    def test_short_row_falls_back_to_one_call_per_entry(self):
        short = (HEADER + "central-postgres;nextcloud\n").encode()
        old, new, old_calls, new_calls = self._run_both(short, ENTRIES)
        self.assertEqual(old, new)
        self.assertEqual(new_calls, old_calls)

    def test_negative_control_a_state_older_than_the_file_breaks_equivalence(self):
        converged = self._converged(STABLE)
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "stale.csv"
            stale.write_bytes(b"")
            state = baudolo_seeded(base64.b64encode(converged).decode("ascii"))
            for entry in STABLE:
                if not baudolo_seed_current(state, *_argv(entry)):
                    _seed(stale, _argv(entry))
            self.assertNotEqual(_bytes(stale), converged)


class TestBaudoloSeeded(unittest.TestCase):
    def test_absent_or_empty_file_is_canonical_without_rows(self):
        self.assertEqual(baudolo_seeded(""), {"canonical": True, "rows": []})

    def test_header_only_is_canonical_without_rows(self):
        self.assertEqual(_seeded(HEADER), {"canonical": True, "rows": []})

    def test_rows_are_read_in_file_order(self):
        text = HEADER + "a;db1;u1;p1\nb;*;u2;p2\n"
        self.assertEqual(
            _seeded(text),
            {
                "canonical": True,
                "rows": [["a", "db1", "u1", "p1"], ["b", "*", "u2", "p2"]],
            },
        )

    def test_quoted_fields_stay_canonical(self):
        text = HEADER + 'a;db;u;"pa;ss"\nb;db;u;"q""t"\n'
        state = _seeded(text)
        self.assertTrue(state["canonical"])
        self.assertEqual(state["rows"][0][3], "pa;ss")
        self.assertEqual(state["rows"][1][3], 'q"t')

    def test_crlf_is_not_canonical(self):
        self.assertFalse(_seeded(HEADER.replace("\n", "\r\n"))["canonical"])

    def test_missing_trailing_newline_is_not_canonical(self):
        self.assertFalse(_seeded(HEADER + "a;db;u;p")["canonical"])

    def test_blank_line_is_not_canonical(self):
        self.assertFalse(_seeded(HEADER + "\na;db;u;p\n")["canonical"])

    def test_needless_quotes_are_not_canonical(self):
        self.assertFalse(_seeded(HEADER + 'a;db;u;"p"\n')["canonical"])

    def test_foreign_header_is_not_canonical(self):
        self.assertFalse(_seeded("instance;database;user;password\n")["canonical"])

    def test_undecodable_content_is_not_canonical(self):
        self.assertFalse(baudolo_seeded("not base64!")["canonical"])
        self.assertFalse(
            baudolo_seeded(base64.b64encode(b"\xff\xfe").decode())["canonical"]
        )


class TestBaudoloSeedCurrent(unittest.TestCase):
    def setUp(self):
        self.state = _seeded(HEADER + "a;db;u;p\na;*;su;sp\nb;db;u;p\nb;db;u;q\n")

    def test_same_credentials_are_current(self):
        self.assertTrue(baudolo_seed_current(self.state, "a", "db", "u", "p"))

    def test_cluster_row_is_current(self):
        self.assertTrue(baudolo_seed_current(self.state, "a", "*", "su", "sp"))

    def test_padded_database_name_matches_the_stripped_row(self):
        self.assertTrue(baudolo_seed_current(self.state, "a", " db ", "u", "p"))

    def test_negative_control_other_password_is_not_current(self):
        self.assertFalse(baudolo_seed_current(self.state, "a", "db", "u", "p2"))

    def test_negative_control_other_username_is_not_current(self):
        self.assertFalse(baudolo_seed_current(self.state, "a", "db", "u2", "p"))

    def test_missing_row_is_not_current(self):
        self.assertFalse(baudolo_seed_current(self.state, "c", "db", "u", "p"))

    def test_duplicate_rows_with_other_credentials_are_not_current(self):
        self.assertFalse(baudolo_seed_current(self.state, "b", "db", "u", "p"))

    def test_invalid_database_name_is_never_current(self):
        state = _seeded(HEADER + "a;bad name;u;p\n")
        self.assertFalse(baudolo_seed_current(state, "a", "bad name", "u", "p"))

    def test_non_canonical_state_is_never_current(self):
        state = _seeded(HEADER + 'a;db;u;"p"\n')
        self.assertFalse(baudolo_seed_current(state, "a", "db", "u", "p"))


class TestBaudoloSeedApply(unittest.TestCase):
    def test_new_definition_is_appended(self):
        state = baudolo_seed_apply(_seeded(HEADER + "a;db;u;p\n"), "b", "*", "u", "p")
        self.assertEqual(state["rows"], [["a", "db", "u", "p"], ["b", "*", "u", "p"]])

    def test_every_matching_row_takes_the_credentials(self):
        state = baudolo_seed_apply(
            _seeded(HEADER + "a;db;u;p\nx;db;u;p\na;db;v;q\n"), "a", "db", "n", "m"
        )
        self.assertEqual(
            state["rows"],
            [["a", "db", "n", "m"], ["x", "db", "u", "p"], ["a", "db", "n", "m"]],
        )

    def test_database_name_is_stored_stripped(self):
        state = baudolo_seed_apply(baudolo_seeded(""), "a", " db ", "u", "p")
        self.assertEqual(state["rows"], [["a", "db", "u", "p"]])

    def test_input_state_is_not_mutated(self):
        state = _seeded(HEADER + "a;db;u;p\n")
        baudolo_seed_apply(state, "a", "db", "u", "q")
        self.assertEqual(state["rows"], [["a", "db", "u", "p"]])

    def test_non_canonical_state_stays_non_canonical(self):
        state = baudolo_seed_apply(
            _seeded(HEADER + 'a;db;u;"p"\n'), "a", "db", "u", "p"
        )
        self.assertEqual(state, {"canonical": False, "rows": []})

    def test_invalid_database_name_makes_the_state_non_canonical(self):
        state = baudolo_seed_apply(baudolo_seeded(""), "a", "nan", "u", "p")
        self.assertFalse(state["canonical"])


class TestDatabaseNameParity(unittest.TestCase):
    def test_validation_matches_baudolo(self):
        for value in (
            "db",
            " db ",
            "*",
            " * ",
            "",
            "  ",
            "nan",
            "NaN",
            "a-b_c",
            "-a",
            "a b",
            "ü",
        ):
            with self.subTest(value=value):
                try:
                    expected = validate_database(value, instance="i")
                except DatabasesCsvError:
                    expected = None
                self.assertEqual(_database(value), expected)


class TestFilterModule(unittest.TestCase):
    def test_filters_are_registered(self):
        self.assertEqual(
            FilterModule().filters(),
            {
                "baudolo_seeded": baudolo_seeded,
                "baudolo_seed_current": baudolo_seed_current,
                "baudolo_seed_apply": baudolo_seed_apply,
            },
        )


if __name__ == "__main__":
    unittest.main()
