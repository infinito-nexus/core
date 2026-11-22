from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest.mock
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT, ROLE, role_task
from ._spec_secrets_fakes import (
    CA_MODE,
    CONTAINER,
    FOREIGN_UID,
    PARENT_OWNERS,
    RAW,
    container_argv,
    load_from,
    load_masker,
    scratch_text,
)
from ._spec_secrets_wiring import environment
from .test_spec_secrets_rerun import RERUN, edited, rerun
from .test_spec_secrets_trust import (
    OWN_UID,
    WORDS_TAKEN,
    ca_argv,
    ca_files,
    refused,
    with_ca,
)

ARCHIVE = ROLE / "files" / "archive_playwright_reports.sh"
DEDICATED = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "ci" / "dedicated.sh"
SWARM_COLLECT = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "swarm"
    / "utils"
    / "collect"
    / "playwright_reports.sh"
)
ARCHIVED = re.compile(r"^for item in (.+); do$", re.MULTILINE)
CLEARED = re.compile(r'^rm -rf -- ("\$reports_dir/[^"]+" ?)+$', re.MULTILINE)
SLOT_WIPE = ('rm -rf "${subdir:?}"\n', "")
RERUN_CLEAR = (
    (
        'rm -rf -- "$reports_dir/playwright-junit.xml" "$reports_dir/playwright-report"'
        ' "$reports_dir/test-results" "$reports_dir/run-parallel"\n'
    ),
    "",
)
RERUN_CA = ('\t"${ca_args[@]}"\n', "")
CA_REFUSALS = {
    "link": "is a link or no regular file",
    "mode": "is neither root's nor yours",
    "words": "takes only .ca-trust",
}
EXTRA_HOST = ("--add-host", "evil.example:host-gateway")
EXTRA_PROXY = ("-e", "PLAYWRIGHT_PROXY=socks5://host.docker.internal:9050")
LINK_TAKEN = ('[[ -L "$ca_trust" || (-e "$ca_trust" && ! -f "$ca_trust") ]]', "false")
MODE_TAKEN = (
    '[[ ("$ca_owner" == 0 || "$ca_owner" == "$EUID") && $((ca_mode & ~0644)) == 0 ]]',
    "true",
)
MISSING_TAKEN = ('        regular, text = True, ""\n', "        return rest\n")
UNDECODED = (
    "    except (OSError, ValueError) as error:\n",
    "    except OSError as error:\n",
)
CONTEXT_TAKEN = (
    'CONFIG_KEYS = frozenset({"auths", "credsStore", "credHelpers"})\n',
    'CONFIG_KEYS = frozenset({"auths", "credsStore", "credHelpers", "currentContext"})\n',
)
CA_WORDS = {
    "the deploy's words": ("block", "block"),
    "no file": (None, "block"),
    "no file, no CA trust": (None, "none"),
    "non-UTF-8": ("bytes", "block"),
    "no CA trust": ("none", "none"),
    "CA trust the file lacks": ("none", "block"),
    "words the command lacks": ("block", "none"),
    "an extra proxy": ("block+proxy", "block+proxy"),
    "a shared mount and a proxy": ("shared+proxy", "shared+proxy"),
    "a link": ("link", "block"),
}
TRUSTED_WORDS = ["no CA trust", "no file, no CA trust", "the deploy's words"]
TEMP_DROP_UNGUARDED = ("-type f -delete ||\n", "-type f -delete\n")
STALE = (
    "run-parallel/result.json",
    "run-parallel/stdout",
    "test-results/old.png",
    "playwright-report/index.html",
)
ATTEMPT_ONE = (
    "variant-0/sync/playwright-junit.xml",
    "variant-0/sync/run-parallel/result.json",
    "variant-1/sync/playwright-junit.xml",
)
PUBLISHING_TEMP = (
    "                    if name.startswith(TEMP):\n                        continue\n",
    "",
)
KEEPING_TEMP = (
    (
        "        for temp in (name for name in files if name.startswith(TEMP)):\n"
        "            with contextlib.suppress(FileNotFoundError):\n"
        "                os.unlink(temp, dir_fd=descriptor)\n"
    ),
    "",
)
CONFIG_CHECK = (
    "    if not isinstance(settings, dict) or not CONFIG_KEYS.issuperset(settings):\n"
)
PROXIES_TAKEN = (CONFIG_CHECK, "    if not isinstance(settings, dict):\n")
CASE_SENSITIVE = (
    CONFIG_CHECK,
    '    if not isinstance(settings, dict) or "proxies" in settings:\n',
)
CASEFOLDED = (
    CONFIG_CHECK,
    '    if not isinstance(settings, dict) or "proxies" in map(str.casefold, settings):\n',
)
PARENTS_UNCHECKED = (
    (
        "        or any(\n"
        "            above.st_uid not in PARENT_UIDS\n"
        "            or (above.st_mode & 0o022 and not above.st_mode & stat.S_ISVTX)\n"
        "            for above in parents\n"
        "        )\n"
    ),
    "",
)
UNCHECKED_CONFIG = ("    check_docker_config()\n", "")
PROXY = {"default": {"httpsProxy": "http://203.0.113.9:3128"}}
CONFIGS = {
    "unset": (None, None, 0o755, 0o755),
    "no config.json": ("dir", None, 0o755, 0o755),
    "credentials only": ("dir", json.dumps({"auths": {}}), 0o755, 0o755),
    "proxies": ("dir", json.dumps({"proxies": PROXY}), 0o755, 0o755),
    "Proxies": ("dir", json.dumps({"Proxies": PROXY}), 0o755, 0o755),
    "PROXIES": ("dir", json.dumps({"PROXIES": PROXY}), 0o755, 0o755),
    "dotless i": (
        "dir",
        json.dumps({"prox\N{LATIN SMALL LETTER DOTLESS I}es": PROXY}),
        0o755,
        0o755,
    ),
    "dotted I": (
        "dir",
        json.dumps({"prox\N{LATIN CAPITAL LETTER I WITH DOT ABOVE}es": PROXY}),
        0o755,
        0o755,
    ),
    "every allowed key": (
        "dir",
        json.dumps(
            {
                "auths": {},
                "credsStore": "pass",
                "credHelpers": {},
            }
        ),
        0o755,
        0o755,
    ),
    "a context": ("dir", json.dumps({"currentContext": "x"}), 0o755, 0o755),
    "group writable": ("dir", None, 0o775, 0o755),
    "below a writable dir": ("dir", None, 0o755, 0o777),
    "below a sticky dir": ("dir", None, 0o755, 0o1777),
    "linked": ("link", None, 0o755, 0o755),
    "no JSON": ("dir", "{", 0o755, 0o755),
    "missing": ("missing", None, 0o755, 0o755),
}
TRUSTED_CONFIGS = [
    "below a sticky dir",
    "credentials only",
    "every allowed key",
    "no config.json",
    "unset",
]
CA_FILE = "🔐 List the CA trust words"


