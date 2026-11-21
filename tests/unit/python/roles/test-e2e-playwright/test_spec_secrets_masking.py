from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest.mock
from pathlib import Path
from urllib.parse import quote, quote_plus

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT, ROLE

FILES = ROLE / "files"
HELPER = FILES / "spec_secrets.py"
MASKER = FILES / "spec_secrets_mask.py"
MATCHER = FILES / "spec_secrets_match.py"
RERUN = PROJECT_ROOT / "scripts" / "tests" / "e2e" / "rerun-spec.sh"
PARENT_LINE = 'PARENT = Path("/tmp/infinito-playwright-spec-secrets")'
VALUE = "Pa%\"s<w&r'd\\9X Sentinel-Value-9f3c abcdefghijklmnopqrstuvwxyz0123456789"
SHORT_VALUE = "abc12"
STAGED_ENV = f"APP_BASE_URL=https://x.example/{VALUE[16:40]}\n"
TRUSTED = f"// {VALUE[16:40]}\n"
WINDOW = 8
SEAM = 4
DEAD_PID = 2**22 + 1
ESC = "\x1b"
EXIT_REMOVAL = 'docker rm --force "$run_name" >/dev/null 2>&1; python3 -B'
PRE_SCRUB = '\tpython3 -B "$masker" scrub "$secrets_dir" "$stage_dir" "$reports_dir"\n'
FINAL_FROM_DIR = (
    "scrub(stage, reports, automaton, kept)",
    "scrub(stage, reports, automaton, read_staged(directory, stage))",
)


def xml(text: str) -> str:
    """Escape text the way a JUnit attribute holds it.

    Args:
        text: the text.

    Returns:
        The text with ``& " ' < >`` as entities.
    """
    for char, entity in (
        ("&", "&amp;"),
        ('"', "&quot;"),
        ("'", "&apos;"),
        ("<", "&lt;"),
        (">", "&gt;"),
    ):
        text = text.replace(char, entity)
    return text


JSON = json.dumps(VALUE)[1:-1]
FORMS = {
    "raw": VALUE,
    "json": JSON,
    "xml": xml(VALUE),
    "json_in_xml_attribute": xml(JSON),
    "percent_encoded": quote(VALUE, safe=""),
    "form_encoded": quote_plus(VALUE),
    "double_percent": quote(quote(VALUE, safe=""), safe=""),
    "form_then_percent": quote(quote_plus(VALUE), safe=""),
    "json_then_percent": JSON.replace("%", "%25"),
    "preview_truncated_49": VALUE[:49] + "…",
    "single_quoted_inspect": VALUE.replace("\\", "\\\\").replace("'", "\\'"),
    "ansi_split": f"{VALUE[:4]}{ESC}[7m{VALUE[4:30]}{ESC}[27m{VALUE[30:]}",
    "json_in_json": json.dumps(JSON)[1:-1],
}
FAKE_RUN = """\
import json, pathlib, shutil, sys
value, short, stage, reports, gone = sys.argv[1:6]
if gone:
    shutil.rmtree(gone)
print(f"Call log: - fill({json.dumps(value)}) {value} {short}")
print(f"Error: {value}", file=sys.stderr)
attribute = json.dumps(value)[1:-1]
for char, entity in (("&", "&amp;"), ('"', "&quot;"), ("<", "&lt;"), (">", "&gt;")):
    attribute = attribute.replace(char, entity)
junit = f'<failure message="fill(&quot;{attribute}&quot;)"><![CDATA[{value}]]></failure>'
pathlib.Path(reports, "playwright-junit.xml").write_text(junit)
pathlib.Path(reports, ".masked.1.junit").write_text(junit)
pathlib.Path(reports, "node_modules").mkdir()
pathlib.Path(reports, "node_modules", "leak.txt").write_text(value)
pathlib.Path(stage, "volume").mkdir()
pathlib.Path(stage, "volume", "download.txt").write_text(value)
sys.exit(3)
"""
FAKE_DOCKER = """\
import os, pathlib, signal, subprocess, sys
probe = pathlib.Path(os.environ["PROBE_DIR"])
args = sys.argv[1:]
if args[0] == "rm":
    pidfile = probe / f"{args[-1]}.pid"
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass
    sys.exit(0)
name = args[args.index("--name") + 1]
cidfile = next((a.split("=", 1)[1] for a in args if a.startswith("--cidfile=")), "")
reports = next(a for a in args if a.endswith(":/reports")).rsplit(":", 1)[0]
mount = next(a for a in args if a.startswith("type=bind,src=")).split(",")[1][4:]
value = pathlib.Path(mount, "LONG_KEY").read_text()
for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(signum, signal.SIG_IGN)
(probe / "masker.pid").write_text(str(os.getppid()))
pid1 = pathlib.Path(__file__).with_name("pid1.py")
container = subprocess.Popen(
    [sys.executable, str(pid1), str(probe / f"{name}.pid"), cidfile, name, reports, value],
    start_new_session=True,
)
code = container.wait()
sys.exit(128 - code if code < 0 else code)
"""
PID1 = """\
import os, pathlib, sys, time
pidfile, cidfile, name, reports, value = sys.argv[1:6]
pathlib.Path(pidfile).write_text(str(os.getpid()))
if cidfile:
    pathlib.Path(cidfile).write_text(name)
for turn in range(int(os.environ.get("PID1_TURNS", "600"))):
    pathlib.Path(reports, "playwright-junit.xml").write_text(f"<failure>{value}</failure>")
    if not turn:
        print("started", flush=True)
    time.sleep(0.1)
"""


