from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.cache.pin import __main__ as cli
from utils.cache import pin
from utils.cache.artefacts import Artefact

SHA = "0123456789abcdef0123456789abcdef01234567"
SHA256 = "0123456789abcdef" * 4


class TestValidate(unittest.TestCase):
    def test_a_full_commit_id_passes(self) -> None:
        self.assertEqual(pin.validate(f"{SHA}\n"), SHA)
        self.assertEqual(pin.validate(SHA256), SHA256)

    def test_anything_but_a_full_commit_id_is_refused(self) -> None:
        for candidate in ("", SHA[:10], "HEAD", "main", SHA.upper(), f"{SHA}0"):
            with self.subTest(candidate=candidate), self.assertRaises(pin.PinError):
                pin.validate(candidate)


class TestReadWrite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "state" / "infinito" / "cache.ref"

    def test_no_pin_fails_loudly_and_names_the_declarer(self) -> None:
        with self.assertRaises(pin.PinError) as caught:
            pin.read(self.path)
        self.assertIn("make cache-declare", str(caught.exception))

    def test_a_written_pin_reads_back_and_leaves_no_scratch_file(self) -> None:
        pin.write(self.path, SHA)
        self.assertEqual(pin.read(self.path), SHA)
        self.assertEqual(
            sorted(p.name for p in self.path.parent.iterdir()), [self.path.name]
        )

    def test_an_invalid_pin_is_never_written(self) -> None:
        with self.assertRaises(pin.PinError):
            pin.write(self.path, "main")
        self.assertFalse(self.path.exists())

    def test_a_corrupt_pin_file_is_refused(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("main\n", encoding="utf-8")
        with self.assertRaises(pin.PinError) as caught:
            pin.read(self.path)
        self.assertIn("make cache-declare", str(caught.exception))

    def test_the_applied_commit_is_recorded_beside_the_pin(self) -> None:
        self.assertEqual(pin.read_applied(self.path), "")
        pin.write_applied(self.path, SHA)
        self.assertEqual(pin.read_applied(self.path), SHA)
        self.assertEqual(pin.applied_path(self.path).name, "cache.applied")
        self.assertFalse(self.path.exists())

    def test_the_checkout_of_a_pin_lives_below_the_root(self) -> None:
        root = Path(self._tmp.name) / "share"
        self.assertEqual(pin.checkout(root, SHA), root / SHA)


class TestDeclareAndPrune(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.path = base / "state" / "cache.ref"
        self.root = base / "share"
        self.old = "1" * 40
        self.previous = "2" * 40
        for name in (self.old, self.previous, SHA, f".{SHA}.abc123", "notes"):
            (self.root / name / "roles").mkdir(parents=True)
        (self.root / "upstreams.conf").write_text("served\n", encoding="utf-8")

    def test_declare_keeps_the_new_and_the_previous_pin_and_prunes_the_rest(
        self,
    ) -> None:
        pin.write(self.path, self.previous)
        removed = pin.declare(self.path, self.root, SHA)
        self.assertEqual(pin.read(self.path), SHA)
        self.assertEqual(removed, [self.root / self.old])
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()),
            sorted([f".{SHA}.abc123", self.previous, SHA, "notes", "upstreams.conf"]),
        )

    def test_the_first_declare_keeps_only_the_new_pin(self) -> None:
        removed = pin.declare(self.path, self.root, SHA)
        self.assertEqual(
            sorted(removed), sorted([self.root / self.old, self.root / self.previous])
        )

    def test_an_invalid_declare_prunes_nothing(self) -> None:
        with self.assertRaises(pin.PinError):
            pin.declare(self.path, self.root, "main")
        self.assertTrue((self.root / self.old).is_dir())


class TestStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.environ = {
            pin.PIN_FILE_KEY: str(base / "cache.ref"),
            pin.PIN_ROOT_KEY: str(base / "share"),
        }

    def test_no_pin_reports_the_declarer_and_no_commit(self) -> None:
        row = pin.status(self.environ)
        self.assertIsNone(row["pin"])
        self.assertIn("make cache-declare", row["error"])

    def test_the_pin_and_the_applied_commit_are_reported(self) -> None:
        path = Path(self.environ[pin.PIN_FILE_KEY])
        pin.write(path, SHA)
        pin.write_applied(path, SHA256)
        row = pin.status(self.environ)
        self.assertEqual(row["pin"], SHA)
        self.assertEqual(row["applied"], SHA256)
        self.assertEqual(
            row["checkout"], str(Path(self.environ[pin.PIN_ROOT_KEY]) / SHA)
        )
        self.assertFalse(row["checkout_present"])
        self.assertIsNone(row["error"])

    def test_an_env_without_the_pin_keys_names_make_dotenv(self) -> None:
        row = pin.status({})
        self.assertIn("make dotenv", row["error"])


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.repo = Path(scratch.name)
        scoped = self._git("rev-parse", "--local-env-vars").split()
        env = {key: value for key, value in os.environ.items() if key not in scoped}
        env.update(
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        isolated = patch.dict(os.environ, env, clear=True)
        isolated.start()
        self.addCleanup(isolated.stop)
        self._git("init", "--quiet")
        (self.repo / "Makefile").write_text("all:\n", encoding="utf-8")
        self._git("add", "Makefile")
        self._git("commit", "--quiet", "--no-gpg-sign", "-m", "init")

    def _git(self, *args: str) -> str:
        """Run git in the scratch repository.

        Args:
            *args: the git arguments.

        Returns:
            Its stdout.
        """
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_a_ref_resolves_to_its_full_commit(self) -> None:
        head = self._git("rev-parse", "HEAD").strip()
        self.assertEqual(pin.resolve("HEAD", self.repo), head)

    def test_a_ref_that_is_no_commit_is_refused(self) -> None:
        for ref in ("HEAD^{tree}", "HEAD:Makefile", "no-such-ref-096", "--all", ""):
            with self.subTest(ref=ref), self.assertRaises(pin.PinError):
                pin.resolve(ref, self.repo)


class TestDrift(unittest.TestCase):
    def test_every_differing_entry_is_named_and_the_role_is_ignored(self) -> None:
        own = {
            "repos": {
                "raw-a": {"upstream": "https://a/", "role": "x"},
                "raw-new": {"upstream": "https://n/", "role": "x"},
            },
            "hosts": {"b.example": {"repo": "raw-b", "role": "x"}},
        }
        pinned = {
            "repos": {
                "raw-a": {"upstream": "https://a/", "role": "moved"},
                "raw-old": {"upstream": "https://o/", "role": "y"},
            },
            "hosts": {"b.example": {"repo": "raw-c", "role": "x"}},
        }
        self.assertEqual(
            pin.drift(own, pinned),
            [
                "repo raw-new: declared here, not pinned",
                "repo raw-old: pinned, not declared here",
                "host b.example: declared differently here",
            ],
        )

    def test_equal_declarations_drift_nowhere(self) -> None:
        same = {"repos": {"raw-a": {"upstream": "https://a/"}}, "hosts": {}}
        self.assertEqual(pin.drift(same, same), [])


class TestServed(unittest.TestCase):
    def test_only_hosts_the_pin_declares_identically_are_agreed(self) -> None:
        own = {
            "same.example": {"repo": "raw-a", "listen": [{"port": 443}], "role": "x"},
            "changed.example": {"repo": "raw-a", "role": "x"},
            "new.example": {"repo": "raw-a", "role": "x"},
        }
        pinned = {
            "same.example": {"repo": "raw-a", "listen": [{"port": 443}], "role": "y"},
            "changed.example": {"repo": "raw-b", "role": "x"},
            "old.example": {"repo": "raw-a", "role": "x"},
        }
        self.assertEqual(pin.agreed(own, pinned), {"same.example"})

    def test_an_env_without_a_pin_file_renders_every_own_host(self) -> None:
        self.assertIsNone(pin.served_hosts({pin.PIN_FILE_KEY: ""}))

    def test_an_unreadable_pin_or_checkout_hijacks_nothing_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pin_file = Path(tmp) / "cache.ref"
            environ = {pin.PIN_FILE_KEY: str(pin_file), pin.PIN_ROOT_KEY: tmp}
            for prepare in (lambda: None, lambda: pin.write(pin_file, SHA)):
                prepare()
                err = io.StringIO()
                with self.subTest(pinned=pin_file.exists()), redirect_stderr(err):
                    self.assertEqual(pin.served_hosts(environ), {})
                self.assertIn("no host is hijacked", err.getvalue())
            (Path(tmp) / SHA).mkdir()
            hosts = {"a.example": {"repo": "raw-a"}}
            with patch.object(
                pin, "pinned_declarations", return_value={"hosts": hosts}
            ) as declared:
                self.assertEqual(pin.served_hosts(environ), hosts)
            declared.assert_called_once_with(Path(tmp) / SHA)

    def test_a_pinned_checkout_that_cannot_run_hijacks_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pin_file = Path(tmp) / "cache.ref"
            pin.write(pin_file, SHA)
            (Path(tmp) / SHA).mkdir()
            environ = {pin.PIN_FILE_KEY: str(pin_file), pin.PIN_ROOT_KEY: tmp}
            for error in (
                subprocess.CalledProcessError(1, ["python"]),
                OSError("no interpreter"),
                json.JSONDecodeError("not json", "", 0),
            ):
                err = io.StringIO()
                with (
                    self.subTest(error=type(error).__name__),
                    patch.object(pin, "pinned_declarations", side_effect=error),
                    redirect_stderr(err),
                ):
                    self.assertEqual(pin.served_hosts(environ), {})
                self.assertIn("no host is hijacked", err.getvalue())
            err = io.StringIO()
            with (
                self.subTest(error="KeyError"),
                patch.object(pin, "pinned_declarations", return_value={}),
                redirect_stderr(err),
            ):
                self.assertEqual(pin.served_hosts(environ), {})
            self.assertIn("no host is hijacked", err.getvalue())


class TestPinnedDigests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.pin_file = self.tmp / "cache.ref"
        self.environ = {
            pin.PIN_FILE_KEY: str(self.pin_file),
            pin.PIN_ROOT_KEY: str(self.tmp),
        }

    def test_without_a_pin_nothing_is_pinned(self) -> None:
        self.assertEqual(pin.pinned_digests({pin.PIN_FILE_KEY: ""}), frozenset())
        self.assertEqual(pin.pinned_digests(self.environ), frozenset())

    def test_the_pinned_commit_names_its_artefact_digests(self) -> None:
        pin.write(self.pin_file, SHA)
        (self.tmp / SHA).mkdir()
        for declared, expected in (
            ({pin.ARTEFACTS: {"m": {"sha256": SHA256}}}, frozenset({SHA256})),
            ({"repos": {}, "hosts": {}}, frozenset()),
        ):
            with (
                self.subTest(declared=declared),
                patch.object(pin, "pinned_declarations", return_value=declared),
            ):
                self.assertEqual(pin.pinned_digests(self.environ), expected)

    def test_an_unreadable_pinned_checkout_leaves_the_digests_unknown(self) -> None:
        pin.write(self.pin_file, SHA)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertIsNone(pin.pinned_digests(self.environ))
        (self.tmp / SHA).mkdir()
        for error in (
            subprocess.CalledProcessError(1, ["python"]),
            json.JSONDecodeError("not json", "", 0),
        ):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(pin, "pinned_declarations", side_effect=error),
                redirect_stderr(err),
            ):
                self.assertIsNone(pin.pinned_digests(self.environ))
        self.assertIn("the pinned artefacts are unknown", err.getvalue())