def files_below(path: Path) -> list[str]:
    """List every file and link below a directory, never following one.

    Args:
        path: the directory.

    Returns:
        The paths relative to it, sorted.
    """
    return sorted(
        str(Path(here, name).relative_to(path))
        for here, dirs, files in os.walk(path)
        for name in [*files, *(d for d in dirs if Path(here, d).is_symlink())]
    )


def archived(*replacements: tuple[str, str]) -> dict[str, str]:
    """Archive a retry's junit into the slot its first attempt filled.

    Args:
        *replacements: changes to the archive script, for a negative control.

    Returns:
        The text of each file below the reports dir afterwards, by path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script, reports = root / ARCHIVE.name, root / "reports"
        script.write_text(edited(ARCHIVE, *replacements), encoding="utf-8")
        for path in (*ATTEMPT_ONE, "playwright-junit.xml"):
            (reports / path).parent.mkdir(parents=True, exist_ok=True)
            (reports / path).write_text("retry" if "/" not in path else "attempt 1")
        subprocess.run(
            ["bash", str(script), str(reports), "0", "false"],
            capture_output=True,
            check=True,
        )
        return {path: scratch_text(reports / path) for path in files_below(reports)}


def cleared_outputs(rerun_text: str, archive_text: str) -> list[str]:
    """Compare what a rerun clears before it runs with what the archive moves.

    Args:
        rerun_text: the text of ``rerun-spec.sh``.
        archive_text: the text of ``archive_playwright_reports.sh``.

    Returns:
        One message when the rerun clears no top-level output or other ones
        than the archive keeps per slot.
    """
    moved = ARCHIVED.search(archive_text)
    cleared = CLEARED.search(rerun_text)
    if not moved or not cleared:
        return ["the rerun or the archive names no top-level outputs"]
    names = re.findall(r'"\$reports_dir/([^"]+)"', cleared.group(0))
    if sorted(names) != sorted(moved.group(1).split()):
        return [f"the rerun clears {sorted(names)}, the archive moves others"]
    return []


def collect_violations(texts: dict[Path, str], temp: str) -> list[str]:
    """Check that no collect path copies a ``TEMP`` file of a killed masker.

    Args:
        texts: the text of each collect script by path.
        temp: the masker's ``TEMP`` prefix.

    Returns:
        One message per script that copies the reports without dropping or
        excluding the names ``temp`` starts.
    """
    pattern = f"'{temp}*'"
    expected = {
        DEDICATED: f'find "${{_playwright_host_dir}}" -name {pattern} -type f -delete',
        SWARM_COLLECT: f"--exclude={pattern}",
    }
    return [
        f"{path.name} collects {temp}* files"
        for path, needle in expected.items()
        if needle not in texts[path]
    ]


def drop_guarded(text: str, temp: str) -> bool:
    """Check that a failed ``TEMP`` drop never ends the EXIT cleanup of ``dedicated.sh``.

    Args:
        text: the text of ``dedicated.sh``.
        temp: the masker's ``TEMP`` prefix.

    Returns:
        Whether the drop is the left side of ``||`` whose right side reports
        the failure, so ``set -e`` lets the rest of the cleanup run.
    """
    drop = f"find \"${{_playwright_host_dir}}\" -name '{temp}*' -type f -delete"
    return bool(re.search(re.escape(drop) + r" \|\|\n\s+echo [^\n]+>&2\n", text))


def temp_publish(module) -> list[str]:
    """Publish staged reports next to the temp files a killed masker left.

    Args:
        module: the loaded masker.

    Returns:
        What the reports dir holds afterwards; a ``TEMP`` link outside stays.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staged, reports = root / "staged", root / "reports"
        (staged / "sub").mkdir(parents=True)
        (reports / "sub").mkdir(parents=True)
        (root / "outside").write_text("kept")
        for path in ("report.xml", "sub/a.xml", f"{module.TEMP}0123abcd"):
            (staged / path).write_text("ok")
        for path in (f"{module.TEMP}feedbeef", f"sub/{module.TEMP}cafe"):
            (reports / path).write_text("partial")
        (reports / f"{module.TEMP}link").symlink_to(root / "outside")
        module.publish(staged, reports, module.windows([RAW]))
        return files_below(reports)


