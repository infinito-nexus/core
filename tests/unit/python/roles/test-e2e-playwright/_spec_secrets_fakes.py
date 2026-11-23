from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import ROLE

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

FILES = ROLE / "files"
HELPER = FILES / "spec_secrets.py"
MASKER = FILES / "spec_secrets_mask.py"
MATCHER = FILES / "spec_secrets_match.py"
CONTAINER = FILES / "spec_secrets_container.py"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
PARENT_LINE = 'PARENT = Path("/tmp/infinito-playwright-spec-secrets")'
QUICK = ("REMOVAL_SECONDS = 30.0", "REMOVAL_SECONDS = 6.0")
CA_MODE = 0o644
SCRATCH = Path(tempfile.gettempdir()).resolve()
SCRATCH_OWNERS = sorted(
    {os.geteuid(), *(os.lstat(path).st_uid for path in (SCRATCH, *SCRATCH.parents))}
)
FOREIGN_UID = max(SCRATCH_OWNERS) + 1
PARENT_OWNERS = (
    "PARENT_UIDS = frozenset({0, TRUSTED_UID})\n",
    f"PARENT_UIDS = frozenset({{0, TRUSTED_UID, {', '.join(map(str, SCRATCH_OWNERS))}}})\n",
)
IMAGE = ":".join(
    re.search(pattern, read_text(str(SERVICES)), re.MULTILINE)[1]
    for pattern in (r"^\s*image:\s*(\S+)", r'^\s*version:\s*"([^"]+)"')
)
NAME = "infinito-playwright-c1"
TOUCH = "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()"
STAGE_ENV = "APP_BASE_URL=https://example.test\nPLAYWRIGHT_TEST_TIMEOUT=60000\n"
STAGE_KEYS = "APP_BASE_URL\n"
FAKE_SETUP = "docker.json"
EXEC_DOCKER = """\
import json, os, pathlib, sys
args = sys.argv[1:]
if args[:1] != ["run"]:
    sys.exit(f"Error: No such container: {args[-1]}")
setup = json.loads(pathlib.Path(sys.argv[0]).with_name("docker.json").read_text())
command, image = setup["command"], setup["image"]
os.execvp(command[0], [*command, *args[args.index(image) + 1 :]])
"""
VALUE = "Pa%\"s<w&r'd\\9X é \U0001f600 Sentinel-Value-9f3c abcdefghijklmnopqrstuvwxyz0123456789"
RAW = VALUE.encode()
WINDOW = 8
REDACTED = "<failure>***</failure>"
EXPECTED = {
    "stderr": "Error: ***",
    "junit": "<![CDATA[***]]>",
    "older report": "***",
}
FAKE_RUN = """\
import json, pathlib, sys
value, reports, gone, code = sys.argv[1:5]
if gone:
    pathlib.Path(gone).unlink()
print(f"Call log: - fill({json.dumps(value)}) {value} abc12")
print(f"Error: {value}", file=sys.stderr)
attribute = json.dumps(value)[1:-1]
for char, entity in (("&", "&amp;"), ('"', "&quot;"), ("<", "&lt;"), (">", "&gt;")):
    attribute = attribute.replace(char, entity)
junit = f'<failure message="fill(&quot;{attribute}&quot;)"><![CDATA[{value}]]></failure>'
pathlib.Path(reports, "playwright-junit.xml").write_text(junit)
pathlib.Path(reports, ".masked.1.junit").write_text(junit)
pathlib.Path(reports, "variant-0", "sync").mkdir(parents=True, exist_ok=True)
pathlib.Path(reports, "variant-0", "sync", "old.xml").write_text(value)
sys.exit(int(code))
"""
FAILED_SCRUB = """\
import sys
sys.path.insert(0, sys.argv[1])
import spec_secrets_mask as masker
masker.scrub = lambda reports, masks: 1
sys.exit(masker.main(["spec_secrets_mask.py", "mask", *sys.argv[2:]]))
"""


