import unittest

from jinja2 import DictLoader, Environment, StrictUndefined

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-atmo"
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

    def test_dockerfile_fetches_exactly_the_ref_it_is_given(self):
        self.assertIn('git fetch -q --depth=1 origin "${ATMO_REF}"', self.text)
        self.assertIn("git checkout -q --detach FETCH_HEAD", self.text)
        self.assertIn("pnpm install --frozen-lockfile", self.text)

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
        self.assertIn('grep -qx "export const ALLOW_SIGNUP = true;"', self.text)
        self.assertIn("grep -q \"production: 'https://selfhosted.social/'\"", self.text)


if __name__ == "__main__":
    unittest.main()