class TestCli(unittest.TestCase):
    def test_the_declarations_carry_the_artefacts(self) -> None:
        out = io.StringIO()
        stored = Artefact("model", "https://h/f", SHA, SHA256, "7", "svc-ai-x")
        with (
            patch.object(cli, "artefacts", return_value=[stored]),
            redirect_stdout(out),
        ):
            self.assertEqual(cli.main(["declarations"]), 0)
        declared = json.loads(out.getvalue())
        self.assertEqual(declared[pin.ARTEFACTS]["model"]["sha256"], SHA256)
        self.assertEqual(set(declared), {"repos", "hosts", pin.ARTEFACTS})

    def test_read_without_a_pin_exits_non_zero_with_the_declarer_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "cache.ref")
            err = io.StringIO()
            with (
                patch.dict(os.environ, {pin.PIN_FILE_KEY: missing}),
                redirect_stderr(err),
            ):
                rc = cli.main(["read"])
        self.assertEqual(rc, 3)
        self.assertIn("make cache-declare", err.getvalue())

    def test_drift_names_the_entries_and_never_fails(self) -> None:
        pinned = {"repos": {}, "hosts": {}}
        own = {"repos": {"raw-new": {"upstream": "https://n/"}}, "hosts": {}}
        err = io.StringIO()
        with (
            patch.object(pin, "pinned_declarations", return_value=pinned),
            patch.object(cli, "_declarations", return_value=own),
            redirect_stderr(err),
        ):
            rc = cli.main(["drift", "/pinned"])
        self.assertEqual(rc, 0)
        self.assertIn("repo raw-new: declared here, not pinned", err.getvalue())
        self.assertIn("ask the declarer to bump the pin", err.getvalue())


if __name__ == "__main__":
    unittest.main()