def install(bin_dir: Path, root: Path, *replacements: tuple[str, str]) -> Path:
    """Copy the four helpers and the image pin into a dir, their parent moved below a scratch dir.

    Args:
        bin_dir: where the helpers go.
        root: the scratch dir.
        *replacements: pairs of text the masker, matcher and container
            check together hold exactly once and its replacement, for a
            negative control; the removal bound is ``QUICK`` already, and
            ``PARENT_OWNERS`` adds the owners of the scratch dirs above,
            such as uid 65534 for ``/`` in a bubblewrap sandbox.

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
    (bin_dir / SERVICES.name).write_text(read_text(str(SERVICES)), encoding="utf-8")
    sources = {path.name: read_text(str(path)) for path in (MASKER, MATCHER, CONTAINER)}
    container = sources[CONTAINER.name]
    if container.count(PARENT_OWNERS[0]) != 1:
        raise AssertionError(
            f"the container check no longer holds {PARENT_OWNERS[0]!r}"
        )
    sources[CONTAINER.name] = container.replace(*QUICK).replace(*PARENT_OWNERS)
    for old, new in replacements:
        holders = [name for name, text in sources.items() if text.count(old) == 1]
        if len(holders) != 1 or sum(t.count(old) for t in sources.values()) != 1:
            raise AssertionError(f"the masker no longer holds {old!r} once")
        sources[holders[0]] = sources[holders[0]].replace(old, new)
    for name, text in sources.items():
        (bin_dir / name).write_text(text, encoding="utf-8")
    return helper


def load_from(bin_dir: Path, root: Path, *replacements: tuple[str, str]):
    """Install the helpers into a dir the caller keeps, then load the masker from it.

    Args:
        bin_dir: where the helpers go.
        root: the scratch dir.
        *replacements: pairs for ``install``.

    Returns:
        The module, with fresh copies of the helper, the matcher and the
        container check, whose image pin stays readable while ``bin_dir`` is.
    """
    install(bin_dir, root, *replacements)
    sys.path.insert(0, str(bin_dir))
    for name in ("spec_secrets", "spec_secrets_match", "spec_secrets_container"):
        sys.modules.pop(name, None)
    try:
        spec = importlib.util.spec_from_file_location(
            "spec_secrets_mask", bin_dir / MASKER.name
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = [entry for entry in sys.path if entry != str(bin_dir)]
    return module


def load_masker(*replacements: tuple[str, str]):
    """Load the masker in this process, its pieces replaced for a control.

    Args:
        *replacements: pairs for ``install``.

    Returns:
        The module, with fresh copies of the helper and the matcher.
    """
    with tempfile.TemporaryDirectory() as tmp:
        return load_from(Path(tmp) / "bin", Path(tmp), *replacements)


def container_argv(root: Path, directory: Path) -> list[str]:
    """Stage a 0755 dir with an env file and its declared keys, then build the container command a run with spec secrets starts.

    Args:
        root: the scratch dir, which gets ``stage``.
        directory: the run directory.

    Returns:
        ``docker run`` named ``NAME`` with every option ``check_container``
        requires, the stage dir and its volume read-only, the reports into
        the run directory and ``IMAGE`` last.
    """
    stage = root / "stage"
    (stage / "volume").mkdir(parents=True, exist_ok=True)
    stage.chmod(0o755)
    (stage / ".env").write_text(STAGE_ENV, encoding="utf-8")
    (stage / ".env.keys").write_text(STAGE_KEYS, encoding="utf-8")
    mount = f"type=bind,src={directory},dst=/run/spec-secrets,readonly"
    return [
        "docker",
        "run",
        "--rm",
        "--log-driver=none",
        "--name",
        NAME,
        f"--cidfile={directory}/.cid",
        "--mount",
        mount,
        "--env-file",
        str(stage / ".env"),
        *("-e", "INFINITO_PLAYWRIGHT_NO_CAPTURE=true"),
        *("-e", "NO_COLOR=1", "-e", "FORCE_COLOR=0"),
        *("-v", f"{stage}:/e2e:ro", "-v", f"{stage}/volume:/volume:ro"),
        *("-v", f"{directory}/reports:/reports"),
        *("-w", "/e2e", IMAGE),
    ]


def exec_tool(
    root: Path, directory: Path, command: list[str]
) -> tuple[list[str], dict[str, str]]:
    """Install a fake ``docker`` whose ``run`` execs a command with the words after the image.

    Args:
        root: the scratch dir holding ``bin``.
        directory: the run directory.
        command: what ``run`` execs; the fake reads it and ``IMAGE`` from
            ``FAKE_SETUP`` next to it, since the masker hands its tool only
            ``container_env``.

    Returns:
        ``container_argv`` and an environment with the fake first on PATH.
    """
    docker = root / "bin" / "docker"
    docker.write_text(f"#!{sys.executable}\n{EXEC_DOCKER}", encoding="utf-8")
    docker.chmod(0o755)
    setup = {"command": command, "image": IMAGE}
    (root / "bin" / FAKE_SETUP).write_text(json.dumps(setup), encoding="utf-8")
    env = caller_env()
    env["PATH"] = f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}"
    return container_argv(root, directory), env


def caller_env() -> dict[str, str]:
    """Copy this process's environment for a masker, without the caller's Docker config.

    Returns:
        Every variable but ``DOCKER_CONFIG``, which ``check_docker_config``
        refuses unless root owns it; a test of that policy sets its own.
    """
    return {key: value for key, value in os.environ.items() if key != "DOCKER_CONFIG"}


def without_docker_config() -> AbstractContextManager:
    """Hide the caller's ``DOCKER_CONFIG`` from a container check in this process.

    Returns:
        A context manager that holds ``caller_env`` as the environment and
        restores the environment on exit.
    """
    return mock.patch.dict(os.environ, caller_env(), clear=True)


def make_run(helper: Path, rendered: str) -> Path:
    """Create a run directory with the helper and split values into it.

    Args:
        helper: the installed ``spec_secrets.py``.
        rendered: the ``KEY=VALUE`` lines.

    Returns:
        The run directory.
    """
    created = subprocess.run(
        [sys.executable, str(helper), "create"],
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


def scratch_text(path: Path) -> str:
    """Read a file a test wrote into its own scratch dir, fresh each time.

    Args:
        path: the file, which the masker may have rewritten since.

    Returns:
        Its text.
    """
    return path.read_text(encoding="utf-8")  # nocheck: cache-read


def leaks(text: str, secret: str) -> bool:
    """Tell whether any piece of ``secret`` of ``WINDOW`` bytes or more shows.

    Args:
        text: masked output.
        secret: the text to look for pieces of.

    Returns:
        Whether such a piece shows, both cut as UTF-8.
    """
    raw, shown = secret.encode(), text.encode()
    return any(raw[at : at + WINDOW] in shown for at in range(len(raw) - WINDOW + 1))


def state_of(report: Path) -> str:
    """Tell what a published report shows.

    Args:
        report: the report in the reports dir.

    Returns:
        ``none`` when it was not published, else ``leaks``, ``masked`` for
        exactly ``REDACTED`` or ``other``, such as an empty file.
    """
    if not report.exists():
        return "none"
    text = scratch_text(report)
    if leaks(text, VALUE):
        return "leaks"
    return "masked" if text == REDACTED else "other"


def masked_run(*replacements, owner_gone: bool = False, code: int) -> list[str]:
    """Run a fake container through ``mask`` and look for the value.

    Args:
        *replacements: changes to the masker or matcher, for a negative control.
        owner_gone: whether the container removes the value's file first.
        code: the exit code of the fake container.

    Returns:
        One message per place the value shows in the output or the published
        reports, per stream or report that lacks its ``EXPECTED`` masked
        text, a link that was followed or published, staged reports left
        behind or the exit code not being the container's.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        reports, staged = root / "reports", directory / "reports"
        staged.mkdir(mode=0o700)
        outside = root / "outside.txt"
        outside.write_text(VALUE)
        (staged / "link.txt").symlink_to(outside)
        fake = [sys.executable, "-c", FAKE_RUN, VALUE, str(staged)]
        fake += [str(directory / "LONG_KEY") if owner_gone else "", str(code)]
        container, env = exec_tool(root, directory, fake)
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        result = subprocess.run(
            [*masker, str(directory), str(reports), "--", *container, "--"],
            capture_output=True,
            check=False,
            env=env,
        )
        problems = [] if result.returncode == code else [f"rc {result.returncode}"]
        shown = {
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
            "junit": scratch_text(reports / "playwright-junit.xml"),
            "older report": scratch_text(reports / "variant-0" / "sync" / "old.xml"),
        }
        problems += [
            f"{name} shows the value" for name, t in shown.items() if leaks(t, VALUE)
        ]
        problems += [
            f"{name} lacks its expected text"
            for name, text in EXPECTED.items()
            if text not in shown[name]
        ]
        if os.path.lexists(reports / ".masked.1.junit"):
            problems.append("a forged temp file was published")
        if "abc12" not in shown["stdout"]:
            problems.append("unrelated short text was masked")
        if scratch_text(outside) != VALUE or os.path.lexists(reports / "link.txt"):
            problems.append("a link was followed")
        if os.path.lexists(staged):
            problems.append("the staged reports were left behind")
        return problems