def install(bin_dir: Path, root: Path, *replacements: tuple[str, str]) -> Path:
    """Copy the three helpers into a dir, their parent moved below a scratch dir.

    Args:
        bin_dir: where the helpers go.
        root: the scratch dir.
        *replacements: pairs of text the masker and matcher together hold
            exactly once and its replacement, for a negative control.

    Returns:
        The installed ``spec_secrets.py``.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    helper = bin_dir / HELPER.name
    helper.write_text(
        read_text(str(HELPER)).replace(
            PARENT_LINE, f'PARENT = Path("{root / "spec-secrets"}")'
        ),
        encoding="utf-8",
    )
    sources = {path.name: read_text(str(path)) for path in (MASKER, MATCHER)}
    for old, new in replacements:
        holders = [name for name, text in sources.items() if text.count(old) == 1]
        if len(holders) != 1 or sum(t.count(old) for t in sources.values()) != 1:
            raise AssertionError(f"the masker no longer holds {old!r} once")
        sources[holders[0]] = sources[holders[0]].replace(old, new)
    for name, text in sources.items():
        (bin_dir / name).write_text(text, encoding="utf-8")
    return helper


def load_masker(*replacements: tuple[str, str]):
    """Load the masker in this process, its pieces replaced for a control.

    Args:
        *replacements: pairs of text the masker and matcher together hold
            exactly once and its replacement.

    Returns:
        The module, with fresh copies of the helper and the matcher.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        install(bin_dir, Path(tmp), *replacements)
        sys.path.insert(0, str(bin_dir))
        for name in ("spec_secrets", "spec_secrets_match"):
            sys.modules.pop(name, None)
        try:
            path = bin_dir / MASKER.name
            spec = importlib.util.spec_from_file_location("spec_secrets_mask", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(bin_dir))
    return module


def make_run(root: Path, helper: Path, rendered: str) -> Path:
    """Create a run directory with the helper and split values into it.

    Args:
        root: the scratch dir.
        helper: the installed ``spec_secrets.py``.
        rendered: the ``KEY=VALUE`` lines.

    Returns:
        The run directory.
    """
    created = subprocess.run(
        [sys.executable, str(helper), "create", "0", str(os.getpid())],
        capture_output=True,
        text=True,
        check=True,
    )
    directory = Path(created.stdout.strip())
    (directory / ".rendered").write_text(rendered, encoding="utf-8")
    subprocess.run(
        [sys.executable, str(helper), "split", str(directory)],
        capture_output=True,
        check=True,
    )
    return directory


