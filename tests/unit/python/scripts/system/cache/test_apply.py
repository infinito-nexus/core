from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cli.administration.infra.__main__ import FOREIGN_MAP, RUNNER_DOWN
from tests.utils.workflow_words import step_options
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.env.handlers.infinito.cache.pin import ROOT_KEY as PIN_ROOT_KEY
from utils.stacks.declaration import load, resolve
from utils.stacks.makefile import make_calls, makefile_calls

CACHE_SCRIPTS = PROJECT_ROOT / "scripts" / "system" / "cache"
APPLY = CACHE_SCRIPTS / "apply.sh"
DECLARE = CACHE_SCRIPTS / "declare.sh"
PIN_SH = CACHE_SCRIPTS / "pin.sh"
WORKSPACE_BOOTSTRAP = (
    PROJECT_ROOT / "scripts" / "tests" / "workspace" / "base" / "04_bootstrap.sh"
)
WORKSPACE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-workspace.yml"
WORKSPACE_JOB = "test-workspace"
WORKSPACE_DECLARE = 'make cache-declare ref="$(git rev-parse HEAD)"'
CACHE_STACK = "cache"
SHA = "0123456789abcdef0123456789abcdef01234567"
SHA2 = "fedcba9876543210fedcba9876543210fedcba98"
MAP = Path("compose") / "package-cache-frontend" / "upstreams.conf"
SHELL_DIR = Path("roles") / "svc-cache-package" / "files" / "shell"
PIN_CLI = Path("cli") / "meta" / "cache" / "pin" / "__main__.py"
PIN_ENV = (
    "INFINITO_CACHE_TLS_HOSTS=pinned.example",
    "INFINITO_CACHE_UPSTREAMS=raw-pinned|raw|https://pinned.example/|||",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")  # nocheck: cache-read


NEXUS = "package-cache"
FRONTEND = "infinito-package-cache-frontend"
NEXUS_PORT = "8081"
PUBLISHED_PORT = "8099"
PUBLISHED_HOST = "nexus.example"

INFRA_ARMS = f"""cache-name)
	case "$4" in
	package) echo {NEXUS} ;;
	*) echo {FRONTEND} ;;
	esac
	;;
cache-port) [[ "$4 $5" == "package http" ]] && echo {NEXUS_PORT} ;;
running) [[ -z "$STUB_RUNNER_DOWN" ]] || exit {RUNNER_DOWN} ;;
docker)
	[[ -z "$STUB_RUNNER_DOWN" ]] || exit 1
	shift 3
	exec docker "$@"
	;;"""

PYTHON_STUB = f"""#!/usr/bin/env bash
printf 'python %s %s\\n' "$PWD" "$*" >>"$STUB_LOG"
case "$3" in
read)
	if [[ ! -s "$STUB_SHA_FILE" ]]; then
		echo "[cache-pin] no cache pin at x; the declarer runs \\`make cache-declare ref=<commit>\\`" >&2
		exit 3
	fi
	cat "$STUB_SHA_FILE"
	;;
env) printf '%s\\n' {" ".join(f"'{line}'" for line in PIN_ENV)} ;;
{INFRA_ARMS}
esac
"""

DECLARE_PYTHON_STUB = f"""#!/usr/bin/env bash
printf 'python %s %s\\n' "$PWD" "$*" >>"$STUB_LOG"
if [[ "$2" == cli.meta.cache && -z "$3" ]]; then
	mkdir -p "$(dirname "$INFINITO_CACHE_PACKAGE_FRONTEND_CONF")"
	echo "rendered map" >"$INFINITO_CACHE_PACKAGE_FRONTEND_CONF"
	exit 0
fi
case "$3" in
resolve) git rev-parse --verify --quiet "$4^{{commit}}" ;;
declare)
	mkdir -p "$(dirname "$INFINITO_CACHE_PIN_FILE")"
	echo "$4" >"$INFINITO_CACHE_PIN_FILE"
	;;
{INFRA_ARMS}
esac
"""

DOCKER_STUB = """#!/usr/bin/env bash
printf 'docker %s\\n' "$*" >>"$STUB_LOG"
case "$1" in
ps)
	if [[ -n "$STUB_DOCKER_FAILS" ]]; then
		echo "Cannot connect to the Docker daemon" >&2
		exit 1
	fi
	[[ -n "$STUB_MOUNTED" ]] && echo infinito-package-cache-frontend
	;;
inspect)
	if [[ -n "$STUB_INSPECT_FAILS" ]]; then
		echo "Error: No such object" >&2
		exit 1
	fi
	[[ -n "$STUB_NO_MAP" ]] || echo "$STUB_MOUNTED"
	;;
esac
exit 0
"""

ROLE_STUB = """#!/usr/bin/env bash
printf '%s %s %s %s\\n' "$(basename "$0")" "$PWD" "$INFINITO_CACHE_TLS_HOSTS" "$INFINITO_CACHE_UPSTREAMS" >>"$STUB_LOG"
"""

BOOTSTRAP_STUB = f"""{ROLE_STUB}printf 'nexus %s:%s\\n' "$INFINITO_CACHE_PACKAGE_REST_HOST" "$INFINITO_CACHE_PACKAGE_PORT" >>"$STUB_LOG"
docker exec "$INFINITO_CACHE_PACKAGE_CONTAINER" true
"""

INTERRUPTED_CP_STUB = """#!/usr/bin/env bash
: >"${@: -1}"
kill -INT $$
export PATH="${PATH#*:}"
exec cp "$@"
"""

RENDER_STUB = """import os
import pathlib

pathlib.Path("pin-file").write_text(os.environ.get("INFINITO_CACHE_PIN_FILE", "unset"))
conf = pathlib.Path(os.environ["INFINITO_CACHE_PACKAGE_FRONTEND_CONF"])
if conf.is_relative_to(pathlib.Path.cwd().resolve()) and not os.environ.get(
    "STUB_RENDER_NO_MAP"
):
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("rendered map\\n")
if os.environ.get("STUB_RENDER_FAILS"):
    raise SystemExit(1)
"""

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _checkout(root: Path, label: str) -> None:
    (root / MAP).parent.mkdir(parents=True, exist_ok=True)
    (root / MAP).write_text(f"{label} map\n", encoding="utf-8")
    for name, stub in (("bootstrap.sh", BOOTSTRAP_STUB), ("certs.sh", ROLE_STUB)):
        _executable(root / SHELL_DIR / name, stub)


def _clean_env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("INFINITO_") and k not in ("BASH_ENV", "PYTHON")
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class ApplyRun:
    """Args:
    apply: the apply.sh under test.
    sha: the commit the pin stub reports, empty for no pin.
    """

    def __init__(self, apply: Path, sha: str) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.caller = base / "caller"
        self.pin_root = base / "share" / "infinito" / "cache"
        self.pinned = self.pin_root / SHA
        self.mounted = self.pin_root / "frontend" / "upstreams.conf"
        self.served = self.pin_root / "upstreams.conf"
        self.log = base / "log"
        self.sha_file = base / "sha"
        self.sha_file.write_text(sha, encoding="utf-8")
        self.script_dir = self.caller / "scripts" / "system" / "cache"
        self.script_dir.mkdir(parents=True)
        (self.script_dir / "apply.sh").symlink_to(apply)
        (self.script_dir / "pin.sh").symlink_to(PIN_SH)
        _checkout(self.caller, "caller")
        _checkout(self.pinned, "pinned")
        self.mounted.parent.mkdir(parents=True)
        self.mounted.write_text("old map\n", encoding="utf-8")
        bin_dir = base / "bin"
        python = _executable(bin_dir / "python-stub", PYTHON_STUB)
        _executable(bin_dir / "docker", DOCKER_STUB)
        loader = self.caller / "scripts" / "meta" / "env" / "load.sh"
        loader.parent.mkdir(parents=True)
        loader.write_text(
            f"export PYTHON={python}\n"
            f"export INFINITO_CACHE_PIN_ROOT={self.pin_root}\n"
            f"export INFINITO_CACHE_PIN_FILE={base / 'state' / 'cache.ref'}\n"
            f"export INFINITO_CACHE_PACKAGE_FRONTEND_CONF={self.served}\n"
            f"export INFINITO_CACHE_PACKAGE_PORT={PUBLISHED_PORT}\n"
            f"export INFINITO_CACHE_PACKAGE_REST_HOST={PUBLISHED_HOST}\n",
            encoding="utf-8",
        )
        self.env = _clean_env()
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(self.log),
            STUB_SHA_FILE=str(self.sha_file),
            STUB_MOUNTED=str(self.mounted),
        )

    def argv(self, stage: str = "") -> list[str]:
        return ["bash", str(self.script_dir / "apply.sh"), *([stage] if stage else [])]

    def run(self, stage: str = "") -> ApplyRun:
        self.done = subprocess.run(
            self.argv(stage),
            cwd=self.caller,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        return self

    @property
    def lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return _read(self.log).splitlines()

    def close(self) -> None:
        self.tmp.cleanup()


class TestApply(unittest.TestCase):
    def _setup(self, sha: str = SHA) -> ApplyRun:
        run = ApplyRun(APPLY, sha)
        self.addCleanup(run.close)
        return run

    def _run(self, sha: str = SHA, stage: str = "") -> ApplyRun:
        return self._setup(sha).run(stage)

    def test_apply_serves_the_pinned_checkout_and_never_the_caller(self) -> None:
        run = self._run()
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        self.assertEqual(_read(run.mounted), "pinned map\n")
        self.assertFalse(run.mounted.stat().st_mode & stat.S_IWUSR)
        roles = [line for line in run.lines if line.startswith(("bootstrap", "certs"))]
        self.assertEqual(
            [line.split(" ", 2)[:2] for line in roles],
            [["bootstrap.sh", str(run.pinned)], ["certs.sh", str(run.pinned)]],
        )
        self.assertTrue(all("pinned.example" in line for line in roles))
        self.assertFalse(any(str(run.caller) in line for line in roles))
        self.assertIn(
            f"python {run.caller} -m cli.meta.cache.pin applied {SHA}", run.lines
        )
        self.assertIn(
            "docker exec infinito-package-cache-frontend nginx -s reload", run.lines
        )

    def test_every_docker_call_goes_through_the_infra_runner(self) -> None:
        run = self._run()
        docker = [line for line in run.lines if line.startswith("docker ")]
        through_runner = [
            line.split(" -m cli.administration.infra ", 1)[1]
            for line in run.lines
            if " -m cli.administration.infra docker " in line
        ]
        self.assertNotEqual(docker, [])
        self.assertEqual(docker, through_runner)

    def test_the_pinned_bootstrap_reaches_nexus_inside_the_infra_runner(
        self,
    ) -> None:
        run = self._run()
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        self.assertIn(
            f"python {run.caller} -m cli.administration.infra docker exec {NEXUS} true",
            run.lines,
        )
        self.assertIn(f"docker exec {NEXUS} true", run.lines)

    def test_the_bootstrap_reaches_nexus_on_its_loopback_and_internal_port(
        self,
    ) -> None:
        run = self._run()
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        nexus = [line for line in run.lines if line.startswith("nexus ")]
        self.assertEqual(nexus, [f"nexus 127.0.0.1:{NEXUS_PORT}"])
        self.assertFalse(any(PUBLISHED_HOST in line for line in run.lines))

    def test_a_stopped_infra_runner_is_a_stopped_frontend(self) -> None:
        run = self._setup()
        run.env["STUB_RUNNER_DOWN"] = "1"
        run.run()
        self.assertEqual(run.done.returncode, 1)
        self.assertIn(
            "is not running; start it with make infra-update", run.done.stderr
        )
        self.assertNotIn("docker ps failed", run.done.stderr)
        self.assertEqual(_read(run.mounted), "old map\n")

    def test_apply_reports_drift_against_the_pinned_checkout(self) -> None:
        run = self._run()
        self.assertIn(
            f"python {run.caller} -m cli.meta.cache.pin drift {run.pinned}", run.lines
        )

    def test_prepare_installs_the_pinned_map_before_the_stack_starts(self) -> None:
        run = self._run(stage="prepare")
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        self.assertEqual(_read(run.served), "pinned map\n")
        self.assertEqual(_read(run.mounted), "old map\n")
        self.assertEqual(
            [
                line.split(" ", 2)[:2]
                for line in run.lines
                if line.startswith(("bootstrap", "certs"))
            ],
            [["certs.sh", str(run.pinned)]],
        )
        self.assertFalse(any(line.startswith("docker") for line in run.lines))

    def test_no_pin_fails_loudly_and_touches_nothing(self) -> None:
        run = self._run(sha="")
        self.assertNotEqual(run.done.returncode, 0)
        self.assertIn("make cache-declare", run.done.stderr)
        self.assertEqual(_read(run.mounted), "old map\n")
        self.assertFalse(
            any(line.startswith(("bootstrap", "certs")) for line in run.lines)
        )

    def test_a_frontend_serving_another_pin_root_is_refused(self) -> None:
        run = self._setup()
        foreign = run.caller / MAP
        run.env["STUB_MOUNTED"] = str(foreign)
        run.run()
        self.assertEqual(run.done.returncode, FOREIGN_MAP, run.done.stderr)
        self.assertIn(f"from {foreign}, outside", run.done.stderr)
        self.assertIn(str(run.pin_root), run.done.stderr)
        self.assertEqual(_read(foreign), "caller map\n")
        self.assertFalse(
            any(line.startswith(("bootstrap", "certs")) for line in run.lines)
        )

    def test_a_docker_that_does_not_answer_is_no_stopped_frontend(self) -> None:
        run = self._setup()
        run.env["STUB_DOCKER_FAILS"] = "1"
        run.run()
        self.assertEqual(run.done.returncode, 1)
        self.assertIn("docker ps failed", run.done.stderr)
        self.assertNotIn("is not running", run.done.stderr)
        self.assertEqual(_read(run.mounted), "old map\n")

    def test_apply_waits_for_the_lock_and_applies_the_pin_it_then_reads(
        self,
    ) -> None:
        run = self._setup()
        with (run.pin_root / ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            proc = subprocess.Popen(
                run.argv(),
                cwd=run.caller,
                env=run.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.addCleanup(proc.kill)
            deadline = time.monotonic() + 10
            while not any(" read" in line for line in run.lines):
                self.assertLess(time.monotonic(), deadline, "apply never read the pin")
                time.sleep(0.05)
            time.sleep(0.5)
            self.assertIsNone(proc.poll(), "apply ran without waiting for the lock")
            _checkout(run.pin_root / SHA2, "second")
            run.sha_file.write_text(SHA2, encoding="utf-8")
            fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertEqual(proc.wait(timeout=30), 0)
        self.assertEqual(_read(run.mounted), "second map\n")
        self.assertIn(
            f"python {run.caller} -m cli.meta.cache.pin applied {SHA2}", run.lines
        )


class TestMapRefusals(unittest.TestCase):
    def _refused(self, **changed: str) -> ApplyRun:
        """Args:
            changed: STUB_* settings of the docker stub for this run.

        Returns:
            The finished apply, which must have touched nothing.
        """
        run = ApplyRun(APPLY, SHA)
        self.addCleanup(run.close)
        run.env.update(changed)
        run.run()
        self.assertEqual(_read(run.mounted), "old map\n")
        self.assertFalse(
            any(line.startswith(("bootstrap", "certs")) for line in run.lines)
        )
        return run

    def test_a_failed_inspect_is_no_foreign_map(self) -> None:
        run = self._refused(STUB_INSPECT_FAILS="1")
        self.assertEqual(run.done.returncode, 1, run.done.stderr)

    def test_a_frontend_without_a_mounted_map_is_no_foreign_map(self) -> None:
        run = self._refused(STUB_NO_MAP="1")
        self.assertEqual(run.done.returncode, 1, run.done.stderr)
        self.assertIn("mounts no map", run.done.stderr)

    def test_a_refused_pin_root_is_no_foreign_map(self) -> None:
        run = ApplyRun(APPLY, SHA)
        self.addCleanup(run.close)
        loader = run.caller / "scripts" / "meta" / "env" / "load.sh"
        loader.write_text(
            _read(loader).replace(
                f"INFINITO_CACHE_PIN_ROOT={run.pin_root}",
                "INFINITO_CACHE_PIN_ROOT=pins",
            ),
            encoding="utf-8",
        )
        run.run()
        self.assertEqual(run.done.returncode, 1, run.done.stderr)
        self.assertIn("is not an absolute path", run.done.stderr)
        self.assertEqual(_read(run.mounted), "old map\n")

    def test_there_is_no_stage_that_skips_the_apply(self) -> None:
        run = ApplyRun(APPLY, SHA)
        self.addCleanup(run.close)
        run.run("refresh")
        self.assertEqual(run.done.returncode, 2)
        self.assertIn("unknown stage 'refresh'", run.done.stderr)


class TestMapInstall(unittest.TestCase):
    def test_an_interrupt_during_the_copy_never_truncates_the_served_map(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _checkout(root / "pinned", "pinned")
            target = root / "pins" / "upstreams.conf"
            target.parent.mkdir()
            target.write_text("served map\n", encoding="utf-8")
            target.chmod(0o444)
            inode = target.stat().st_ino
            stubs = root / "bin"
            _executable(stubs / "cp", INTERRUPTED_CP_STUB)
            done = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; cache_pin_install_map "$2" "$3"',
                    "install-map",
                    str(PIN_SH),
                    str(root / "pinned"),
                    str(target),
                ],
                env={
                    **_clean_env(),
                    "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(_read(target), "pinned map\n")
            self.assertEqual(target.stat().st_ino, inode)
            self.assertFalse(target.stat().st_mode & stat.S_IWUSR)


class TempRepo:
    """Args:
    with_pin_cli: whether the commit carries cli/meta/cache/pin.
    """

    def __init__(self, with_pin_cli: bool = True) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        (self.repo / "roles").mkdir()
        (self.repo / "roles" / "networks.yml").write_text(
            "committed\n", encoding="utf-8"
        )
        (self.repo / "locale").mkdir()
        (self.repo / "locale" / "big.po").write_text("catalog\n", encoding="utf-8")
        render = self.repo / "cli" / "meta" / "cache" / "__main__.py"
        render.parent.mkdir(parents=True)
        render.write_text(RENDER_STUB, encoding="utf-8")
        for package in ("cli", "cli/meta", "cli/meta/cache"):
            (self.repo / package / "__init__.py").write_text("", encoding="utf-8")
        if with_pin_cli:
            (self.repo / PIN_CLI).parent.mkdir(parents=True)
            (self.repo / PIN_CLI).write_text("", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "c")
        self.sha = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "roles" / "networks.yml").write_text(
            "uncommitted\n", encoding="utf-8"
        )

    def materialize(self, root: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "bash",
                "-c",
                f'source "{PIN_SH}"; cache_pin_materialize "$1" && echo "$CACHE_PIN_CHECKOUT"',
                "_",
                self.sha,
            ],
            cwd=self.repo,
            env={
                **os.environ,
                **GIT_ENV,
                "INFINITO_CACHE_PIN_ROOT": root,
                "PYTHON": sys.executable,
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def close(self) -> None:
        self.tmp.cleanup()


class TestMaterialize(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TempRepo()
        self.addCleanup(self.temp.close)
        self.root = self.temp.base / "pins"

    def test_the_committed_state_is_materialized_and_rendered(self) -> None:
        done = self.temp.materialize(str(self.root))
        self.assertEqual(done.returncode, 0, done.stderr)
        checkout = Path(done.stdout.strip())
        self.assertEqual(checkout, self.root / self.temp.sha)
        self.assertEqual(
            _read(checkout / "roles" / "networks.yml"),
            "committed\n",
        )
        self.assertEqual(_read(checkout / MAP), "rendered map\n")
        self.assertFalse((checkout / "locale").exists())
        self.assertFalse(checkout.is_relative_to(self.temp.repo))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [self.temp.sha])

    def test_a_symlinked_root_is_resolved_so_the_map_is_rendered(self) -> None:
        self.root.mkdir()
        link = self.temp.base / "link"
        link.symlink_to(self.root)
        done = self.temp.materialize(str(link))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(Path(done.stdout.strip()), self.root / self.temp.sha)
        self.assertEqual(
            _read(self.root / self.temp.sha / MAP),
            "rendered map\n",
        )

    def test_a_render_without_a_map_moves_nothing_into_place(self) -> None:
        done = self.temp.materialize(str(self.root), STUB_RENDER_NO_MAP="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual([p.name for p in self.root.iterdir()], [])

    def test_a_failed_render_leaves_neither_checkout_nor_scratch(self) -> None:
        done = self.temp.materialize(str(self.root), STUB_RENDER_FAILS="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual([p.name for p in self.root.iterdir()], [])

    def test_the_render_never_filters_against_another_pin(self) -> None:
        done = self.temp.materialize(
            str(self.root), INFINITO_CACHE_PIN_FILE=str(self.temp.base / "cache.ref")
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(_read(self.root / self.temp.sha / "pin-file"), "")

    def test_a_symlinked_checkout_is_refused(self) -> None:
        self.root.mkdir()
        elsewhere = self.temp.base / "elsewhere"
        elsewhere.mkdir()
        (self.root / self.temp.sha).symlink_to(elsewhere)
        done = self.temp.materialize(str(self.root))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("symlink", done.stderr)

    def test_a_relative_or_in_repository_root_is_refused(self) -> None:
        for root in ("pins", str(self.temp.repo / ".pins")):
            with self.subTest(root=root):
                done = self.temp.materialize(root)
                self.assertNotEqual(done.returncode, 0)
                self.assertFalse((self.temp.repo / ".pins").exists())
                self.assertFalse((self.temp.repo / "pins").exists())


class DeclareRun:
    """Args:
    temp: the repository whose HEAD is declared.
    docker: extra STUB_* settings of the docker stub.
    """

    def __init__(self, temp: TempRepo, **docker: str) -> None:
        base = temp.base
        self.root = base / "share" / "infinito" / "cache"
        self.pin_file = base / "state" / "cache.ref"
        self.log = base / "log"
        script_dir = temp.repo / "scripts" / "system" / "cache"
        script_dir.mkdir(parents=True)
        for script in (DECLARE, APPLY, PIN_SH):
            (script_dir / script.name).symlink_to(script)
        bin_dir = base / "bin"
        python = _executable(bin_dir / "python-stub", DECLARE_PYTHON_STUB)
        _executable(bin_dir / "docker", DOCKER_STUB)
        loader = temp.repo / "scripts" / "meta" / "env" / "load.sh"
        loader.parent.mkdir(parents=True)
        loader.write_text(
            f"export PYTHON={python}\n"
            f"export INFINITO_CACHE_PIN_ROOT={self.root}\n"
            f"export INFINITO_CACHE_PIN_FILE={self.pin_file}\n"
            f"export INFINITO_CACHE_PACKAGE_FRONTEND_CONF={self.root / 'upstreams.conf'}\n",
            encoding="utf-8",
        )
        env = _clean_env()
        env.update(
            GIT_ENV,
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(self.log),
        )
        env.update({"STUB_MOUNTED": "", **docker})
        self.done = subprocess.run(
            ["bash", str(script_dir / "declare.sh"), "HEAD"],
            cwd=temp.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.lines = _read(self.log).splitlines() if self.log.exists() else []


class TestDeclare(unittest.TestCase):
    def _declare(
        self, with_pin_cli: bool, **docker: str
    ) -> tuple[TempRepo, DeclareRun]:
        temp = TempRepo(with_pin_cli=with_pin_cli)
        self.addCleanup(temp.close)
        return temp, DeclareRun(temp, **docker)

    def test_a_docker_that_does_not_answer_fails_the_declare(self) -> None:
        temp, run = self._declare(with_pin_cli=True, STUB_DOCKER_FAILS="1")
        self.assertEqual(run.done.returncode, 1)
        self.assertIn("docker ps failed", run.done.stderr)
        self.assertIn("pinned but not applied", run.done.stderr)
        self.assertNotIn("is not running", run.done.stdout)
        self.assertEqual(_read(run.pin_file).strip(), temp.sha)

    def test_a_frontend_serving_another_pin_root_fails_the_declare(self) -> None:
        live = Path("/live/upstreams.conf")
        temp, run = self._declare(with_pin_cli=True, STUB_MOUNTED=str(live))
        self.assertEqual(run.done.returncode, 1)
        self.assertIn(f"from {live}, outside", run.done.stderr)
        self.assertIn("pinned but not applied", run.done.stderr)
        self.assertFalse(any(" read" in line for line in run.lines))
        self.assertEqual(_read(run.pin_file).strip(), temp.sha)

    def test_a_commit_without_the_pin_cli_is_refused_and_nothing_is_pinned(
        self,
    ) -> None:
        temp, run = self._declare(with_pin_cli=False)
        self.assertEqual(run.done.returncode, 2, run.done.stderr)
        self.assertIn("predates the cache pin", run.done.stderr)
        self.assertFalse(run.pin_file.exists())
        self.assertFalse((run.root / temp.sha).exists())

    def test_without_a_running_frontend_the_pin_waits_for_infra_update(
        self,
    ) -> None:
        temp, run = self._declare(with_pin_cli=True)
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        self.assertEqual(_read(run.pin_file).strip(), temp.sha)
        self.assertEqual(_read(run.root / temp.sha / MAP), "rendered map\n")
        self.assertIn("make infra-update", run.done.stdout)
        self.assertIn("that starts the infra runner", run.done.stdout)
        self.assertFalse(any(" read" in line for line in run.lines))

    def test_a_declare_before_the_infra_runner_starts_pins_and_succeeds(
        self,
    ) -> None:
        temp, run = self._declare(with_pin_cli=True, STUB_RUNNER_DOWN="1")
        self.assertEqual(run.done.returncode, 0, run.done.stderr)
        self.assertEqual(_read(run.pin_file).strip(), temp.sha)
        self.assertIn("make infra-update", run.done.stdout)
        self.assertNotIn("pinned but not applied", run.done.stderr)


def _cache_starters(lines: list[str]) -> list[str]:
    """
    Args:
        lines: shell lines of a script.

    Returns:
        The make targets the lines run that compose/stacks.yml resolves to
        the cache stack, so they start or address the infra runner.
    """
    stacks, graph = load(), makefile_calls()
    return sorted(
        target
        for line in lines
        for target in make_calls(line)
        if CACHE_STACK in resolve(target, stacks, graph)
    )


def _starters_before_the_declare(lines: list[str]) -> list[str]:
    """
    Args:
        lines: shell lines of a workspace bootstrap script.

    Returns:
        The cache stack starters the lines run above the workspace declare.
    """
    return _cache_starters(lines[: lines.index(WORKSPACE_DECLARE)])


class TestWorkspaceBootstrap(unittest.TestCase):
    def test_the_fresh_ci_host_declares_its_own_head_before_any_call_starts_the_cache(
        self,
    ) -> None:
        lines = read_text(str(WORKSPACE_BOOTSTRAP)).splitlines()
        self.assertEqual(_starters_before_the_declare(lines), [])
        declare = lines.index(WORKSPACE_DECLARE)
        self.assertIn("compose-up", _cache_starters(lines[declare + 1 :]))

    def test_the_old_order_with_the_lint_bootstrap_above_the_declare_is_caught(
        self,
    ) -> None:
        self.assertEqual(
            _starters_before_the_declare(
                ["make environment-bootstrap", WORKSPACE_DECLARE]
            ),
            ["environment-bootstrap"],
        )

    def test_the_pin_root_is_the_same_path_for_the_container_and_the_daemon(
        self,
    ) -> None:
        env = load_yaml(WORKSPACE_WORKFLOW)["jobs"][WORKSPACE_JOB]["env"]
        self.assertEqual(env[PIN_ROOT_KEY], "/mnt/cache/pin")
        handed = {
            ("-e", PIN_ROOT_KEY),
            ("-v", f"${{{PIN_ROOT_KEY}}}:${{{PIN_ROOT_KEY}}}"),
        }
        self.assertTrue(
            any(
                handed <= options
                for options in step_options(WORKSPACE_WORKFLOW, WORKSPACE_JOB)
            )
        )


if __name__ == "__main__":
    unittest.main()
