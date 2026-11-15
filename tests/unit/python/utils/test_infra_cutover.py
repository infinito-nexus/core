from __future__ import annotations

import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development.extra_mounts import write_mounts_override
from cli.administration.infra import __main__ as cli
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml
from utils.infra import (
    CACHE_SERVICES,
    NETWORK,
    ROOTS_OVERRIDE,
    SERVICE,
    cache_container,
    inner_docker,
    unmounted,
)

_CACHE_KEY = re.compile(r"INFINITO_CACHE_[A-Z_]+")
_CACHE_INSPECT = re.compile(r"docker inspect[^\n]*(registry-cache|package-cache)")
_HOST_CACHE_DOCKER = re.compile(
    r"(?<![-\w])docker (?:ps|inspect|exec|logs|stop|rm)\b[^\n]*"
    r"(?:registry-cache|package-cache|cache-registry)"
)


def _worktree_cache_wiring(text: str) -> list[str]:
    """Args:
        text: content of a worktree script.

    Returns:
        Every cache key it pins and every cache container it inspects.
    """
    return [*_CACHE_KEY.findall(text), *_CACHE_INSPECT.findall(text)]


def _writable_checkout_binds(volumes: list, roots: list[Path]) -> list[str]:
    """Args:
        volumes: compose volume entries of the runner.
        roots: checkout roots the runner sees.

    Returns:
        Every bind of a checkout root that is not read-only.
    """
    found: list[str] = []
    for volume in volumes:
        if isinstance(volume, str):
            source, _, rest = volume.partition(":")
            writable = not rest.endswith(":ro")
        else:
            source = str(volume.get("source", ""))
            writable = not volume.get("read_only", False)
        if writable and any(Path(source).is_relative_to(root) for root in roots):
            found.append(source)
    return found


class TestWorktreeUpWritesNoCacheWiring(unittest.TestCase):
    def test_worktree_up_pins_no_cache_key_and_inspects_no_cache(self) -> None:
        for name in ("up.sh", "lib.sh"):
            text = read_text(str(PROJECT_ROOT / "scripts/system/worktree" / name))
            self.assertEqual(_worktree_cache_wiring(text), [], name)

    def test_a_planted_cache_pin_would_be_found(self) -> None:
        planted = "INFINITO_CACHE_NETWORK=x\ndocker inspect infinito-registry-cache\n"
        self.assertEqual(len(_worktree_cache_wiring(planted)), 2)


class TestCheckoutRootsStayReadOnly(unittest.TestCase):
    def setUp(self) -> None:
        self.roots = [Path("/srv/core"), Path("/home/me/.local/share/worktrees")]

    def _volumes(self) -> list:
        compose = load_yaml(PROJECT_ROOT / "compose/infra.yml")
        volumes = list(compose["services"][SERVICE]["volumes"])
        with tempfile.TemporaryDirectory() as tmp:
            relative = write_mounts_override(
                Path(tmp), self.roots, service=SERVICE, override=ROOTS_OVERRIDE
            )
            override = load_yaml(Path(tmp) / relative)
        return [*volumes, *override["services"][SERVICE]["volumes"]]

    def test_every_checkout_root_is_mounted_read_only(self) -> None:
        self.assertEqual(_writable_checkout_binds(self._volumes(), self.roots), [])

    def test_a_writable_checkout_bind_would_be_found(self) -> None:
        planted = [
            *self._volumes(),
            {"type": "bind", "source": "/srv/core", "target": "/srv/core"},
            "/home/me/.local/share/worktrees/x:/x",
        ]
        self.assertEqual(
            _writable_checkout_binds(planted, self.roots),
            ["/srv/core", "/home/me/.local/share/worktrees/x"],
        )

    def test_the_cache_names_resolve_to_the_runner_on_the_infra_network(self) -> None:
        compose = load_yaml(PROJECT_ROOT / "compose/infra.yml")
        joined = compose["services"][SERVICE]["networks"]
        (network,) = joined
        self.assertEqual(compose["networks"][network]["name"], NETWORK)
        self.assertLessEqual(
            {
                "infinito-registry-cache",
                "infinito-package-cache",
                "infinito-package-cache-frontend",
            },
            set(joined[network]["aliases"]),
        )

    def test_the_infra_network_carries_the_stack_network_mtu(self) -> None:
        mtu = "com.docker.network.driver.mtu"
        stack = load_yaml(PROJECT_ROOT / "compose.yml")["networks"]["default"]
        infra = load_yaml(PROJECT_ROOT / "compose/infra.yml")["networks"]
        (network,) = infra.values()
        self.assertEqual(network["driver_opts"][mtu], stack["driver_opts"][mtu])

    def test_the_runner_writes_its_ansible_state_to_its_own_volume(self) -> None:
        runner = load_yaml(PROJECT_ROOT / "compose/infra.yml")["services"][SERVICE]
        self.assertIn("state:/var/lib/infinito-infra", runner["volumes"])
        for key in ("ANSIBLE_HOME", "ANSIBLE_LOCAL_TEMP"):
            self.assertTrue(
                runner["environment"][key].startswith("/var/lib/infinito-infra/"), key
            )


