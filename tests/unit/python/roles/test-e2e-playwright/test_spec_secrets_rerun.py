from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._spec_secrets_fakes import (
    CA_MODE,
    IMAGE,
    SERVICES,
    STAGE_KEYS,
    VALUE,
    install,
    leaks,
    scratch_text,
)
from .test_spec_secrets_helper import load_helper

RERUN = PROJECT_ROOT / "scripts" / "tests" / "e2e" / "rerun-spec.sh"
MAKEFILE = PROJECT_ROOT / "Makefile"
ROLE_ID = "web-app-x"
FAKE_DOCKER = """\
import json, pathlib, sys
probe = pathlib.Path(sys.argv[0]).parent.with_name("probe")
args = sys.argv[1:]
with (probe / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
stuck = (probe / "STUCK").exists()
if args[0] == "inspect":
    sys.exit(0 if stuck else f"Error: No such object: {args[-1]}")
if args[0] == "rm":
    failure = "cannot remove container" if stuck else "No such container:"
    sys.exit(f"Error response from daemon: {failure} {args[-1]}")
if "--mount" not in args:
    sys.exit(0)
cidfile =next((a.split("=", 1)[1] for a in args if a.startswith("--cidfile=")), "")
if cidfile:
    pathlib.Path(cidfile).write_text(args[args.index("--name") + 1])
reports = next(a for a in args if a.endswith(":/reports")).rsplit(":", 1)[0]
mount = next(a for a in args if a.startswith("type=bind,src="))
value = pathlib.Path(mount.split(",")[1][4:], "LONG_KEY").read_text()
pathlib.Path(reports, "playwright-junit.xml").write_text(f"<failure>{value}</failure>")
print(f"fill({value})", flush=True)
sys.exit(int((probe / "RUN_CODE").read_text()))
"""
CIDFILE = '"--cidfile=$secrets_dir/.cid" '
TIMEOUT_CHECK = 'grep -qE "^${timeout}=.+" "$env_file" || {'
REQUIRED = 'requiredTimeout("PLAYWRIGHT_TEST_TIMEOUT");\nrequiredTimeout("PLAYWRIGHT_ACTION_TIMEOUT");\n'
STAGED_MOUNT = 'reports_mount="$secrets_dir/reports"'
META = "a|b*$x"
SHELL_FORMS = ("--{reporter=html,trace=on}", "$OPTS", "`id`", "$(id)", f"$'{META}'")
HANDED_ARGS = ('-- "$@" &', "-- $* &")
AS_CALLER = (
    '((EUID == 0)) || user_args=(--user "$(id -u):$(id -g)" -e HOME=/tmp)',
    ":",
)
INSTALL = ["npm", "install", "--no-fund", "--no-audit", "--no-package-lock"]
INSTALL_MOUNTS = [":/e2e:ro", "node_modules:/e2e/node_modules"]
INSTALL_RO = (
    '-v "$stage_dir:/e2e:ro" -v "$stage_dir/node_modules:/e2e/node_modules"',
    '-v "$stage_dir:/e2e"',
)
ARG_CHECK = 'python3 -I -B "$spec_secrets" arguments "$@" || exit 2'
STAGE_RO = 'stage_ro=":ro"'
UNCHECKED_CONTAINER = ("        check_container(container, paths[0])\n", "")
FOREIGN_IMAGE = "mcr.microsoft.com/playwright:v0.0.1-noble"
OVERRIDE_CHECK = '[[ -z "${TEST_E2E_PLAYWRIGHT_COMMAND:-}" ]] || {'
OVERRIDE = "npm install && npx playwright test --reporter=html"
STAGE_GUARD = '[[ -d "$stage_dir" && ! -L "$stage_dir" ]]'
ASSIGN = re.compile(r"^PLAYWRIGHT_SECRETS_ASSIGN = .*$", re.MULTILINE)
NAIVE_ASSIGN = (
    "PLAYWRIGHT_SECRETS_ASSIGN = "
    "$(if $(secrets),PLAYWRIGHT_SPEC_SECRETS_FILE=$(secrets) )"
)
WRAPPERS = (
    ("bash scripts/tests/e2e/rerun-spec.sh $(role) $(pw)", "sh {show}"),
    ("bash scripts/tests/deploy/local/exec/container.sh", "sh {runner}"),
    ("bash scripts/tests/deploy/act/exec/node.sh", "sh {runner}"),
    ("bash scripts/tests/deploy/act/copy_worktree_to_node.sh", "true"),
)