def failed_scrub_run(
    *replacements: tuple[str, str],
) -> tuple[int, list[str], bool, int]:
    """Run a passing command that writes a report through ``mask``, its scrub failing.

    Args:
        *replacements: changes to the masker or matcher, for a negative control.

    Returns:
        The masker's exit code, the files published to the reports dir,
        whether the staged reports were left behind and the exit code of the
        ``scrub`` the run's ``always`` section runs after it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        reports, staged = root / "reports", directory / "reports"
        reports.mkdir()
        patched = [sys.executable, "-c", FAILED_SCRUB, str(root / "bin")]
        write = [
            "sh",
            "-c",
            'echo "<failure/>" > "$0/playwright-junit.xml"',
            str(staged),
        ]
        container, env = exec_tool(root, directory, write)
        result = subprocess.run(
            [*patched, str(directory), str(reports), "--", *container, "--"],
            capture_output=True,
            check=False,
            env=env,
        )
        published = sorted(path.name for path in reports.iterdir())
        left = os.path.lexists(staged)
        masker = [sys.executable, str(root / "bin" / MASKER.name), "scrub"]
        scrub = subprocess.run(
            [*masker, str(directory), str(reports), "true"],
            capture_output=True,
            check=False,
        )
        return result.returncode, published, left, scrub.returncode