def _host_cache_lookups(text: str) -> list[str]:
    """Args:
        text: content of a shell script.

    Returns:
        Every docker call on the host daemon that names a cache container.
    """
    return _HOST_CACHE_DOCKER.findall(text)


class TestCachesAreReachedThroughTheRunner(unittest.TestCase):
    def test_no_script_looks_for_a_cache_container_on_the_host(self) -> None:
        scripts = f"{PROJECT_ROOT / 'scripts'}{os.sep}"
        found = {
            os.path.relpath(path, PROJECT_ROOT): hits
            for path in iter_project_files(extensions=(".sh",))
            if path.startswith(scripts)
            and (hits := _host_cache_lookups(read_text(path)))
        }
        self.assertEqual(found, {})

    def test_a_planted_host_lookup_would_be_found(self) -> None:
        planted = 'docker exec infinito-package-cache curl x\ndocker logs "$(c)"\n'
        self.assertEqual(len(_host_cache_lookups(planted)), 1)

    def test_the_names_come_from_the_cache_roles(self) -> None:
        self.assertEqual(
            {kind: cache_container(PROJECT_ROOT, kind) for kind in CACHE_SERVICES},
            {
                "registry": "cache-registry",
                "package": "package-cache",
                "frontend": "package-cache-frontend",
            },
        )

    def test_docker_runs_on_the_runner_daemon(self) -> None:
        self.assertEqual(
            inner_docker(["compose"], ["ps"]),
            ["compose", "exec", "-T", SERVICE, "docker", "ps"],
        )


def _open_ports(ports: list[str]) -> list[str]:
    """Args:
        ports: compose port entries of the runner.

    Returns:
        Every entry not bound to the loopback address.
    """
    return [port for port in ports if not port.startswith("127.0.0.1:")]


class TestHostReachesOnlyLoopbackPorts(unittest.TestCase):
    def setUp(self) -> None:
        runner = load_yaml(PROJECT_ROOT / "compose/infra.yml")["services"][SERVICE]
        self.ports = list(runner["ports"])

    def test_the_runner_publishes_gateway_and_nexus_on_loopback_only(self) -> None:
        self.assertEqual(_open_ports(self.ports), [])
        self.assertEqual(
            [port.split(":", 1)[1].split("}", 1)[0] for port in self.ports],
            [
                "${INFINITO_TOOLS_TRANSLATE_PORT:?Run 'make dotenv' to generate the .env single source of truth",
                "${INFINITO_CACHE_PACKAGE_PORT:?Run 'make dotenv' to generate the .env single source of truth",
            ],
        )

    def test_a_port_on_every_interface_would_be_found(self) -> None:
        self.assertEqual(_open_ports([*self.ports, "8081:8081"]), ["8081:8081"])

    def test_host_sync_reaches_nexus_on_the_published_loopback_port(self) -> None:
        recipe = read_text(str(PROJECT_ROOT / "Makefile"))
        sync = recipe.split("\ncache-host-sync:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn(
            '--nexus "http://$${INFINITO_CACHE_PACKAGE_REST_HOST}:$${INFINITO_CACHE_PACKAGE_PORT}"',
            sync,
        )
        self.assertNotIn("INFINITO_BIND_IP", sync)


_BASE = Path("/var/cache/infinito")
_PINS = Path("/home/me/.local/share/infinito/cache")
_CONF = "INFINITO_CACHE_PACKAGE_FRONTEND_CONF"


