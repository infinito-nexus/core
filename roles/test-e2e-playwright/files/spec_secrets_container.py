from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

from spec_secrets import SpecSecretsError

CID = ".cid"
MISSING = re.compile(rb"no such (?:container|object)", re.IGNORECASE)
REMOVAL_SECONDS = 30.0
FIRST_PAUSE = 0.25
LAST_PAUSE = 4.0
SERVICES = "services.yml"
SECRETS = "/run/spec-secrets"
CLI = "docker"
SHARED = "_shared"
CA_CERT = "/tmp/infinito/ca/root-ca.crt"  # noqa: S108 - a path inside the container, the role's CA_TRUST.inject_cert_container
CA_BUNDLES = (
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
CA_ORDER = ("CA_TRUST_CERT", "CA_TRUST_NAME", *CA_BUNDLES)
CA_ENV = frozenset(CA_ORDER)
CA_WORDS = ".ca-trust"
CA_SHAPE = (
    ("-v", re.compile(f"/[^:]+:{re.escape(CA_CERT)}:ro")),
    *(("-e", re.compile(f"{key}=.*")) for key in CA_ORDER),
)
OPEN_WORDS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
TRUSTED_UID = 0
PARENT_UIDS = frozenset({0, TRUSTED_UID})
CONFIG_KEYS = frozenset({"auths", "credsStore", "credHelpers"})
CHILD_ENV = (
    "PATH",
    "HOME",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CONFIG",
    "DOCKER_DEFAULT_PLATFORM",
    "DOCKER_API_VERSION",
)
NUMBER = re.compile(r"[0-9]+")
DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
BOOL = re.compile(r"[Tt]rue|[Ff]alse")
LISTED = re.compile(r"[^\n]*")
# nocheck: logging-driver  the run prints spec secrets before the host masker scrubs its attached output, so journald would keep them unmasked
NO_LOG = "--log-driver=none"
FLAGS = frozenset({"--rm", "--ipc=host", "--shm-size=1g", NO_LOG})
OPTIONS = {
    "--add-host": re.compile(r"[A-Za-z0-9.-]+:host-gateway"),
    "--name": re.compile(r"infinito-playwright-[A-Za-z0-9_.-]+"),
    "--oom-score-adj": re.compile(r"-?[0-9]+"),
    "--network": re.compile(r"host|none"),
    "--user": re.compile(r"[0-9]+:[0-9]+"),
    "--ulimit": re.compile(r"core=0"),
    "-w": re.compile(r"/e2e"),
    "-e": re.compile(r"[A-Z][A-Z0-9_]*=.*"),
    "-v": re.compile(r"/[^:]+:/[^:]+(?::ro)?"),
    "--env-file": re.compile(r"/.+/\.env"),
    "--cidfile": re.compile(r"/.+"),
    "--mount": re.compile(r"type=bind,src=/[^,]+,dst=/run/spec-secrets,readonly"),
}
REPEATABLE = frozenset({"-e", "-v", "--add-host"})
REQUIRED = frozenset({"--rm", NO_LOG, "-w", "--cidfile", "--mount", "--env-file"})
NO_CAPTURE = "INFINITO_PLAYWRIGHT_NO_CAPTURE"  # nocheck: container env
ENV = {
    "INFINITO_PLAYWRIGHT_KEEP": re.compile(r"(?:[Tt]rue|[Ff]alse)?"),
    "INFINITO_PLAYWRIGHT_GLOBAL_TIMEOUT_MS": NUMBER,  # nocheck: container env
    NO_CAPTURE: re.compile(r"true"),
    "PLAYWRIGHT_PROXY": re.compile(
        r"(?:socks5://(?:127\.0\.0\.1|host\.docker\.internal):[0-9]+)?"
    ),
    "PLAYWRIGHT_WORKERS": re.compile(r"[0-9]+%?"),
    "PLAYWRIGHT_FULLY_PARALLEL": BOOL,
    "PLAYWRIGHT_TIMEOUT_FACTOR": DECIMAL,
    "PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIER": DECIMAL,
    "PLAYWRIGHT_GALLERY_VIEWS": re.compile(r"[A-Za-z0-9,_-]*"),
    "PLAYWRIGHT_GALLERY_BEFORE": re.compile(r"[A-Za-z0-9,_-]*"),
    "NO_COLOR": re.compile(r"1"),
    "FORCE_COLOR": re.compile(r"0"),
    "HOME": re.compile(r"/tmp"),  # noqa: S108 - the HOME a non-root run gets inside the container
    **dict.fromkeys(("CA_TRUST_CERT", *CA_BUNDLES), re.compile(re.escape(CA_CERT))),
    "CA_TRUST_NAME": re.compile(r"[a-z0-9][a-z0-9.-]*"),
}
REQUIRED_ENV = frozenset({NO_CAPTURE, "NO_COLOR", "FORCE_COLOR"})
TIMEOUTS = (
    "PLAYWRIGHT_TEST_TIMEOUT",
    "PLAYWRIGHT_EXPECT_TIMEOUT",
    "PLAYWRIGHT_NAVIGATION_TIMEOUT",
    "PLAYWRIGHT_ACTION_TIMEOUT",
)
ENV_FILE = {
    **dict.fromkeys(TIMEOUTS, NUMBER),
    "PLAYWRIGHT_NETWORK_LEAK": BOOL,
    "PLAYWRIGHT_NETWORK_SUFFIXES": LISTED,
    "PLAYWRIGHT_NETWORK_ALLOWED_HOSTS": LISTED,
    "PLAYWRIGHT_PROXY_BYPASS": LISTED,
}
DECLARED_RUNTIME = {
    "PLAYWRIGHT_MAX_WORKERS": NUMBER,
    "NODE_TLS_REJECT_UNAUTHORIZED": re.compile(r'"?[01]"?'),
}
KEYS = ".env.keys"
RUNTIME = re.compile(
    r"(?:NODE_|PW|PLAYWRIGHT_|DEBUG|LD_|PYTHON|NPM_|npm_|OPENSSL_|SSL_|XDG_|CA_TRUST_)"
    r"|(?:BASH_ENV|ENV|PATH|HOME|SHELL|TMPDIR|CI|GCONV_PATH|LOCPATH|VERBOSE"
    r"|VK_ICD_FILENAMES|LIBGL_DRIVERS_PATH|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE"
    r"|(?i:[A-Z_]*PROXY))$"
)


def container_env() -> dict[str, str]:
    """Pick the environment the container tool of a run with spec secrets gets.

    Returns:
        The variables of ``CHILD_ENV`` this process has, so no proxy nor the
        play's ``CA_*`` reach the tool or, through a bare ``-e``, the container.
    """
    return {key: os.environ[key] for key in CHILD_ENV if key in os.environ}


def remove_container(directory: Path, cli: str, name: str) -> bool:
    """Force-remove the container the run directory's ``CID`` names, then prove it gone.

    Args:
        directory: the run directory.
        cli: the container tool, such as ``container`` or ``docker``.
        name: the name the run gave its container, removed the same way while
            no ``CID`` names one; empty for a run that names none.

    Returns:
        Whether none is named or, after ``rm --force``, ``inspect`` finds
        none; both repeat, pausing ``FIRST_PAUSE`` doubling to ``LAST_PAUSE``,
        until ``REMOVAL_SECONDS`` pass, then False, as when the tool fails.
    """
    try:
        container = (directory / CID).read_text(encoding="utf-8").strip() or name
    except FileNotFoundError:
        container = name
    except OSError:
        return False
    if not container:
        return True
    deadline = time.monotonic() + REMOVAL_SECONDS
    calls = (
        [cli, "rm", "--force", container],
        [cli, "inspect", "--type", "container", container],
    )
    pause = FIRST_PAUSE
    while True:
        for call in calls:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            try:
                found = subprocess.run(
                    call, capture_output=True, check=False, timeout=left
                )
            except (subprocess.TimeoutExpired, OSError):
                return False
        if found.returncode and MISSING.search(found.stderr):
            return True
        time.sleep(max(min(pause, deadline - time.monotonic()), 0))
        pause = min(2 * pause, LAST_PAUSE)


def cid_named(directory: Path) -> str:
    """Read the container id the run directory's ``CID`` names yet.

    Args:
        directory: the run directory.

    Returns:
        The id, empty until the tool wrote one; until then a container may
        still start that no removal can prove gone.
    """
    try:
        return (directory / CID).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def pinned_image() -> str:
    """Read the Playwright image the role pins in its ``meta/services.yml``.

    Returns:
        ``image:version`` of the first ``image`` and ``version`` lines of the
        ``SERVICES`` next to this file or else in the role's ``meta`` dir.

    Raises:
        SpecSecretsError: neither holds both.
    """
    here = Path(__file__).parent
    for path in (here / SERVICES, here.parent / "meta" / SERVICES):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            image = re.search(r"^\s*image:\s*(\S+)", text, re.MULTILINE)
            version = re.search(r'^\s*version:\s*"([^"]+)"', text, re.MULTILINE)
            if image and version:
                return f"{image[1]}:{version[1]}"
    raise SpecSecretsError(f"no {SERVICES} next to the masker pins the image")


def options(words: list[str]) -> dict[str, list[str]]:
    """Group the options of a container command by name.

    Args:
        words: the words between ``run`` and the image.

    Returns:
        Each value per option, an empty one per flag of ``FLAGS``.

    Raises:
        SpecSecretsError: a word is no option of ``FLAGS`` or ``OPTIONS``, a value is
            outside its pattern, or an option not ``REPEATABLE`` repeats.
    """
    found: dict[str, list[str]] = {}
    remaining = iter(words)
    for word in remaining:
        if word in FLAGS:
            found.setdefault(word, []).append("")
            continue
        name, equals, value = word.partition("=")
        if name not in OPTIONS or (equals and not name.startswith("--")):
            raise SpecSecretsError(f"a run with spec secrets takes no {name}")
        value = value if equals else next(remaining, "")
        if not OPTIONS[name].fullmatch(value):
            raise SpecSecretsError(f"a run with spec secrets refuses that {name}")
        found.setdefault(name, []).append(value)
    for name, values in found.items():
        if len(values) > 1 and name not in REPEATABLE:
            raise SpecSecretsError(f"a run with spec secrets takes {name} once")
    return found


def check_env(assignments: list[str]) -> None:
    """Refuse ``-e`` variables outside ``ENV``.

    Args:
        assignments: the ``KEY=VALUE`` of each ``-e``.

    Raises:
        SpecSecretsError: a key is not in ``ENV``, repeats or has a value
            outside its pattern, or one of ``REQUIRED_ENV`` is missing.
    """
    keys = [assignment.partition("=")[0] for assignment in assignments]
    for key, assignment in zip(keys, assignments, strict=True):
        if key not in ENV or not ENV[key].fullmatch(assignment.partition("=")[2]):
            raise SpecSecretsError(f"a run with spec secrets refuses -e {key}")
    if len(set(keys)) != len(keys) or not set(keys) >= REQUIRED_ENV:
        raise SpecSecretsError(
            f"a run with spec secrets sets each of {sorted(REQUIRED_ENV)} once"
        )


def declared_keys(stage: Path) -> frozenset[str]:
    """Read the keys the application role's env template declares.

    Args:
        stage: the stage dir, whose ``KEYS`` the deploy lists from the template.

    Returns:
        The key names.

    Raises:
        SpecSecretsError: the stage dir holds no ``KEYS``, as after an old deploy.
    """
    try:
        descriptor = os.open(stage / KEYS, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as error:
        raise SpecSecretsError(f"{stage} lacks {KEYS}: redeploy the role") from error
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        return frozenset(line.strip() for line in handle if line.strip())


def check_env_file(path: Path) -> None:
    """Refuse an env file that sets a variable a run with spec secrets does not take.

    Args:
        path: the stage dir's ``.env``, opened without following a link.

    Raises:
        SpecSecretsError: a line copies a host variable without ``=``, sets a
            key neither in ``ENV_FILE`` nor ``declared_keys``, a value outside
            the pattern ``ENV_FILE`` or ``DECLARED_RUNTIME`` gives its key, or
            a declared key ``RUNTIME`` matches, such as ``NODE_OPTIONS``. The
            message names the line and the key, never a value.
    """
    declared = declared_keys(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for number, line in enumerate(lines, start=1):
        key, equals, value = line.partition("=")
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        if not equals:
            raise SpecSecretsError(f"line {number} of {path} copies host {key}")
        pattern = ENV_FILE.get(key) or (
            DECLARED_RUNTIME.get(key) if key in declared else None
        )
        if pattern is not None and not pattern.fullmatch(value):
            raise SpecSecretsError(f"line {number} of {path} gives {key} a bad value")
        if pattern is None and (key not in declared or RUNTIME.match(key)):
            raise SpecSecretsError(f"line {number} of {path} sets {key}")


def check_stage(stage: Path) -> None:
    """Refuse a stage dir that is a link, another user's or writable by others.

    Args:
        stage: the directory the env file sits in.

    Raises:
        SpecSecretsError: it is no directory of root or this user with mode
            0755 or tighter.
    """
    info = os.lstat(stage)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid not in (0, os.geteuid())
        or info.st_mode & 0o022
    ):
        raise SpecSecretsError(f"the stage dir {stage} is not this user's 0755 dir")


def mount_key(value: str) -> str:
    """Spell a ``-v`` value with its source path normalised.

    Args:
        value: ``source:target`` with an optional ``:ro``.

    Returns:
        The value with ``source`` as ``Path`` writes it.
    """
    source, colon, rest = value.partition(":")
    return f"{Path(source)}{colon}{rest}"


def check_trusted(source: Path, *, directory: bool) -> None:
    """Refuse a path the container or its tool would trust that another user may have planted.

    Args:
        source: the host path, such as the source of the CA trust's mount.
        directory: whether it must be a directory rather than a file of one link.

    Raises:
        SpecSecretsError: it is missing, reached through a link, of another
            kind, a hard linked file, not ``TRUSTED_UID``'s, group or other
            writable, or below a dir another user may rename it out of: one
            of no owner of ``PARENT_UIDS``, or writable without sticky bit.
    """
    try:
        info, real = os.lstat(source), source.resolve(strict=True)
        parents = [os.lstat(parent) for parent in source.parents]
    except OSError as error:
        raise SpecSecretsError(f"a run with spec secrets lacks {source}") from error
    if (
        real != source
        or not (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode)
        or (info.st_nlink != 1 and not directory)
        or info.st_uid != TRUSTED_UID
        or info.st_mode & 0o022
        or any(
            above.st_uid not in PARENT_UIDS
            or (above.st_mode & 0o022 and not above.st_mode & stat.S_ISVTX)
            for above in parents
        )
    ):
        raise SpecSecretsError(f"a run with spec secrets does not trust {source}")


def check_docker_config() -> None:
    """Refuse a ``DOCKER_CONFIG`` another user may have planted or that sets proxies.

    Raises:
        SpecSecretsError: ``check_trusted`` refuses it or its ``config.json``,
            or that is no JSON object or has a key outside ``CONFIG_KEYS``.
    """
    if "DOCKER_CONFIG" not in os.environ:
        return
    directory = Path(os.environ["DOCKER_CONFIG"])
    check_trusted(directory, directory=True)
    config = directory / "config.json"
    if not os.path.lexists(config):
        return
    check_trusted(config, directory=False)
    try:
        settings = json.loads(config.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SpecSecretsError(f"{config} holds no JSON") from error
    if not isinstance(settings, dict) or not CONFIG_KEYS.issuperset(settings):
        raise SpecSecretsError(f"a run with spec secrets refuses {config}")


def check_ca(argv: list[str], found: dict[str, list[str]], stage: Path) -> list[str]:
    """Refuse CA trust other than the role's own, which comes whole or not at all.

    Args:
        argv: the command through the image.
        found: its options.
        stage: the stage dir, whose ``CA_WORDS`` holds one a line the words of
            ``_playwright_ca_argv`` the deploy gave the run, none if it lacks it.

    Returns:
        The ``-v`` values but the one of the CA trust, each source normalised.

    Raises:
        SpecSecretsError: of the ``CA_ENV`` variables and one read-only mount
            onto ``CA_CERT``, only some are given; ``check_trusted`` refuses
            the mount's source; or ``CA_WORDS`` is no regular UTF-8 file,
            holds other words than ``CA_SHAPE`` in turn, ones the command
            lacks in one piece, or none while the command has CA trust.
    """
    trusted: list[Path] = []
    rest = []
    for value in map(mount_key, found.get("-v", [])):
        source, target, *mode = value.split(":")
        if target != CA_CERT:
            rest.append(value)
        elif mode != ["ro"] or trusted:
            raise SpecSecretsError(f"a run with spec secrets mounts {target} once, ro")
        else:
            trusted.append(Path(source))
    keys = {assignment.partition("=")[0] for assignment in found.get("-e", [])}
    whole = bool(trusted) and keys >= CA_ENV
    if not whole and (trusted or keys & CA_ENV):
        raise SpecSecretsError("a run with spec secrets takes the CA trust whole")
    for source in trusted:
        check_trusted(source, directory=False)
    try:
        descriptor = os.open(stage / CA_WORDS, OPEN_WORDS)
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            regular = stat.S_ISREG(os.fstat(descriptor).st_mode)
            text = handle.read() if regular else ""
    except FileNotFoundError:
        regular, text = True, ""
    except (OSError, ValueError) as error:
        raise SpecSecretsError(f"cannot read the stage {CA_WORDS}") from error
    words = [line for line in text.splitlines() if line]
    shaped = len(words) == 2 * len(CA_SHAPE) and all(
        words[2 * at] == flag and pattern.fullmatch(words[2 * at + 1])
        for at, (flag, pattern) in enumerate(CA_SHAPE)
    )
    held = any(argv[at : at + len(words)] == words for at in range(len(argv)))
    if not regular or ((words or trusted) and not (shaped and held)):
        raise SpecSecretsError(f"a run with spec secrets takes only {CA_WORDS}")
    return rest


def check_container(container: list[str], run: Path) -> None:
    """Refuse a container command other than the one a run with spec secrets starts.

    Args:
        container: the command through the image.
        run: the run directory.

    Raises:
        SpecSecretsError: the tool is not ``docker run``, the image not
            ``pinned_image``, a ``check_*`` or ``options`` refuses, one of
            ``REQUIRED`` is missing, ``--cidfile`` and ``--mount`` name another
            directory, or the other mounts are not the stage dir, its volume,
            the reports and at most the ``SHARED`` node_modules and personas.
    """
    if len(container) < 3 or container[:2] != [CLI, "run"]:
        raise SpecSecretsError(f"a run with spec secrets starts with {CLI} run")
    if container[-1] != pinned_image():
        raise SpecSecretsError(f"a run with spec secrets runs {pinned_image()} only")
    check_docker_config()
    found = options(container[2:-1])
    if not set(found) >= REQUIRED:
        raise SpecSecretsError(f"spec secrets runs take each of {sorted(REQUIRED)}")
    check_env(found.get("-e", []))
    env_file = Path(found["--env-file"][0])
    stage, shared = env_file.parent, Path(__file__).parent.with_name(SHARED)
    check_stage(stage)
    check_env_file(env_file)
    mount = f"type=bind,src={run},dst={SECRETS},readonly"
    if found["--cidfile"] != [str(run / CID)] or found["--mount"] != [mount]:
        raise SpecSecretsError(f"a run with spec secrets mounts and names {run} only")
    required = {f"{stage}:/e2e:ro", f"{stage / 'volume'}:/volume:ro"}
    required.add(f"{run / 'reports'}:/reports")
    optional = {
        f"{shared / 'node_modules'}:/e2e/node_modules:ro",
        f"{shared / 'personas'}:/e2e/tests/personas:ro",
    }
    mounts = check_ca(container, found, stage)
    if len(set(mounts)) != len(mounts) or not required <= set(mounts) <= (
        required | optional
    ):
        raise SpecSecretsError("a run with spec secrets takes no other mounts")