def edited(path: Path, *replacements: tuple[str, str]) -> str:
    """Read a file with pieces of it replaced, for a negative control.

    Args:
        path: the file.
        *replacements: pairs of text the file holds exactly once and its
            replacement.

    Returns:
        The changed text.
    """
    text = read_text(str(path))
    for old, new in replacements:
        if text.count(old) != 1:
            raise AssertionError(f"{path.name} no longer holds {old!r} once")
        text = text.replace(old, new)
    return text


def rerun(
    args=(),
    *replacements,
    stuck=False,
    run_code,
    linked=False,
    required="",
    staged_env="",
    override="",
    image="",
    masker=(),
    ca="",
    ca_mode,
    ca_linked=False,
    stale=(),
) -> dict:
    """Run ``rerun-spec.sh`` for a role with the template against a fake docker.

    Args:
        args: the Playwright arguments.
        *replacements: changes to the script, for a negative control.
        stuck: whether the container outlives its run and ``docker rm``
            cannot remove it; else, as with ``--rm``, it is gone once the
            run ends and ``rm`` fails with ``No such container``.
        run_code: the exit code of the fake container.
        linked: whether the stage dir is a link to another directory.
        required: ``requiredTimeout`` calls the staged config makes.
        staged_env: lines the stage ``.env`` holds beyond ``APP_BASE_URL``.
        override: a ``TEST_E2E_PLAYWRIGHT_COMMAND`` to set, empty for none.
        image: a ``TEST_E2E_PLAYWRIGHT_IMAGE`` to set, empty for the pin.
        masker: changes to the masker and its container check, for a
            negative control of the script alone.
        ca: the stage ``.ca-trust`` a deploy under ``self_signed`` writes,
            empty for none.
        ca_mode: the mode of that ``.ca-trust``.
        ca_linked: whether that ``.ca-trust`` is a link to a file of its words.
        stale: paths below the role's reports dir an earlier rerun left,
            each written as a file before the run.

    Returns:
        The exit code, whether a container with the secrets ran, its whole
        argv and its command after the image, the commands of the containers
        without them, the ``--user`` of each container, whether the value
        showed in the output or the published report, whether ``***`` did,
        what is left of the run directories, whether the report reached the
        reports dir, which of ``stale`` are still there, whether the run
        mounted the stage dir writable, what each ``rm`` removed and all it
        printed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files = root / "roles" / "test-e2e-playwright" / "files"
        install(files, root, *masker)
        (files.parent / "meta").mkdir()
        (files.parent / "meta" / SERVICES.name).write_text(read_text(str(SERVICES)))
        (files / "playwright.config.js").write_text(
            f"{required}module.exports = {{}};\n"
        )
        role = root / "roles" / ROLE_ID
        (role / "files" / "playwright").mkdir(parents=True)
        (role / "files" / "playwright" / "playwright.spec.js").write_text("\n")
        (role / "templates").mkdir()
        (role / "templates" / "playwright.secrets.j2").write_text("\n")
        script = root / "scripts" / "tests" / "e2e" / RERUN.name
        script.parent.mkdir(parents=True)
        script.write_text(edited(RERUN, *replacements))
        (root / ".env").write_text(
            f"INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR={root / 'reports'}\n"
        )
        stage = root / "stage" / ROLE_ID
        target = root / "elsewhere" if linked else stage
        target.mkdir(parents=True)
        target.chmod(0o755)
        (target / ".env").write_text(
            f"APP_BASE_URL=http://web-app-x.example\n{staged_env}"
        )
        (target / ".env.keys").write_text(STAGE_KEYS)
        if ca:
            words = target / ("ca-words" if ca_linked else ".ca-trust")
            words.write_text(ca)
            words.chmod(ca_mode)
            if ca_linked:
                (target / ".ca-trust").symlink_to(words)
        for path in stale:
            left_over = root / "reports" / ROLE_ID / path
            left_over.parent.mkdir(parents=True, exist_ok=True)
            left_over.write_text("attempt 1\n")
        if linked:
            stage.parent.mkdir()
            stage.symlink_to(target)
        tools = root / "tools"
        tools.mkdir()
        (tools / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        (tools / "docker").write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
        for tool in tools.iterdir():
            tool.chmod(0o755)
        (root / "secrets.txt").write_text(f"LONG_KEY={VALUE}\n")
        (root / "probe").mkdir()
        (root / "probe" / "RUN_CODE").write_text(str(run_code))
        if stuck:
            (root / "probe" / "STUCK").touch()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                ("TEST_E2E_PLAYWRIGHT_", "PLAYWRIGHT_", "DOCKER_CONFIG")
            )
        }
        env.update(
            **({"TEST_E2E_PLAYWRIGHT_COMMAND": override} if override else {}),
            **({"TEST_E2E_PLAYWRIGHT_IMAGE": image} if image else {}),
            PATH=f"{tools}:{os.environ['PATH']}",
            PLAYWRIGHT_SPEC_SECRETS_FILE=str(root / "secrets.txt"),
            INFINITO_PLAYWRIGHT_STAGE_BASE_DIR=str(root / "stage"),
        )
        result = subprocess.run(
            ["bash", str(script), ROLE_ID, *args],
            capture_output=True,
            env=env,
            check=False,
        )
        log = root / "probe" / "calls.jsonl"
        logged = scratch_text(log).splitlines() if log.exists() else []
        calls = [json.loads(line) for line in logged]
        started = [call for call in calls if call[0] == "run"]
        runs = [call for call in started if "--mount" in call]
        reports = root / "reports" / ROLE_ID
        junit = reports / "playwright-junit.xml"
        shown = result.stdout.decode() + result.stderr.decode()
        parent = root / f"spec-secrets-{os.geteuid()}"
        used = image or IMAGE
        return {
            "rc": result.returncode,
            "ran": bool(runs),
            "run": runs[0] if runs else [],
            "kept": [path for path in stale if (reports / path).exists()],
            "command": runs[0][runs[0].index(used) + 1 :] if runs else [],
            "installs": [
                call[call.index(used) + 1 :]
                for call in started
                if "--mount" not in call
            ],
            "writable": any(
                str(arg).endswith((":/e2e", ":/volume")) for run in runs for arg in run
            ),
            "install_mounts": [
                arg.removeprefix(f"{stage}/").removeprefix(str(stage))
                for call in started
                if "--mount" not in call
                for flag, arg in pairwise(call)
                if flag == "-v"
            ],
            "users": [
                call[call.index("--user") + 1] if "--user" in call else None
                for call in started
            ],
            "leaks": leaks(shown, VALUE)
            or (junit.exists() and leaks(scratch_text(junit), VALUE)),
            "masked": "***" in shown,
            "left": sorted(os.listdir(parent)) if parent.exists() else [],
            "published": junit.exists(),
            "removed": [call[-1] for call in calls if call[0] == "rm"],
            "said": shown,
        }


def forwarded(makefile: str, secrets: str | None) -> list[str]:
    """Run both Playwright make targets with stub wrappers and read the file name.

    Args:
        makefile: the Makefile text.
        secrets: the ``secrets=`` argument, None to leave it out.

    Returns:
        Per target, the ``PLAYWRIGHT_SPEC_SECRETS_FILE`` the rerun would see.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "show.sh").write_text(
            "printf '%s\\n' \"${PLAYWRIGHT_SPEC_SECRETS_FILE-unset}\"\n"
        )
        (root / "runner.sh").write_text('exec sh -c "$cmd"\n')
        lines = ASSIGN.findall(makefile) + re.findall(
            r"^PLAYWRIGHT_SECRETS_WORD = .*$", makefile, re.MULTILINE
        )
        for target in ("compose-playwright", "swarm-playwright"):
            recipe = re.search(rf"^{target}:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
            body = recipe.group(1) if recipe else "\t@false\n"
            for old, new in WRAPPERS:
                body = body.replace(
                    old, new.format(show=root / "show.sh", runner=root / "runner.sh")
                )
            lines.append(f"{target}:\n{body}")
        (root / "Makefile").write_text("\n".join(lines))
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("MAKE", "MFLAGS", "PLAYWRIGHT_SPEC_SECRETS_FILE"))
        }
        env["INFINITO_NODE_SRC_DIR"] = str(root)
        found = []
        for target in ("compose-playwright", "swarm-playwright"):
            argv = [
                "make",
                "-s",
                "-f",
                str(root / "Makefile"),
                target,
                "role=x",
                "name=c",
            ]
            result = subprocess.run(
                argv + ([f"secrets={secrets}"] if secrets is not None else []),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            found.append(
                result.stdout.strip()
                if result.returncode == 0
                else f"rc {result.returncode}"
            )
        return found


class TestSpecSecretsRerun(unittest.TestCase):
    def test_a_rerun_masks_its_run_quotes_its_arguments_and_cleans_up(self) -> None:
        arguments = ["--grep", "talk admin", "--grep", "design:/x"]
        found = rerun(arguments, run_code=0, ca_mode=CA_MODE)
        self.assertEqual(found["command"], [*load_helper().RUNNER, *arguments])
        self.assertEqual(found["installs"], [INSTALL])
        self.assertEqual(found["install_mounts"], INSTALL_MOUNTS)
        self.assertEqual(
            {
                key: found[key]
                for key in ("rc", "ran", "leaks", "masked", "left", "published")
            },
            {
                "rc": 0,
                "ran": True,
                "leaks": False,
                "masked": True,
                "left": [],
                "published": True,
            },
        )

    def test_a_rerun_keeps_a_failure_and_publishes_only_once_the_container_is_gone(
        self,
    ) -> None:
        for (stuck, code), expected in (
            ((False, 3), (3, True)),
            ((True, 0), (70, False)),
            ((True, 3), (70, False)),
        ):
            with self.subTest(stuck=stuck, code=code):
                found = rerun((), stuck=stuck, run_code=code, ca_mode=CA_MODE)
                self.assertEqual(
                    [found[key] for key in ("rc", "published", "left", "leaks")],
                    [*expected, [], False],
                )

    def test_a_stage_env_without_a_required_timeout_fails_before_a_run(self) -> None:
        older = rerun(
            (),
            required=REQUIRED,
            staged_env="PLAYWRIGHT_TEST_TIMEOUT=1\n",
            run_code=0,
            ca_mode=CA_MODE,
        )
        self.assertEqual([older["rc"], older["ran"]], [1, False])
        self.assertIn("lacks PLAYWRIGHT_ACTION_TIMEOUT", older["said"])
        self.assertIn("redeploy web-app-x", older["said"])
        complete = "PLAYWRIGHT_TEST_TIMEOUT=1\nPLAYWRIGHT_ACTION_TIMEOUT=1\n"
        found = rerun(
            (), required=REQUIRED, staged_env=complete, run_code=0, ca_mode=CA_MODE
        )
        self.assertEqual(found["rc"], 0)

    def test_a_rerun_refuses_a_capture_flag_or_a_linked_stage_dir(self) -> None:
        refused = [("--reporter=html",), ("--grep", "x", "-u"), ("-c/x",), ("--ui",)]
        refused += [("--grep", META), *((form,) for form in SHELL_FORMS)]
        for args in refused:
            with self.subTest(args=args):
                self.assertEqual(
                    [
                        rerun(args, run_code=0, ca_mode=CA_MODE)[key]
                        for key in ("rc", "ran")
                    ],
                    [2, False],
                )
        found = rerun((), linked=True, run_code=0, ca_mode=CA_MODE)
        self.assertEqual([found[key] for key in ("rc", "ran")], [1, False])

    @unittest.skipIf(os.geteuid() == 0, "root runs its containers as root")
    def test_a_non_root_rerun_runs_each_container_as_the_caller(self) -> None:
        caller = f"{os.getuid()}:{os.getgid()}"
        found = rerun((), run_code=0, ca_mode=CA_MODE)
        self.assertEqual(found["users"], [caller, caller])

    def test_a_rerun_refuses_any_command_override(self) -> None:
        found = rerun((), override="npx playwright test", run_code=0, ca_mode=CA_MODE)
        self.assertEqual([found["rc"], found["ran"]], [2, False])
        self.assertIn("override is refused", found["said"])

    @unittest.skipUnless(shutil.which("make"), "make is not installed")
    def test_both_make_targets_forward_any_secrets_file_name(self) -> None:
        name = '/tmp/a b/it\'s "quoted".txt'
        makefile = read_text(str(MAKEFILE))
        self.assertEqual(forwarded(makefile, name), [name, name])
        self.assertEqual(forwarded(makefile, None), ["unset", "unset"])

    def test_a_rerun_mounts_the_stage_dir_read_only(self) -> None:
        found = rerun((), run_code=0, ca_mode=CA_MODE)
        self.assertEqual(
            [found["rc"], found["ran"], found["writable"]], [0, True, False]
        )

    def test_the_container_check_refuses_a_foreign_image_or_a_runtime_variable(
        self,
    ) -> None:
        plain = {"run_code": 0, "ca_mode": CA_MODE}
        for name, found in (
            ("image", rerun((), image=FOREIGN_IMAGE, **plain)),
            (
                "NODE_OPTIONS",
                rerun((), staged_env="NODE_OPTIONS=--require=/e2e/x.js\n", **plain),
            ),
            (
                "PW_TEST",
                rerun((), staged_env="PW_TEST_SOURCE_TRANSFORM=/e2e/t.js\n", **plain),
            ),
            ("timeout", rerun((), staged_env="PLAYWRIGHT_TEST_TIMEOUT=6e4\n", **plain)),
            ("undeclared", rerun((), staged_env="FOO=bar\n", **plain)),
        ):
            with self.subTest(trigger=name):
                self.assertEqual([found["rc"], found["ran"]], [70, False])
                self.assertIn("spec secrets refused", found["said"])


class TestSpecSecretsRerunNegativeControls(unittest.TestCase):
    def test_a_rerun_whose_install_may_write_the_stage_dir_is_caught(self) -> None:
        found = rerun((), INSTALL_RO, run_code=0, ca_mode=CA_MODE)
        self.assertEqual(found["install_mounts"], [":/e2e"])

    def test_a_rerun_that_settles_without_the_container_id_is_caught(self) -> None:
        unchecked = (UNCHECKED_CONTAINER,)
        plain = {"stuck": True, "run_code": 0, "ca_mode": CA_MODE}
        blind = rerun((), (CIDFILE, ""), masker=unchecked, **plain)
        self.assertEqual([blind["rc"], blind["published"]], [1, True])
        refused = rerun((), (CIDFILE, ""), **plain)
        self.assertEqual([refused["rc"], refused["ran"]], [70, False])

    def test_a_rerun_that_mounts_the_stage_dir_writable_is_caught(self) -> None:
        unchecked = (UNCHECKED_CONTAINER,)
        plain = {"run_code": 0, "ca_mode": CA_MODE}
        writable = rerun((), (STAGE_RO, 'stage_ro=""'), masker=unchecked, **plain)
        self.assertEqual([writable["ran"], writable["writable"]], [True, True])
        refused = rerun((), (STAGE_RO, 'stage_ro=""'), **plain)
        self.assertEqual([refused["rc"], refused["ran"]], [70, False])

    def test_a_masker_that_leaves_the_container_part_unchecked_is_caught(self) -> None:
        unchecked = (UNCHECKED_CONTAINER,)
        found = rerun(
            (), image=FOREIGN_IMAGE, masker=unchecked, run_code=0, ca_mode=CA_MODE
        )
        self.assertEqual([found["rc"], found["ran"]], [0, True])

    def test_a_rerun_that_skips_the_timeout_check_is_caught(self) -> None:
        older = rerun(
            (),
            (TIMEOUT_CHECK, "true || {"),
            required=REQUIRED,
            staged_env="PLAYWRIGHT_TEST_TIMEOUT=1\n",
            run_code=0,
            ca_mode=CA_MODE,
        )
        self.assertEqual([older["rc"], older["ran"]], [0, True])

    def test_a_rerun_that_reports_into_the_collected_dir_is_caught(self) -> None:
        unchecked = (UNCHECKED_CONTAINER,)
        plain = {"run_code": 0, "ca_mode": CA_MODE}
        found = rerun((), (STAGED_MOUNT, ":"), masker=unchecked, **plain)
        self.assertTrue(found["leaks"])
        refused = rerun((), (STAGED_MOUNT, ":"), **plain)
        self.assertEqual([refused["rc"], refused["leaks"]], [70, False])

    def test_a_rerun_that_splits_an_argument_is_caught(self) -> None:
        found = rerun(
            ("--grep", "talk admin"), HANDED_ARGS, run_code=0, ca_mode=CA_MODE
        )
        self.assertEqual(found["command"][-3:], ["--grep", "talk", "admin"])

    @unittest.skipIf(os.geteuid() == 0, "root runs its containers as root")
    def test_a_rerun_that_runs_its_containers_as_root_is_caught(self) -> None:
        found = rerun((), AS_CALLER, run_code=0, ca_mode=CA_MODE)
        self.assertEqual(found["users"], [None, None])

    def test_a_rerun_without_the_flag_or_link_check_is_caught(self) -> None:
        plain = {"run_code": 0, "ca_mode": CA_MODE}
        unchecked = rerun(("--reporter=html",), (ARG_CHECK, ":"), **plain)
        self.assertEqual([unchecked["rc"], unchecked["ran"]], [70, False])
        unguarded = (STAGE_GUARD, '[[ -d "$stage_dir" ]]')
        unchecked = (UNCHECKED_CONTAINER,)
        found = rerun((), unguarded, linked=True, masker=unchecked, **plain)
        self.assertEqual(found["ran"], True)
        self.assertEqual(rerun((), unguarded, linked=True, **plain)["ran"], False)

    def test_a_rerun_that_takes_a_command_override_is_caught(self) -> None:
        taking = rerun(
            (),
            (OVERRIDE_CHECK, "true || {"),
            override=OVERRIDE,
            run_code=0,
            ca_mode=CA_MODE,
        )
        self.assertEqual([taking["rc"], taking["ran"]], [0, True])
        self.assertEqual(taking["command"], list(load_helper().RUNNER))

    @unittest.skipUnless(shutil.which("make"), "make is not installed")
    def test_a_make_target_that_splits_the_file_name_is_caught(self) -> None:
        name = '/tmp/a b/it\'s "quoted".txt'
        naive = ASSIGN.sub(NAIVE_ASSIGN.replace("\\", "\\\\"), read_text(str(MAKEFILE)))
        self.assertNotIn(name, forwarded(naive, name))


if __name__ == "__main__":
    unittest.main()