def config_refused(case: str, *replacements: tuple[str, str]) -> bool:
    """Hold a run against the check with one ``DOCKER_CONFIG`` of ``CONFIGS``.

    Args:
        case: the name of the case.
        *replacements: changes to the container check, for a negative control.

    Returns:
        Whether ``check_container`` refused the run.
    """
    kind, config, mode, above = CONFIGS[case]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        module = load_from(root / "bin", root, OWN_UID, *replacements)
        run = root / "run"
        argv = container_argv(root, run)
        real = root / "above" / "docker"
        real.mkdir(parents=True)
        real.chmod(mode)
        real.parent.chmod(above)
        if config is not None:
            (real / "config.json").write_text(config, encoding="utf-8")
            (real / "config.json").chmod(0o644)
        (root / "docker-link").symlink_to(real)
        named = {"dir": real, "link": root / "docker-link", "missing": root / "gone"}
        with unittest.mock.patch.dict(os.environ):
            if "DOCKER_CONFIG" in os.environ:
                del os.environ["DOCKER_CONFIG"]
            if kind is not None:
                os.environ["DOCKER_CONFIG"] = str(named[kind])
            try:
                module.check_container(argv, run)
            except module.spec_secrets.SpecSecretsError:
                return True
            return False


def foreign_above_refused(*replacements: tuple[str, str]) -> bool:
    """Hold a ``DOCKER_CONFIG`` whose dir above reports ``FOREIGN_UID`` as owner.

    Args:
        *replacements: changes to the container check, for a negative control.

    Returns:
        Whether ``check_container`` refused the run, as it must for an owner
        neither root, ``TRUSTED_UID`` nor one of the scratch dirs above.
    """
    real = os.lstat

    def lstat(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if Path(os.fsdecode(path)).name != "above":
            return info
        return os.stat_result((*info[:4], FOREIGN_UID, *info[5:10]))

    with unittest.mock.patch("os.lstat", lstat):
        return config_refused("no config.json", *replacements)


def ca_words_refused(case: str, *replacements: tuple[str, str]) -> bool:
    """Hold a run against the check with one stage ``.ca-trust`` of ``CA_WORDS``.

    Args:
        case: the name of the case, whose kinds name the words the stage file
            holds, ``None`` for no file and ``bytes`` for no UTF-8, and the
            words the command carries.
        *replacements: changes to the container check, for a negative control.

    Returns:
        Whether ``check_container`` refused the run.
    """
    written, carried = CA_WORDS[case]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        module = load_from(root / "bin", root, OWN_UID, *replacements)
        run = root / "run"
        block = ca_argv(ca_files(root, CA_MODE))
        shared = ["-v", f"{root / '_shared' / 'node_modules'}:/e2e/node_modules:ro"]
        kinds = {
            "none": [],
            "block": block,
            "link": block,
            "block+proxy": [*block, *EXTRA_PROXY],
            "shared+proxy": [*shared, *EXTRA_PROXY],
        }
        argv = with_ca(root, run, kinds[carried])
        stage = root / "stage"
        (stage / ".ca-trust").unlink()
        if written == "bytes":
            (stage / ".ca-trust").write_bytes(b"-v\n\xff\xfe\n")
        elif written is not None:
            words = stage / ("ca-words" if written == "link" else ".ca-trust")
            words.write_text("".join(f"{w}\n" for w in kinds[written]))
            if written == "link":
                (stage / ".ca-trust").symlink_to(words)
        return refused(module, argv, run)


def rerun_ca(
    *replacements: tuple[str, str], extra=(), mode: int, linked=False, masker=()
) -> tuple[int, bool, list[str]]:
    """Rerun a role with the template after a deploy under ``self_signed``.

    Args:
        *replacements: changes to ``rerun-spec.sh``, for a negative control.
        extra: words the stage ``.ca-trust`` holds after the deploy's.
        mode: the mode of the stage ``.ca-trust``.
        linked: whether the stage ``.ca-trust`` is a link to its words.
        masker: changes to the container check, for a negative control.

    Returns:
        The exit code, whether the run carried the deploy's CA trust words
        in one piece, and which of ``CA_REFUSALS`` the script printed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        words = ca_argv(ca_files(Path(tmp), CA_MODE))
        found = rerun(
            (),
            *replacements,
            run_code=0,
            ca="".join(f"{w}\n" for w in (*words, *extra)),
            ca_mode=mode,
            ca_linked=linked,
            masker=(OWN_UID, *masker),
        )
        run = found["run"]
        whole = any(run[at : at + len(words)] == words for at in range(len(run)))
        said = [name for name, text in CA_REFUSALS.items() if text in found["said"]]
        return found["rc"], whole, said


def ca_file_words(words: list[str]) -> list[str]:
    """Render the stage ``.ca-trust`` the deploy writes for a run with spec secrets.

    Args:
        words: the ``_playwright_ca_argv`` of the setup.

    Returns:
        Its non-empty lines, each one word.
    """
    task = role_task("03_run_pass.yml", CA_FILE)
    content = environment().from_string(task["ansible.builtin.copy"]["content"])
    rendered = content.render(_playwright_ca_argv=words, _playwright_ca_required=True)
    return [line for line in rendered.splitlines() if line]


class TestSpecSecretsLeftovers(unittest.TestCase):
    def test_a_retry_replaces_its_whole_slot_and_keeps_the_others(self) -> None:
        self.assertEqual(
            archived(),
            {
                "variant-0/sync/playwright-junit.xml": "retry",
                "variant-1/sync/playwright-junit.xml": "attempt 1",
            },
        )

    def test_a_rerun_clears_the_outputs_the_archive_moves_before_it_runs(
        self,
    ) -> None:
        texts = (read_text(str(RERUN)), read_text(str(ARCHIVE)))
        self.assertEqual(cleared_outputs(*texts), [])
        found = rerun((), stale=STALE, run_code=0, ca_mode=CA_MODE)
        self.assertEqual([found["rc"], found["kept"]], [0, []])

    def test_no_collect_path_copies_a_temp_file(self) -> None:
        texts = {path: read_text(str(path)) for path in (DEDICATED, SWARM_COLLECT)}
        self.assertEqual(collect_violations(texts, load_masker().TEMP), [])

    def test_a_failed_temp_drop_never_ends_the_exit_cleanup(self) -> None:
        self.assertTrue(drop_guarded(read_text(str(DEDICATED)), load_masker().TEMP))

    def test_publish_skips_temp_names_and_drops_stale_temp_files(self) -> None:
        module = load_masker()
        self.assertEqual(
            temp_publish(module), [f"{module.TEMP}link", "report.xml", "sub/a.xml"]
        )

    def test_only_a_trusted_docker_config_without_proxies_passes(self) -> None:
        self.assertEqual(
            sorted(case for case in CONFIGS if not config_refused(case)),
            TRUSTED_CONFIGS,
        )

    def test_a_rerun_carries_the_deploys_ca_trust_words(self) -> None:
        self.assertEqual(rerun_ca(mode=CA_MODE), (0, True, []))
        with tempfile.TemporaryDirectory() as tmp:
            words = ca_argv(ca_files(Path(tmp), CA_MODE))
        self.assertEqual(ca_file_words(words), words)

    def test_a_rerun_refuses_a_ca_trust_file_it_cannot_trust(self) -> None:
        for extra in (EXTRA_HOST, EXTRA_PROXY):
            with self.subTest(extra=extra):
                found = rerun_ca(extra=extra, mode=CA_MODE)
                self.assertEqual(found, (70, False, ["words"]))
        self.assertEqual(rerun_ca(mode=0o666), (2, False, ["mode"]))
        self.assertEqual(rerun_ca(linked=True, mode=CA_MODE), (2, False, ["link"]))

    def test_only_the_deploys_ca_trust_words_pass_word_by_word(self) -> None:
        self.assertEqual(
            sorted(case for case in CA_WORDS if not ca_words_refused(case)),
            TRUSTED_WORDS,
        )

    def test_a_dir_above_of_another_owner_is_refused(self) -> None:
        text = read_text(str(CONTAINER))
        self.assertEqual(
            [text.count("TRUSTED_UID = 0\n"), text.count(PARENT_OWNERS[0])], [1, 1]
        )
        self.assertTrue(foreign_above_refused())


class TestSpecSecretsLeftoversNegativeControls(unittest.TestCase):
    def test_an_archive_that_keeps_the_first_attempts_leftovers_is_caught(
        self,
    ) -> None:
        self.assertIn("variant-0/sync/run-parallel/result.json", archived(SLOT_WIPE))

    def test_a_rerun_that_keeps_its_earlier_outputs_is_caught(self) -> None:
        text = edited(RERUN, RERUN_CLEAR)
        self.assertNotEqual(cleared_outputs(text, read_text(str(ARCHIVE))), [])
        found = rerun((), RERUN_CLEAR, stale=STALE, run_code=0, ca_mode=CA_MODE)
        self.assertEqual(found["kept"], list(STALE))

    def test_a_collect_path_that_copies_temp_files_is_caught(self) -> None:
        texts = {path: read_text(str(path)) for path in (DEDICATED, SWARM_COLLECT)}
        texts = {
            path: text.replace(".masked.", ".kept.") for path, text in texts.items()
        }
        self.assertEqual(len(collect_violations(texts, load_masker().TEMP)), 2)

    def test_an_exit_cleanup_that_a_failed_temp_drop_ends_is_caught(self) -> None:
        text = edited(DEDICATED, TEMP_DROP_UNGUARDED)
        self.assertFalse(drop_guarded(text, load_masker().TEMP))

    def test_a_publish_that_copies_or_keeps_temp_files_is_caught(self) -> None:
        module = load_masker(PUBLISHING_TEMP)
        self.assertIn(f"{module.TEMP}0123abcd", temp_publish(module))
        module = load_masker(KEEPING_TEMP)
        self.assertIn(f"sub/{module.TEMP}cafe", temp_publish(module))

    def test_a_check_that_takes_any_docker_config_is_caught(self) -> None:
        self.assertFalse(config_refused("proxies", PROXIES_TAKEN))
        self.assertFalse(config_refused("group writable", UNCHECKED_CONFIG))

    def test_a_check_that_matches_proxies_by_case_is_caught(self) -> None:
        self.assertFalse(config_refused("Proxies", CASE_SENSITIVE))
        self.assertFalse(config_refused("PROXIES", CASE_SENSITIVE))

    def test_a_check_that_casefolds_proxies_is_caught(self) -> None:
        self.assertFalse(config_refused("dotless i", CASEFOLDED))
        self.assertFalse(config_refused("dotted I", CASEFOLDED))

    def test_a_check_that_ignores_the_dirs_above_is_caught(self) -> None:
        self.assertFalse(config_refused("below a writable dir", PARENTS_UNCHECKED))
        self.assertFalse(foreign_above_refused(PARENTS_UNCHECKED))

    def test_a_rerun_without_the_ca_trust_words_is_caught(self) -> None:
        self.assertEqual(rerun_ca(RERUN_CA, mode=CA_MODE), (70, False, ["words"]))

    def test_a_rerun_that_trusts_any_ca_trust_file_is_caught(self) -> None:
        loose = rerun_ca(extra=EXTRA_PROXY, mode=CA_MODE, masker=(WORDS_TAKEN,))
        self.assertEqual(loose, (0, True, []))
        self.assertEqual(rerun_ca(MODE_TAKEN, mode=0o666), (0, True, []))
        linked = rerun_ca(LINK_TAKEN, linked=True, mode=CA_MODE)
        self.assertNotIn("link", linked[2])

    def test_a_check_that_takes_ca_trust_words_loosely_is_caught(self) -> None:
        for case in ("an extra proxy", "a shared mount and a proxy"):
            with self.subTest(case=case):
                self.assertFalse(ca_words_refused(case, WORDS_TAKEN))

    def test_a_check_that_takes_ca_trust_without_its_file_is_caught(self) -> None:
        self.assertFalse(ca_words_refused("no file", MISSING_TAKEN))

    def test_a_check_that_lets_a_non_utf8_file_escape_is_caught(self) -> None:
        with self.assertRaises(UnicodeDecodeError):
            ca_words_refused("non-UTF-8", UNDECODED)

    def test_a_check_that_takes_a_docker_context_is_caught(self) -> None:
        self.assertFalse(config_refused("a context", CONTEXT_TAKEN))


if __name__ == "__main__":
    unittest.main()