def fake_docker(bin_dir: Path) -> Path:
    """Write a docker stand-in whose container runs in a session of its own.

    Args:
        bin_dir: where it goes, next to its ``pid1.py``.

    Returns:
        The executable; ``run`` reads the value from the mount and starts a
        container that rewrites the JUnit report with it every 0.1 s and
        ignores HUP, INT and TERM; ``rm --force <name>`` kills it.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "pid1.py").write_text(PID1, encoding="utf-8")
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}", encoding="utf-8")
    docker.chmod(0o755)
    return docker


def scratch_text(path: Path) -> str:
    """Read a file a test wrote into its own scratch dir, fresh each time.

    Args:
        path: the file, which the masker may have rewritten since.

    Returns:
        Its text.
    """
    return path.read_text(encoding="utf-8")  # nocheck: cache-read


def leaks(text: str, window: int = WINDOW) -> bool:
    """Tell whether any piece of ``VALUE`` of ``window`` bytes or more shows.

    Args:
        text: masked output.
        window: the shortest piece to look for, by default as long as the
            masker's ``MASK_MIN``.

    Returns:
        Whether such a piece shows.
    """
    return any(VALUE[at : at + window] in text for at in range(len(VALUE) - window + 1))


def reap(pidfile: Path) -> bool:
    """Kill the fake container a pid file names, if it still runs.

    Args:
        pidfile: the file the container wrote its pid to.

    Returns:
        Whether it was still running; a zombie whose parent died before it
        and that no init reaped yet counts as gone.
    """
    pid = int(scratch_text(pidfile))
    try:
        state = scratch_text(Path(f"/proc/{pid}/stat")).rsplit(") ", 1)[1][:1]
    except OSError:
        return False
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    return state != "Z"


def form_leaks(module) -> list[str]:
    """Mask each form Playwright writes a value in, one line each.

    Args:
        module: the loaded masker.

    Returns:
        The forms not masked whole, so that a byte of the value shows.
    """
    automaton = module.Automaton([VALUE.encode()])
    found = []
    for name, form in FORMS.items():
        out = module.Stream(automaton).feed(f"<<{form}>>\n".encode(), final=True)
        body = re.sub(r"\x1b\[[0-9;]*m", "", out.decode().strip()[2:-2])
        if body.removesuffix("…") != "***":
            found.append(name)
    return found


def chunk_leaks(module) -> bool:
    """Feed a line without a break, the value across the scan boundary.

    Args:
        module: the loaded masker.

    Returns:
        Whether a piece of the value of ``SEAM`` bytes or more shows: a scan
        without overlap masks each side of the boundary that holds 8 bytes
        of the value, so only the shorter side, 5 bytes here, shows.
    """
    automaton = module.Automaton([VALUE.encode()])
    stream = module.Stream(automaton)
    data = (
        b"." * (module.CHUNK - 5)
        + VALUE.encode()
        + b"." * (module.CHUNK + automaton.reach)
    )
    out = b"".join(
        stream.feed(data[at : at + 4096]) for at in range(0, len(data), 4096)
    )
    out += stream.feed(b"", final=True)
    return b"***" not in out or leaks(out.decode(), SEAM)


def masked_run(*replacements: tuple[str, str], owner_gone: bool = False) -> list[str]:
    """Run a failing fake container through ``mask`` and look for the value.

    Args:
        *replacements: changes to the masker or matcher, for a negative control.
        owner_gone: whether the container removes the run directory first,
            as the hold child does once the play or rerun shell is gone.

    Returns:
        One message per place the value shows, among them a ``.masked.``
        file the container wrote and one a killed scrub left, a short one
        is masked, a staged file is touched or the exit code changed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(
            root, helper, f"LONG_KEY={VALUE}\nSHORT_KEY={SHORT_VALUE}\n"
        )
        stage, reports = root / "stage", root / "reports"
        (stage / "node_modules").mkdir(parents=True)
        (stage / ".env").write_text(STAGED_ENV)
        npm = stage / "node_modules" / "package.json"
        npm.write_text(VALUE)
        older = reports / "variant-0" / "sync" / "playwright-junit.xml"
        older.parent.mkdir(parents=True)
        older.write_text(xml(JSON))
        os.utime(older, (1000, 1000))
        stale = reports / f".masked.{DEAD_PID}.abcd"
        stale.write_text(VALUE)
        fake = [sys.executable, "-c", FAKE_RUN, VALUE, SHORT_VALUE, str(stage)]
        fake += [str(reports), str(directory) if owner_gone else ""]
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        paths = [str(directory), str(stage), str(reports)]
        result = subprocess.run(
            [*masker, *paths, "--", *fake],
            capture_output=True,
            check=False,
        )
        problems = [] if result.returncode == 3 else [f"rc {result.returncode}"]
        shown = {
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
            "junit": scratch_text(reports / "playwright-junit.xml"),
            "older report": scratch_text(older),
            "reports node_modules": scratch_text(reports / "node_modules" / "leak.txt"),
            "stage volume": scratch_text(stage / "volume" / "download.txt"),
            "forged temp": scratch_text(reports / ".masked.1.junit"),
            "stale temp": scratch_text(stale),
        }
        problems += [
            f"{name} shows the value" for name, text in shown.items() if leaks(text)
        ]
        if SHORT_VALUE not in shown["stdout"]:
            problems.append("a value below the minimum was masked")
        if scratch_text(npm) != VALUE:
            problems.append("npm's install tree was rewritten")
        if scratch_text(stage / ".env") != STAGED_ENV:
            problems.append("a staged file was rewritten")
        return problems


