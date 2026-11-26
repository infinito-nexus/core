import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import DictLoader, Environment, StrictUndefined

from tests.lint.repository import dockerfile_instructions
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-atmo"
DOCKERFILE = ROLE / "files" / "Dockerfile"
TEMPLATE = f"roles/web-app-atmo/{ROLE_FILE_TEMPL_COMPOSE}"
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}
VARIABLES = {
    "application_id": "web-app-atmo",
    "container_port": "8080",
    "container_hostname": "atmo-host",
    "DOCKER_BIND_HOST": "127.0.0.1",
    "ATMO_NODE_BASE": "node:26-slim",
    "ATMO_REPO_URL": "https://github.com/flo-bit/atmo-events.git",
    "ATMO_REF": "83e3d1067a5c13de2e850ad290f62de82a727923",
    "ATMO_SIGNUP_PDS": "https://api.bluesky.example.org/",
    "ATMO_DATA_DIR": "/data",
    "ATMO_BRIDGE_STATE_DIR": "/var/lib/atmo-bridge",
    "ATMO_SCRIPTS": "/opt/atmo",
    "ATMO_DOMAIN": "rsvp.example.org",
    "ATMO_CONTAINER": "atmo",
    "ATMO_CRON_CONTAINER": "atmo-cron",
    "ATMO_BRIDGE_CONTAINER": "atmo-bridge",
}


def _lookup(name, *terms, **_kwargs):
    if name == "template":
        return "build:\n  context: .\n  dockerfile: Dockerfile"
    if name == "container_image":
        return f'image: "{terms[1]}_custom:26-slim"'
    if name == "compose_only":
        return f"{terms[0]}: {terms[1]}"
    return ""


def render(bridge_enabled: bool) -> dict:
    """Render the compose template with stubbed lookups.

    Args:
        bridge_enabled: value of ``ATMO_BRIDGE_ENABLED``.

    Returns:
        The ``services`` mapping of the rendered file.
    """
    environment = Environment(
        loader=DictLoader(
            {**INCLUDES, TEMPLATE: read_text(str(PROJECT_ROOT / TEMPLATE))}
        ),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - renders a compose YAML file, not markup
    )
    environment.globals["lookup"] = _lookup
    environment.filters["bool"] = bool
    rendered = environment.get_template(TEMPLATE).render(
        **VARIABLES, ATMO_BRIDGE_ENABLED=bridge_enabled
    )
    return load_yaml_str(rendered)["services"]


