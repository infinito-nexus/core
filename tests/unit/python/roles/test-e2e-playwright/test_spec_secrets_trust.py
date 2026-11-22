from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT, role_task
from ._spec_secrets_fakes import (
    CA_MODE,
    IMAGE,
    MASKER,
    VALUE,
    container_argv,
    exec_tool,
    install,
    load_from,
    make_run,
    scratch_text,
)
from ._spec_secrets_wiring import (
    ARGV_VARS,
    PATH_FACT,
    holds,
    render,
    role_tasks,
    run_argv,
)
from .test_spec_secrets_container import env_refused

TLS_VARS = PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"
CA_TRUST = load_yaml_any(str(TLS_VARS), default_if_missing={})["CA_TRUST"]
CA_CERT = CA_TRUST["inject_cert_container"]
CA_WRAPPER = CA_TRUST["inject_wrapper_container"]
BUNDLES = (
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
TRUST_NAME = "example.test"
PLAY_ENV = {
    "CA_CONTAINER_ENABLED": "1",
    "CA_TRUST_CERT_HOST": "/etc/example.test/ca/root-ca.crt",
    "CA_TRUST_WRAPPER_HOST": "/usr/bin/ca-trust-wrapper",
    "CA_TRUST_NAME": TRUST_NAME,
    "HTTPS_PROXY": "http://203.0.113.9:3128",
    "http_proxy": "http://203.0.113.9:3128",
    "NODE_OPTIONS": "--require=/e2e/x.js",
}
DOCKER_ENV = {
    "DOCKER_CONFIG": "/etc/example.test/docker",
    "DOCKER_DEFAULT_PLATFORM": "linux/arm64",
    "DOCKER_API_VERSION": "1.43",
}
WRITE_ENV = (
    "import json, os, pathlib, sys; "
    "pathlib.Path(sys.argv[1]).write_text(json.dumps(sorted(os.environ)))"
)
OWN_UID = ("TRUSTED_UID = 0\n", f"TRUSTED_UID = {os.geteuid()}\n")
OTHER_UID = ("TRUSTED_UID = 0\n", f"TRUSTED_UID = {os.geteuid() + 1}\n")
INHERITING = ("stderr=piped, env=container_env())", "stderr=piped, env=None)")
NARROW = (
    '    "DOCKER_CONFIG",\n    "DOCKER_DEFAULT_PLATFORM",\n    "DOCKER_API_VERSION",\n',
    "",
)
PARTIAL = ("    if not whole and (trusted or keys & CA_ENV):\n", "    if False:\n")
WORDS_TAKEN = (
    "    if not regular or ((words or trusted) and not (shaped and held)):\n",
    "    if not regular:\n",
)
UNTRUSTING = (
    "    for source in trusted:\n        check_trusted(source, directory=False)\n",
    "",
)
LAX = (
    (
        "        or (info.st_nlink != 1 and not directory)\n"
        "        or info.st_uid != TRUSTED_UID\n"
    ),
    "",
)
WRAPPED = ('CLI = "docker"', 'CLI = "container"')
OLD_RUNTIME = (
    (
        'r"(?:NODE_|PW|PLAYWRIGHT_|DEBUG|LD_|PYTHON|NPM_|npm_|OPENSSL_|SSL_|XDG_|CA_TRUST_)"\n'
        '    r"|(?:BASH_ENV|ENV|PATH|HOME|SHELL|TMPDIR|CI|GCONV_PATH|LOCPATH|VERBOSE"\n'
        '    r"|VK_ICD_FILENAMES|LIBGL_DRIVERS_PATH|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE"\n'
        '    r"|(?i:[A-Z_]*PROXY))$"'
    ),
    (
        'r"(?:NODE_|PW_|PLAYWRIGHT_|DEBUG|LD_|PYTHON|NPM_|npm_)"\n'
        '    r"|(?:BASH_ENV|ENV|PATH|HOME|SHELL)$"'
    ),
)
RUNTIME_KEYS = (
    "PWDEBUG",
    "PWPAUSE",
    "PWTEST_SKIP_TEST_OUTPUT",
    "TMPDIR",
    "OPENSSL_CONF",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "CI",
    "GCONV_PATH",
    "LOCPATH",
    "VK_ICD_FILENAMES",
    "LIBGL_DRIVERS_PATH",
    "CA_TRUST_BUNDLE",
    "CA_TRUST_CERT_EXTRA",
    "VERBOSE",
)
INSPECT = [
    "container",
    "image",
    "inspect",
    "--format",
    "{{json .Config.Entrypoint}}",
    IMAGE,
]
ENTRYPOINT_FACT = "_playwright_image_entrypoint"
REFUSALS = {
    "pull": "🛑 Refuse a run with spec secrets whose image could not be pulled",
    "entrypoint": "🛑 Refuse a run with spec secrets whose image has an ENTRYPOINT",
}
ENTRYPOINTS = {
    "none": ({"rc": 0, "stdout": "null\n"}, []),
    "empty": ({"rc": 0, "stdout": "[]"}, []),
    "a shell": ({"rc": 0, "stdout": '["/bin/sh"]\n'}, ["entrypoint"]),
    "no image": ({"rc": 1, "stdout": ""}, ["pull"]),
}
CA_FACTS = "📌 Define the paths every role's run shares"


def ca_files(root: Path, mode: int, linked: bool = False) -> Path:
    """Write a CA certificate of this user.

    Args:
        root: the scratch dir.
        mode: the certificate's mode.
        linked: whether the certificate is reached through a link.

    Returns:
        The certificate's path as the mount names it, below the resolved
        scratch dir, so only ``linked`` adds a link.
    """
    root = root.resolve()
    cert = root / "ca.crt"
    cert.write_text("cert\n", encoding="utf-8")
    cert.chmod(mode)
    if linked:
        (root / "ca-link.crt").symlink_to(cert)
        cert = root / "ca-link.crt"
    return cert


def ca_block(cert: Path) -> list[str]:
    """Spell the role's CA trust for a run with spec secrets.

    Args:
        cert: the host certificate.

    Returns:
        The read-only mount, the trust variables and each bundle variable,
        the container wrapper's words for an image without ENTRYPOINT.
    """
    return [
        *("-v", f"{cert}:{CA_CERT}:ro"),
        *("-e", f"CA_TRUST_CERT={CA_CERT}", "-e", f"CA_TRUST_NAME={TRUST_NAME}"),
        *(word for key in BUNDLES for word in ("-e", f"{key}={CA_CERT}")),
    ]


def ca_variants(cert: Path) -> dict[str, list[str]]:
    """Name each CA trust a run with spec secrets must refuse.

    Args:
        cert: the host certificate.

    Returns:
        Per name, the words that replace the role's CA trust.
    """
    whole = ca_block(cert)
    return {
        "no bundle": whole[:-2],
        "no trust name": whole[:4] + whole[6:],
        "no certificate mount": whole[2:],
        "writable certificate mount": [whole[0], f"{cert}:{CA_CERT}", *whole[2:]],
        "foreign target": [whole[0], f"{cert}:/etc/ssl/certs/x.pem:ro", *whole[2:]],
        "foreign certificate path": [*whole[:3], "CA_TRUST_CERT=/x.pem", *whole[4:]],
        "foreign bundle path": [*whole[:9], "SSL_CERT_FILE=/x.pem", *whole[10:]],
        "certificate twice": [*whole[:2], *whole],
        "trust script": [*whole, "--entrypoint", CA_WRAPPER],
    }


def refused(module, argv: list[str], run: Path) -> bool:
    """Hold a container command against the check.

    Args:
        module: the loaded masker.
        argv: the command through the image.
        run: the run directory.

    Returns:
        Whether ``check_container`` refused it.
    """
    try:
        module.check_container(argv, run)
    except module.spec_secrets.SpecSecretsError:
        return True
    return False


def with_ca(root: Path, run: Path, block: list[str]) -> list[str]:
    """Build ``container_argv`` with CA trust words in front of ``-w``.

    Args:
        root: the scratch dir.
        run: the run directory.
        block: the CA trust words, which the stage ``.ca-trust`` holds too,
            one a line, as the deploy writes them.

    Returns:
        The container command.
    """
    argv = container_argv(root, run)
    (root / "stage" / ".ca-trust").write_text("".join(f"{w}\n" for w in block))
    at = argv.index("-w")
    return [*argv[:at], *block, *argv[at:]]


def tool_env_seen(caller: dict[str, str], *replacements: tuple[str, str]) -> list:
    """Mask a run whose caller carries extra variables.

    Args:
        caller: the variables the masker's caller adds; a ``DOCKER_CONFIG``
            among them names a fresh dir of this user, which the masker
            trusts like root's.
        *replacements: changes to the masker, for a negative control.

    Returns:
        The names of ``caller`` the container tool's command saw.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, OWN_UID, *replacements)
        docker = root.resolve() / "docker-config"
        docker.mkdir(mode=0o755)
        docker.chmod(0o755)
        if "DOCKER_CONFIG" in caller:
            caller = {**caller, "DOCKER_CONFIG": str(docker)}
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        probe = root / "env.json"
        container, env = exec_tool(
            root, directory, [sys.executable, "-c", WRITE_ENV, str(probe)]
        )
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        subprocess.run(
            [*masker, str(directory), str(root / "reports"), "--", *container, "--"],
            capture_output=True,
            check=False,
            env={**env, **caller},
        )
        seen = json.loads(scratch_text(probe)) if probe.exists() else ["no run"]
        return sorted(set(seen) & {*caller, "no run"})


def ca_argv(cert: Path) -> list[str]:
    """Render the CA trust words the setup defines once for the run and the rerun.

    Args:
        cert: the host certificate ``CA_TRUST.cert_host`` names.

    Returns:
        The words of ``_playwright_ca_argv``.
    """
    defined = role_task("01_setup/shared_checks.yml", CA_FACTS)
    trust = {**CA_TRUST, "cert_host": str(cert), "trust_name": TRUST_NAME}
    return render(
        defined["ansible.builtin.set_fact"]["_playwright_ca_argv"], CA_TRUST=trust
    )


def entrypoint_violations(run_one: list[dict]) -> list[str]:
    """Check that a run with spec secrets and CA trust refuses an image with ENTRYPOINT or none to inspect.

    Args:
        run_one: the parsed ``02_run_one.yml``.

    Returns:
        One message per broken expectation: the inspect does not read the
        image's ENTRYPOINT, a refusal of ``REFUSALS`` is missing or fires
        for another case than its own, or the pull refusal blames the
        ENTRYPOINT instead of naming the pull's exit code.
    """
    inspect = role_task("01_setup/shared_checks.yml", "🔎 Read the Playwright image")
    argv = [
        render(str(word), TEST_E2E_PLAYWRIGHT_IMAGE=IMAGE)
        for word in inspect["ansible.builtin.command"]["argv"]
    ]
    problems = [] if argv == INSPECT else [f"the image is inspected with {argv}"]
    if inspect.get("register") != ENTRYPOINT_FACT:
        problems.append("the inspect result goes elsewhere")
    run_at = next(
        i
        for i, task in enumerate(run_one)
        if task.get("ansible.builtin.include_tasks") == "03_run_pass.yml"
    )
    refusals = {
        key: task
        for key, prefix in REFUSALS.items()
        for task in run_one[:run_at]
        if "ansible.builtin.fail" in task and task.get("name", "").startswith(prefix)
    }
    missing = sorted(set(REFUSALS) - set(refusals))
    if missing:
        return [*problems, f"a run with spec secrets lacks the {missing} refusal"]
    for name, (found, expected) in ENTRYPOINTS.items():
        scope = {
            "_playwright_secrets_template_stat": {"stat": {"exists": True}},
            "_playwright_ca_required": True,
            ENTRYPOINT_FACT: found,
        }
        fired = [key for key, task in refusals.items() if holds(task["when"], **scope)]
        if fired != expected:
            problems.append(f"an image with {name} fires {fired}, not {expected}")
    for exists, required in ((False, True), (True, False)):
        scope = {
            "_playwright_secrets_template_stat": {"stat": {"exists": exists}},
            "_playwright_ca_required": required,
        }
        if any(holds(task["when"], **scope) for task in refusals.values()):
            problems.append(f"a refusal fires for template {exists}, CA {required}")
    said = render(
        refusals["pull"]["ansible.builtin.fail"]["msg"],
        TEST_E2E_PLAYWRIGHT_IMAGE=IMAGE,
        application_id="web-app-x",
        _playwright_shared_pull={"rc": 125},
        **{ENTRYPOINT_FACT: {"rc": 1}},
    )
    if "ENTRYPOINT" in said or "pull rc 125" not in said:
        problems.append("the pull refusal does not name the failed pull")
    return problems


class TestSpecSecretsTrust(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.module = load_from(self.root / "bin", self.root, OWN_UID)
        self.run_dir = self.root / "run"

    def test_the_ca_paths_are_the_group_vars_ones(self) -> None:
        checked = sys.modules[self.module.check_container.__module__]
        self.assertEqual(checked.CA_CERT, CA_CERT)

    def test_the_role_ca_trust_whole_passes(self) -> None:
        argv = with_ca(self.root, self.run_dir, ca_block(ca_files(self.root, CA_MODE)))
        self.assertFalse(refused(self.module, argv, self.run_dir))

    def test_partial_foreign_or_planted_ca_trust_is_refused(self) -> None:
        cert = ca_files(self.root, CA_MODE)
        for name, block in ca_variants(cert).items():
            with self.subTest(variant=name):
                argv = with_ca(self.root, self.run_dir, block)
                self.assertTrue(refused(self.module, argv, self.run_dir))
        for name, (mode, linked) in {
            "group writable": (0o664, False),
            "linked": (0o644, True),
        }.items():
            with self.subTest(certificate=name):
                scratch = self.root / name.replace(" ", "-")
                scratch.mkdir()
                block = ca_block(ca_files(scratch, mode, linked))
                argv = with_ca(self.root, self.run_dir, block)
                self.assertTrue(refused(self.module, argv, self.run_dir))

    def test_a_hard_linked_or_foreign_certificate_is_refused(self) -> None:
        cert = ca_files(self.root, CA_MODE)
        argv = with_ca(self.root, self.run_dir, ca_block(cert))
        foreign = load_from(self.root / "other", self.root, OTHER_UID)
        self.assertTrue(refused(foreign, argv, self.run_dir))
        os.link(cert, self.root / "kept.crt")
        self.assertTrue(refused(self.module, argv, self.run_dir))

    def test_the_ca_wrapper_cli_is_refused(self) -> None:
        argv = container_argv(self.root, self.run_dir)
        self.assertTrue(refused(self.module, ["container", *argv[1:]], self.run_dir))

    def test_the_rendered_deploy_command_with_ca_trust_passes(self) -> None:
        cert = ca_files(self.root, CA_MODE)
        container_argv(self.root, self.run_dir)
        (self.root / "stage" / ".ca-trust").write_text(
            "".join(f"{w}\n" for w in ca_argv(cert))
        )
        shared = self.root / "_shared"
        facts = {
            **ARGV_VARS,
            "_playwright_stage_dir": str(self.root / "stage"),
            "TEST_E2E_PLAYWRIGHT_SHARED_NODE_MODULES": f"{shared}/node_modules",
            "TEST_E2E_PLAYWRIGHT_SHARED_PERSONAS": f"{shared}/personas",
            "TEST_E2E_PLAYWRIGHT_IMAGE": IMAGE,
            "TEST_E2E_PLAYWRIGHT_MASK_ARGV": [],
            "_playwright_secrets_template_stat": {"stat": {"exists": True}},
            "_playwright_ca_required": True,
            "_playwright_ca_argv": ca_argv(cert),
            PATH_FACT: str(self.run_dir),
        }
        argv = render(run_argv(), **facts)
        container = argv[argv.index("docker") : argv.index(IMAGE) + 1]
        self.assertNotIn("--entrypoint", container)
        self.assertEqual(container.count(f"SSL_CERT_FILE={CA_CERT}"), 1)
        self.assertFalse(refused(self.module, container, self.run_dir))

    def test_an_image_with_an_entrypoint_is_refused_before_the_run(self) -> None:
        self.assertEqual(entrypoint_violations(role_tasks("02_run_one.yml")), [])

    def test_the_container_tool_gets_no_ca_or_proxy_variable(self) -> None:
        self.assertEqual(tool_env_seen(PLAY_ENV), [])

    def test_the_container_tool_keeps_the_docker_platform_and_config(self) -> None:
        self.assertEqual(tool_env_seen(DOCKER_ENV), sorted(DOCKER_ENV))

    def test_the_env_file_takes_no_runtime_switch(self) -> None:
        self.assertEqual(
            [
                key
                for key in RUNTIME_KEYS
                if not env_refused(f"{key}=/e2e/x", keys=f"APP_BASE_URL\n{key}\n")
            ],
            [],
        )


class TestSpecSecretsTrustNegativeControls(unittest.TestCase):
    def test_a_masker_that_hands_its_tool_the_play_env_is_caught(self) -> None:
        self.assertEqual(tool_env_seen(PLAY_ENV, INHERITING), sorted(PLAY_ENV))

    def test_a_masker_that_drops_the_docker_platform_is_caught(self) -> None:
        self.assertEqual(tool_env_seen(DOCKER_ENV, NARROW), [])

    def test_a_check_that_takes_partial_or_planted_ca_trust_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            cert = ca_files(root, CA_MODE)
            partial = with_ca(root, run, ca_block(cert)[:-2])
            module = load_from(root / "bin", root, OWN_UID, PARTIAL, WORDS_TAKEN)
            self.assertFalse(refused(module, partial, run))
            cert.chmod(0o664)
            planted = with_ca(root, run, ca_block(cert))
            module = load_from(root / "bin", root, OWN_UID, UNTRUSTING)
            self.assertFalse(refused(module, planted, run))
            module = load_from(root / "bin", root, WRAPPED)
            wrapped = ["container", *container_argv(root, run)[1:]]
            self.assertFalse(refused(module, wrapped, run))

    def test_a_check_that_takes_a_hard_linked_or_foreign_certificate_is_caught(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            cert = ca_files(root, CA_MODE)
            argv = with_ca(root, run, ca_block(cert))
            os.link(cert, root / "kept.crt")
            module = load_from(root / "bin", root, OTHER_UID, LAX)
            self.assertFalse(refused(module, argv, run))

    def test_a_run_that_takes_an_image_with_an_entrypoint_is_caught(self) -> None:
        for key, prefix in REFUSALS.items():
            with self.subTest(refusal=key):
                run_one = [
                    task
                    for task in copy.deepcopy(role_tasks("02_run_one.yml"))
                    if not task.get("name", "").startswith(prefix)
                ]
                self.assertEqual(
                    entrypoint_violations(run_one),
                    [f"a run with spec secrets lacks the {[key]} refusal"],
                )

    def test_a_pull_refusal_that_blames_the_entrypoint_is_caught(self) -> None:
        run_one = copy.deepcopy(role_tasks("02_run_one.yml"))
        pull = next(t for t in run_one if t["name"].startswith(REFUSALS["pull"]))
        pull["ansible.builtin.fail"]["msg"] = (
            "{{ TEST_E2E_PLAYWRIGHT_IMAGE }} has an ENTRYPOINT"
        )
        self.assertEqual(
            entrypoint_violations(run_one),
            ["the pull refusal does not name the failed pull"],
        )

    def test_an_env_file_check_that_misses_a_runtime_switch_is_caught(self) -> None:
        self.assertEqual(
            [
                key
                for key in RUNTIME_KEYS
                if env_refused(
                    f"{key}=/e2e/x", OLD_RUNTIME, keys=f"APP_BASE_URL\n{key}\n"
                )
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