def stopped_run(how: signal.Signals, *replacements: tuple[str, str]) -> list[str]:
    """Stop a masker whose container survives it, then scrub with the tool.

    Args:
        how: TERM, which the masker answers, or KILL, which it cannot.
        *replacements: changes to the masker or matcher, for a negative control.

    Returns:
        What happened, in order: the masker's exit code, whether the report
        showed the value right after, whether the container outlived the
        scrub, and whether the report showed the value after the scrub.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(root, helper, f"LONG_KEY={VALUE}\n")
        stage, reports, probe = root / "stage", root / "reports", root / "probe"
        for path in (stage, reports, probe):
            path.mkdir()
        docker = fake_docker(root / "bin")
        env = {**os.environ, "PROBE_DIR": str(probe)}
        masker = [sys.executable, str(root / "bin" / MASKER.name)]
        mount = f"type=bind,src={directory},dst=/run/spec-secrets,readonly"
        run = [str(docker), "run", "--name", "c1", f"--cidfile={directory}/.cid"]
        run += ["--mount", mount, "-v", f"{reports}:/reports", "image"]
        paths = [str(directory), str(stage), str(reports)]
        proc = subprocess.Popen(
            [*masker, "mask", *paths, "--", *run],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        try:
            proc.stdout.readline()
            os.killpg(proc.pid, how)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            proc.stdout.close()
            time.sleep(0.3)
            junit = reports / "playwright-junit.xml"
            events = [
                f"masker {proc.returncode}",
                f"leaks {leaks(scratch_text(junit))}",
            ]
            scrub = [*masker, "scrub", *paths, str(docker)]
            subprocess.run(scrub, capture_output=True, check=False, env=env)
            time.sleep(0.5)
            events.append(f"container alive {reap(probe / 'c1.pid')}")
            events.append(f"scrubbed leaks {leaks(scratch_text(junit))}")
        finally:
            reap(probe / "c1.pid")
        return events


def rerun(script: str, *, kill: bool, leftovers: bool) -> list[str]:
    """Rerun a deployed stage dir, its masker SIGKILLed or earlier runs' files left.

    Args:
        script: the text of ``rerun-spec.sh`` to run.
        kill: whether to SIGKILL the masker while its container runs on.
        leftovers: whether a killed run left the value in clear in the stage
            dir, in a new file and appended to the ``.env``.

    Returns:
        Which containers outlived the rerun, whether the report and the
        leftover show the value afterwards, the ``.env``'s state, and whether
        the deployed ``package.json`` and the restaged spec, both holding a
        piece of the value, stayed as they were.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = root / "repo"
        (repo / "scripts/tests/e2e").mkdir(parents=True)
        (repo / "scripts/tests/e2e/rerun-spec.sh").write_text(script)
        files = repo / "roles/test-e2e-playwright/files"
        install(files, root)
        shutil.copy(FILES / "playwright.config.js", files)
        role = repo / "roles/web-app-x"
        source = role / ROLE_FILE_PLAYWRIGHT_SPEC
        source.parent.mkdir(parents=True)
        source.write_text(TRUSTED)
        (role / "templates").mkdir()
        (role / "templates/playwright.secrets.j2").write_text("LONG_KEY=x\n")
        (repo / ".env").write_text(f"INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR={root}/r\n")
        stage = root / "stage" / "web-app-x"
        stage.mkdir(parents=True)
        stage.parent.chmod(0o755)
        (stage / ".env").write_text(STAGED_ENV)
        (stage / "package.json").write_text(TRUSTED)
        deploy = [sys.executable, str(files / MASKER.name), "baseline", str(stage)]
        subprocess.run(deploy, capture_output=True, check=True)
        if leftovers:
            (stage / "volume").mkdir()
            (stage / "volume" / "early.txt").write_text(VALUE)
            with (stage / ".env").open("a", encoding="utf-8") as handle:
                handle.write(f"LEAK={VALUE}\n")
        (root / "secrets.txt").write_text(f"LONG_KEY={VALUE}\n")
        probe = root / "probe"
        probe.mkdir()
        tools = root / "tools"
        fake_docker(tools)
        (tools / "python3").symlink_to(sys.executable)
        env = {
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "INFINITO_PLAYWRIGHT_STAGE_BASE_DIR": str(root / "stage"),
            "TEST_E2E_PLAYWRIGHT_IMAGE": "image",
            "PLAYWRIGHT_SPEC_SECRETS_FILE": str(root / "secrets.txt"),
            "PROBE_DIR": str(probe),
            "PID1_TURNS": "600" if kill else "3",
        }
        script_path = repo / "scripts/tests/e2e/rerun-spec.sh"
        junit = root / "r" / "web-app-x" / "playwright-junit.xml"
        containers = "infinito-playwright-rerun-*.pid"
        proc = subprocess.Popen(
            ["bash", str(script_path), "web-app-x"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            if kill:
                deadline = time.monotonic() + 20
                while not junit.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                os.kill(int(scratch_text(probe / "masker.pid")), signal.SIGKILL)
            proc.wait(timeout=30)
            time.sleep(0.5)
            alive = [reap(pidfile) for pidfile in probe.glob(containers)]
            events = [
                f"containers alive {alive}",
                f"junit leaks {leaks(scratch_text(junit))}",
            ]
            if leftovers:
                early = scratch_text(stage / "volume" / "early.txt")
                events.append(f"leftover leaks {leaks(early)}")
            env_text = scratch_text(stage / ".env")
            env_state = f"env leaks {leaks(env_text)}"
            spec = scratch_text(stage / "tests" / "playwright.spec.js")
            events += [
                "env kept" if env_text == STAGED_ENV else env_state,
                f"package kept {scratch_text(stage / 'package.json') == TRUSTED}",
                f"spec kept {spec == TRUSTED}",
            ]
        finally:
            for pidfile in probe.glob(containers):
                reap(pidfile)
        return events


def baseline_cases(*replacements: tuple[str, str]) -> list[str]:
    """Plant what another user could leave beside a stage dir, then keep and use the list.

    Args:
        *replacements: changes to the masker, for a negative control.

    Returns:
        One message per plant that worked: a hardlink at the list's path
        whose target the list is written through, a list that keeps a
        group- and world-writable mode, a forged writable list that keeps a
        leftover in clear, and a writable base dir the list is kept in.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        masker = [sys.executable, str(root / "bin" / MASKER.name)]
        stage = root / "base" / "web-app-x"
        stage.mkdir(parents=True)
        stage.parent.chmod(0o755)
        (stage / ".env").write_text(STAGED_ENV)
        listed = stage.parent / "web-app-x.staged"
        victim = root / "victim"
        victim.write_text("victim")
        victim.chmod(0o666)
        os.link(victim, listed)
        problems = []
        subprocess.run(
            [*masker, "baseline", str(stage)], capture_output=True, check=False
        )
        if scratch_text(victim) != "victim":
            problems.append("a hardlinked file was written through")
        if stat.S_IMODE(listed.stat().st_mode) != 0o600:
            problems.append("the list kept a mode others can write")
        leftover = stage / "volume" / "early.txt"
        leftover.parent.mkdir()
        leftover.write_text(VALUE)
        forged = {"volume/early.txt": hashlib.sha256(VALUE.encode()).hexdigest()}
        listed.unlink()
        listed.write_text(json.dumps(forged))
        listed.chmod(0o666)
        directory = make_run(root, helper, f"LONG_KEY={VALUE}\n")
        scrub = [*masker, "scrub", str(directory), str(stage), str(root / "reports")]
        subprocess.run(scrub, capture_output=True, check=False)
        if leaks(scratch_text(leftover)):
            problems.append("a forged writable list kept a leftover in clear")
        stage.parent.chmod(0o777)
        kept = subprocess.run(
            [*masker, "baseline", str(stage)], capture_output=True, check=False
        )
        stage.parent.chmod(0o755)
        if kept.returncode != 1:
            problems.append("a base dir others can write was accepted")
        return problems


def owner_case(module) -> tuple[list[str], list[str], bool]:
    """Keep a list, then read and keep it again as another user.

    Args:
        module: the loaded masker.

    Returns:
        The paths the list holds for its owner, those it holds for another
        user, and whether keeping it as another user is refused.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "base" / "web-app-x"
        stage.mkdir(parents=True)
        stage.parent.chmod(0o755)
        (stage / ".env").write_text(STAGED_ENV)
        module.keep_baseline(stage)
        own = list(module.read_baseline(stage))
        with unittest.mock.patch.object(os, "geteuid", return_value=os.geteuid() + 1):
            other = list(module.read_baseline(stage))
            refused = False
            try:
                module.keep_baseline(stage)
            except module.spec_secrets.SpecSecretsError:
                refused = True
        return own, other, refused


class TestSpecSecretsMasking(unittest.TestCase):
    def test_every_form_playwright_writes_a_value_in_is_masked(self) -> None:
        self.assertEqual(form_leaks(load_masker()), [])

    def test_a_value_across_the_scan_boundary_of_a_long_line_is_masked(self) -> None:
        self.assertFalse(chunk_leaks(load_masker()))

    def test_a_file_is_masked_in_chunks_and_rewritten_only_with_a_value(self) -> None:
        module = load_masker()
        automaton = module.Automaton([VALUE.encode()])
        with tempfile.TemporaryDirectory() as tmp:
            dirty = Path(tmp) / "report.xml"
            dirty.write_bytes(
                b"-" * (module.CHUNK - 9) + xml(JSON).encode() + b"\n" * 9
            )
            dirty.chmod(0o640)
            clean = Path(tmp) / "clean.xml"
            clean.write_bytes(b"-" * (3 * module.CHUNK))
            inode = clean.stat().st_ino
            self.assertTrue(module.scrub_file(dirty, automaton))
            self.assertFalse(module.scrub_file(clean, automaton))
            self.assertFalse(leaks(scratch_text(dirty)))
            self.assertEqual(stat.S_IMODE(dirty.stat().st_mode), 0o640)
            self.assertEqual(clean.stat().st_ino, inode)
            self.assertEqual(
                sorted(p.name for p in Path(tmp).iterdir()), ["clean.xml", "report.xml"]
            )

    def test_two_values_mask_independently_and_short_ones_stay(self) -> None:
        module = load_masker()
        other = "Second-Secret-Token-77"
        automaton = module.Automaton([VALUE.encode(), other.encode()])
        line = f"{other} {SHORT_VALUE} {VALUE[10:30]} {VALUE[:7]}\n".encode()
        out = module.Stream(automaton).feed(line, final=True).decode()
        self.assertEqual(out, f"*** {SHORT_VALUE} *** {VALUE[:7]}\n")

    def test_the_runner_masks_output_and_every_file_of_the_run(self) -> None:
        self.assertEqual(masked_run(), [])

    def test_the_runner_masks_from_memory_once_the_run_directory_is_gone(
        self,
    ) -> None:
        self.assertEqual(masked_run(owner_gone=True), [])

    def test_term_removes_the_container_and_masks_before_the_masker_ends(self) -> None:
        self.assertEqual(
            stopped_run(signal.SIGTERM),
            [
                "masker 137",
                "leaks False",
                "container alive False",
                "scrubbed leaks False",
            ],
        )

    def test_a_sigkill_scrub_removes_the_surviving_container_first(self) -> None:
        self.assertEqual(
            stopped_run(signal.SIGKILL),
            [
                "masker -9",
                "leaks True",
                "container alive False",
                "scrubbed leaks False",
            ],
        )

    def test_a_rerun_removes_its_container_before_its_exit_scrub(self) -> None:
        self.assertEqual(
            rerun(read_text(str(RERUN)), kill=True, leftovers=False),
            [
                "containers alive [False]",
                "junit leaks False",
                "env kept",
                "package kept True",
                "spec kept True",
            ],
        )

    def test_a_rerun_masks_what_a_killed_run_left_before_it_starts(self) -> None:
        self.assertEqual(
            rerun(read_text(str(RERUN)), kill=False, leftovers=True),
            [
                "containers alive [False]",
                "junit leaks False",
                "leftover leaks False",
                "env leaks False",
                "package kept True",
                "spec kept True",
            ],
        )

    def test_the_deploy_list_resists_what_another_user_plants(self) -> None:
        self.assertEqual(baseline_cases(), [])

    def test_a_list_or_base_dir_another_user_owns_is_not_trusted(self) -> None:
        self.assertEqual(owner_case(load_masker()), ([".env"], [], True))

    def test_bad_usage_and_a_foreign_run_directory_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for argv, code in (
                (["scrub", tmp], 2),
                (["scrub", tmp, tmp, tmp, "docker", "extra"], 2),
                (["mask", tmp, tmp, tmp, "true"], 2),
                (["baseline"], 2),
                (["baseline", tmp, tmp], 2),
                (["baseline", f"{tmp}/missing/stage"], 1),
                (["scrub", tmp, tmp, tmp], 1),
                (["scrub", tmp, tmp, tmp, "docker"], 1),
            ):
                with self.subTest(argv=argv):
                    result = subprocess.run(
                        [sys.executable, "-B", str(MASKER), *argv],
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, code)


class TestSpecSecretsMaskingNegativeControls(unittest.TestCase):
    def test_each_form_leaks_without_its_decoding(self) -> None:
        cases = (
            (
                (
                    (
                        'return decode(view, ANSI, lambda _found: b"") or view',
                        "return view",
                    ),
                ),
                ["ansi_split"],
            ),
            (
                (("(PERCENT, from_percent), (FORM, from_form), ", ""),),
                [
                    "percent_encoded",
                    "form_encoded",
                    "double_percent",
                    "form_then_percent",
                    "json_then_percent",
                ],
            ),
            (
                (("(FORM, from_form), ", ""),),
                ["form_encoded", "form_then_percent"],
            ),
            (
                (("(FORM, from_form), (JS, from_js))", "(FORM, from_form))"),),
                [
                    "json",
                    "json_in_xml_attribute",
                    "json_then_percent",
                    "single_quoted_inspect",
                    "json_in_json",
                ],
            ),
            (
                (("yield strip(twice)", "continue"),),
                [
                    "json_in_xml_attribute",
                    "double_percent",
                    "form_then_percent",
                    "json_then_percent",
                    "json_in_json",
                ],
            ),
            (
                (
                    (
                        "for inner, inner_convert in LAYERS:",
                        "for inner, inner_convert in LAYERS[::3]:",
                    ),
                ),
                ["double_percent", "form_then_percent"],
            ),
            (
                (("if length < MASK_MIN:", "if length < self.longest:"),),
                ["preview_truncated_49"],
            ),
        )
        for replacements, leaking in cases:
            with self.subTest(replacement=replacements[0][0]):
                self.assertEqual(form_leaks(load_masker(*replacements)), leaking)

    def test_a_scan_without_overlap_is_caught(self) -> None:
        module = load_masker(
            ("self.reach = 16 * self.longest + 1024", "self.reach = 0")
        )
        self.assertTrue(chunk_leaks(module))

    def test_a_masker_that_masks_nothing_is_caught(self) -> None:
        problems = masked_run(("MASK_MIN = 8", "MASK_MIN = 10**6"))
        self.assertEqual(
            problems,
            [
                "stdout shows the value",
                "stderr shows the value",
                "junit shows the value",
                "older report shows the value",
                "reports node_modules shows the value",
                "stage volume shows the value",
                "forged temp shows the value",
                "stale temp shows the value",
            ],
        )

    def test_a_scrub_that_ignores_the_staged_digests_is_caught(self) -> None:
        problems = masked_run(("kept = digests(stage)", "kept = {}"))
        self.assertEqual(problems, ["a staged file was rewritten"])

    def test_a_scrub_that_skips_masked_named_files_is_caught(self) -> None:
        walked = "yield from (Path(top, name) for name in files"
        problems = masked_run((f"{walked})", f"{walked} if not name.startswith(TEMP))"))
        self.assertEqual(
            problems, ["forged temp shows the value", "stale temp shows the value"]
        )

    def test_a_final_scrub_that_needs_the_run_directory_is_caught(self) -> None:
        self.assertEqual(masked_run(FINAL_FROM_DIR), [])
        self.assertEqual(
            masked_run(FINAL_FROM_DIR, owner_gone=True),
            [
                "rc 1",
                "junit shows the value",
                "older report shows the value",
                "reports node_modules shows the value",
                "stage volume shows the value",
                "forged temp shows the value",
                "stale temp shows the value",
            ],
        )

    def test_a_container_left_running_after_a_sigkill_is_caught(self) -> None:
        removal = ('[cli, "rm", "--force", container]', '["true"]')
        self.assertEqual(
            stopped_run(signal.SIGKILL, removal),
            ["masker -9", "leaks True", "container alive True", "scrubbed leaks True"],
        )
        script = read_text(str(RERUN))
        self.assertEqual(script.count(EXIT_REMOVAL), 1)
        self.assertEqual(
            rerun(
                script.replace(EXIT_REMOVAL, "python3 -B"), kill=True, leftovers=False
            ),
            [
                "containers alive [True]",
                "junit leaks True",
                "env kept",
                "package kept True",
                "spec kept True",
            ],
        )

    def test_a_list_trusted_or_written_blindly_is_caught(self) -> None:
        trusting = (
            "return info.st_uid == os.geteuid() and not info.st_mode & WRITABLE",
            "return True",
        )
        through = (
            "Path(name).replace(baseline(stage))",
            "baseline(stage).write_bytes(Path(name).read_bytes())",
        )
        self.assertEqual(
            baseline_cases(trusting),
            [
                "a forged writable list kept a leftover in clear",
                "a base dir others can write was accepted",
            ],
        )
        self.assertEqual(owner_case(load_masker(trusting)), ([".env"], [".env"], False))
        self.assertEqual(
            baseline_cases(through),
            [
                "a hardlinked file was written through",
                "the list kept a mode others can write",
            ],
        )

    def test_a_rerun_that_trusts_leftovers_or_masks_its_spec_is_caught(self) -> None:
        script = read_text(str(RERUN))
        self.assertEqual(script.count(PRE_SCRUB), 1)
        unscrubbed = script.replace(PRE_SCRUB, "")
        late = unscrubbed.replace(
            "\nrun=(docker run", "\n" + PRE_SCRUB.lstrip("\t") + "run=(docker run"
        )
        self.assertNotEqual(late, unscrubbed)
        for broken, expected in (
            (unscrubbed, ["leftover leaks True", "env leaks True", "spec kept True"]),
            (late, ["leftover leaks False", "env leaks False", "spec kept False"]),
        ):
            with self.subTest(late=broken is late):
                events = rerun(broken, kill=False, leftovers=True)
                self.assertEqual(
                    [events[2], events[3], events[5]], expected, msg=str(events)
                )


if __name__ == "__main__":
    unittest.main()