PACKAGE_MANAGER = "pnpm@10.4.1"
STUBBED = ("git", "node", "npm", "pnpm", "rm")
STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "${0##*/} $*" >>"${STUB_LOG}"\n'
    '[ "${0##*/} ${1-}" != "${STUB_FAIL-}" ] || exit 1\n'
    '[ "${0##*/}" != node ] || printf "%s\\n" "${STUB_PACKAGE_MANAGER}"\n'
)
SETTINGS = "apps/web/src/lib/atproto/settings.ts"
UPSTREAM_SIGNUP = "https://selfhosted.social/"
UPSTREAM_SETTINGS = (
    "export const ALLOW_SIGNUP = true;\n"
    "\n"
    "export const SIGNUP_PDS = {\n"
    f"\tproduction: '{UPSTREAM_SIGNUP}',\n"
    "\tdevelopment: 'http://localhost:2583/'\n"
    "};\n"
)
DRIFTED_SETTINGS = (
    UPSTREAM_SETTINGS.replace("ALLOW_SIGNUP = true", "ALLOW_SIGNUP = !dev"),
    UPSTREAM_SETTINGS.replace(UPSTREAM_SIGNUP, "https://bsky.social/"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir


def _step(command: str) -> str:
    """
    Args:
        command: a command only the wanted RUN instruction of the Dockerfile
            holds.

    Returns:
        The shell command of that RUN instruction, continuations joined.
    """
    (step,) = [
        arguments
        for keyword, arguments in dockerfile_instructions(read_text(str(DOCKERFILE)))
        if keyword == "RUN" and command in arguments
    ]
    return step


def _build(
    command: str, env: dict[str, str], files: dict[str, str]
) -> tuple[subprocess.CompletedProcess, list[str], dict[str, str]]:
    """Args:
        command: selects the RUN instruction, see ``_step``.
        env: build args and stub switches over the defaults; ``STUB_FAIL``
            names the ``<tool> <subcommand>`` call that exits 1.
        files: WORKDIR-relative files the checkout holds before the step.

    Returns:
        The finished run, every stubbed call in order, and the text of
        ``files`` after the step.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir, workdir, log = root / "bin", root / "app", root / "calls.log"
        bin_dir.mkdir()
        workdir.mkdir()
        log.touch()
        for name in STUBBED:
            (bin_dir / name).write_text(STUB, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        for relative, text in files.items():
            (workdir / relative).parent.mkdir(parents=True, exist_ok=True)
            (workdir / relative).write_text(text, encoding="utf-8")
        done = subprocess.run(
            ["bash", "-c", _step(command)],
            cwd=workdir,
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
                "STUB_PACKAGE_MANAGER": PACKAGE_MANAGER,
                "ATMO_REPO_URL": VARIABLES["ATMO_REPO_URL"],
                "ATMO_REF": VARIABLES["ATMO_REF"],
                "ATMO_SIGNUP_PDS": VARIABLES["ATMO_SIGNUP_PDS"],
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        calls = _read(log).splitlines()
        after = {relative: _read(workdir / relative) for relative in files}
    return done, calls, after


class TestComposeTemplate(unittest.TestCase):
    def test_bridge_is_only_scheduled_when_enabled(self):
        self.assertEqual(set(render(False)), {"atmo", "cron"})
        self.assertEqual(set(render(True)), {"atmo", "cron", "bridge"})

    def test_atmo_runs_the_upstream_worker_under_wrangler_with_persistent_bindings(
        self,
    ):
        command = render(False)["atmo"]["command"]
        self.assertEqual(command[:3], ["node_modules/.bin/wrangler", "dev", "--local"])
        pairs = dict(zip(command[3::2], command[4::2], strict=False))
        self.assertEqual(pairs["--ip"], "0.0.0.0")  # noqa: S104 - asserts the bind the template renders inside the container
        self.assertEqual(pairs["--port"], "8080")
        self.assertEqual(pairs["--persist-to"], "/data")
        self.assertEqual(pairs["--local-upstream"], "rsvp.example.org")
        self.assertEqual(pairs["--upstream-protocol"], "https")
        self.assertIn("--show-interactive-dev-session=false", command)

    def test_atmo_is_built_from_the_pinned_upstream_ref(self):
        build = render(False)["atmo"]["build"]
        self.assertEqual(build["dockerfile"], "Dockerfile")
        self.assertEqual(build["args"]["ATMO_REF"], VARIABLES["ATMO_REF"])
        self.assertEqual(build["args"]["ATMO_REPO_URL"], VARIABLES["ATMO_REPO_URL"])
        self.assertEqual(build["args"]["ATMO_SIGNUP_PDS"], VARIABLES["ATMO_SIGNUP_PDS"])

    def test_sidecars_reuse_the_built_image_without_pulling(self):
        services = render(True)
        for name, script in (("cron", "cron.py"), ("bridge", "bridge.py")):
            with self.subTest(service=name):
                self.assertEqual(services[name]["image"], services["atmo"]["image"])
                self.assertEqual(services[name]["pull_policy"], "never")
                self.assertNotIn("build", services[name])
                self.assertEqual(
                    services[name]["command"], ["python3", f"/opt/atmo/{script}", "run"]
                )


class TestDockerfile(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(ROLE / "files" / "Dockerfile"))

    def test_the_build_installs_exactly_the_fetched_ref_from_its_lockfile(self):
        done, calls, _after = _build("git fetch", {}, {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            calls,
            [
                "git init -q .",
                f"git remote add origin {VARIABLES['ATMO_REPO_URL']}",
                f"git fetch -q --depth=1 origin {VARIABLES['ATMO_REF']}",
                "git checkout -q --detach FETCH_HEAD",
                "rm -rf .git",
            ],
        )
        done, calls, _after = _build("pnpm install", {}, {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            [call for call in calls if not call.startswith("node ")],
            [
                f"npm install -g --no-fund --no-audit {PACKAGE_MANAGER}",
                "pnpm install --frozen-lockfile",
            ],
        )

    def test_negative_control_a_failed_fetch_fails_before_the_checkout(self):
        done, calls, _after = _build("git fetch", {"STUB_FAIL": "git fetch"}, {})
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(
            calls[-1], f"git fetch -q --depth=1 origin {VARIABLES['ATMO_REF']}"
        )

    def test_every_build_arg_is_declared_without_a_default(self):
        args = {
            line.split()[1]
            for line in self.text.splitlines()
            if line.startswith("ARG ")
        }
        self.assertTrue(all("=" not in arg for arg in args))
        passed = set(render(False)["atmo"]["build"]["args"])
        self.assertEqual(args, passed)

    def test_signup_patch_fails_the_build_when_upstream_drifts(self):
        for drifted in DRIFTED_SETTINGS:
            for pds in (VARIABLES["ATMO_SIGNUP_PDS"], ""):
                with self.subTest(drifted=drifted, pds=pds):
                    done, _calls, after = _build(
                        SETTINGS, {"ATMO_SIGNUP_PDS": pds}, {SETTINGS: drifted}
                    )
                    self.assertNotEqual(done.returncode, 0)
                    self.assertEqual(after[SETTINGS], drifted)

    def test_the_signup_patch_points_signups_at_the_platform_pds(self):
        pds = VARIABLES["ATMO_SIGNUP_PDS"]
        done, _calls, after = _build(SETTINGS, {}, {SETTINGS: UPSTREAM_SETTINGS})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            after[SETTINGS], UPSTREAM_SETTINGS.replace(UPSTREAM_SIGNUP, pds)
        )

    def test_without_a_pds_the_signup_patch_closes_signups(self):
        done, _calls, after = _build(
            SETTINGS, {"ATMO_SIGNUP_PDS": ""}, {SETTINGS: UPSTREAM_SETTINGS}
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            after[SETTINGS],
            UPSTREAM_SETTINGS.replace("ALLOW_SIGNUP = true", "ALLOW_SIGNUP = false"),
        )


if __name__ == "__main__":
    unittest.main()