class TestUnmountedHostPathsAreRefused(unittest.TestCase):
    def test_a_models_path_outside_the_cache_base_is_named(self) -> None:
        refused = unmounted(
            _BASE, _PINS, {"INFINITO_TOOLS_MODELS_HOST_PATH": "/srv/models"}
        )
        self.assertEqual(len(refused), 1)
        self.assertIn("INFINITO_TOOLS_MODELS_HOST_PATH=/srv/models", refused[0])

    def test_cache_data_below_the_read_only_pin_root_is_refused(self) -> None:
        refused = unmounted(
            _BASE, _PINS, {"INFINITO_TOOLS_MODELS_HOST_PATH": f"{_PINS}/models"}
        )
        self.assertEqual(len(refused), 1)

    def test_a_pin_path_outside_both_roots_is_refused(self) -> None:
        refused = unmounted(_BASE, _PINS, {_CONF: "/etc/infinito/upstreams.conf"})
        self.assertEqual(len(refused), 1)
        self.assertIn(f"{_CONF}=/etc/infinito/upstreams.conf", refused[0])
        self.assertIn(str(_PINS), refused[0])

    def test_paths_below_their_roots_or_unset_pass(self) -> None:
        self.assertEqual(
            unmounted(
                _BASE,
                _PINS,
                {
                    "INFINITO_TOOLS_MODELS_HOST_PATH": f"{_BASE}/models",
                    "INFINITO_CACHE_PACKAGE_HOST_PATH": "",
                    _CONF: f"{_PINS}/upstreams.conf",
                },
            ),
            [],
        )

    def test_the_runner_mounts_the_pin_root_read_only_at_its_host_path(self) -> None:
        runner = load_yaml(PROJECT_ROOT / "compose/infra.yml")["services"][SERVICE]
        pin = [
            volume
            for volume in runner["volumes"]
            if isinstance(volume, dict)
            and "INFINITO_CACHE_PIN_ROOT" in volume["source"]
        ]
        self.assertEqual(len(pin), 1)
        self.assertEqual(pin[0]["source"].split(":", 1)[0], "${INFINITO_CACHE_PIN_ROOT")
        self.assertEqual(pin[0]["target"], "${INFINITO_CACHE_PIN_ROOT}")
        self.assertIs(pin[0]["read_only"], True)

    def test_a_writable_pin_mount_would_be_found(self) -> None:
        planted = {"type": "bind", "source": str(_PINS), "target": str(_PINS)}
        self.assertEqual(_writable_checkout_binds([planted], [_PINS]), [str(_PINS)])

    def test_infra_up_refuses_before_it_starts_anything(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "INFINITO_TOOLS_MODELS_HOST_PATH": "/srv/models",
                    "INFINITO_CACHE_PIN_ROOT": str(_PINS),
                    _CONF: f"{_PINS}/upstreams.conf",
                },
            ),
            patch.object(cli, "base", return_value=_BASE),
            patch.object(cli, "up", side_effect=AssertionError("started")),
            self.assertRaisesRegex(SystemExit, "/srv/models"),
        ):
            cli._up(
                [],
                Path("/srv/core"),
                print,
                recreate=False,
                takeover=False,
                bridge=None,
            )


class TestTakeoverRefusal(unittest.TestCase):
    def _refusal(self, names: str | None, *, takeover: bool) -> list[str]:
        with (
            patch.object(cli, "base", return_value=_BASE),
            patch.object(cli, "base_refusal", return_value=[]),
            patch.object(cli, "build_cache_usage"),
            patch.object(cli, "floor_refusal", return_value=[]),
        ):
            return cli._refusal(names, takeover=takeover)

    def test_a_takeover_lets_a_running_legacy_stack_pass(self) -> None:
        self.assertEqual(self._refusal("infinito-registry-cache\n", takeover=True), [])

    def test_without_takeover_a_running_legacy_stack_is_refused(self) -> None:
        self.assertTrue(self._refusal("infinito-registry-cache\n", takeover=False))

    def test_an_unanswered_host_refuses_even_a_takeover(self) -> None:
        self.assertTrue(self._refusal(None, takeover=True))

    def test_only_a_takeover_derives_the_legacy_bridge(self) -> None:
        with (
            patch.dict(os.environ, {"INFINITO_CACHE_STACK": "true", "CI": ""}),
            patch.object(cli, "_legacy_bridge", side_effect=AssertionError("derived")),
            patch.object(cli, "_prepare", side_effect=RuntimeError("prepared")),
        ):
            for action in ("up", "update", "attach", "down", "docker"):
                with self.subTest(action=action), self.assertRaises(RuntimeError):
                    cli.main([action])
            with self.assertRaisesRegex(AssertionError, "derived"):
                cli.main(["--takeover", "up"])


class TestDisabledCacheStackStartsNoInfra(unittest.TestCase):
    def _main(self, action: str, stack: str) -> tuple[int, str]:
        out = io.StringIO()
        with (
            patch.dict(os.environ, {"INFINITO_CACHE_STACK": stack, "CI": ""}),
            patch.object(cli, "_prepare", side_effect=AssertionError("prepared")),
            patch.object(
                cli, "render_inventory", side_effect=AssertionError("rendered")
            ),
            patch("sys.stderr", io.StringIO()),
            redirect_stdout(out),
        ):
            code = cli.main([action])
        return code, out.getvalue()

    def test_no_starting_target_touches_the_runner_or_the_inventory(self) -> None:
        for action in cli.STARTING:
            self.assertEqual(self._main(action, "false"), (0, ""), action)

    def test_an_enabled_cache_stack_prepares_the_runner(self) -> None:
        with self.assertRaisesRegex(AssertionError, "prepared"):
            self._main("up", "true")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
