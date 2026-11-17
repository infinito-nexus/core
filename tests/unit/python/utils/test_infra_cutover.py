from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development.extra_mounts import write_mounts_override
from cli.administration.infra import __main__ as cli
from cli.meta.cache.base import __main__ as base_cli
from utils.cache.evict import CACHES, FLOOR_KEY, IDLE_KEY, parse_size
from utils.cache.files import (
    PROJECT_ROOT,
    iter_project_files,
    read_text,
    repository_files,
)
from utils.cache.yaml import load_yaml
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import conf as frontend_conf
from utils.env.handlers.infinito.cache import paths as cache_paths
from utils.env.handlers.infinito.cache.paths import BASE_KEY
from utils.env.handlers.infinito.cache.pin import ROOT_KEY as PIN_ROOT_KEY
from utils.env.handlers.infinito.tools import idle, models
from utils.env.handlers.infinito.tools.idle import STAMP_DIR_KEY
from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY
from utils.env.parser import parse_static_env
from utils.infra import (
    BRIDGE_NAME,
    CACHE_SERVICES,
    LOCK_NAME,
    NETWORK,
    OWNER_NAME,
    ROOTS_KEY,
    ROOTS_OVERRIDE,
    RUNNER_CONTAINER_KEY,
    SERVICE,
    cache_container,
    inner_docker,
    unmounted,
)
from utils.inventory import tools_vars

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


_WORKSPACE = PROJECT_ROOT / ".github" / "workflows" / "call-test-workspace.yml"
_MOVED = Path("/mnt/cache")


def _derived_env(exported: dict[str, str]) -> tuple[Path, dict[str, str]]:
    """Args:
        exported: the INFINITO_* variables a job exports; every guarded path
            it leaves out derives from the cache base as ``make dotenv`` does.

    Returns:
        The cache base and the environment ``make infra-up`` then checks.
    """
    blank = dict.fromkeys(
        (
            BASE_KEY,
            MODELS_KEY,
            STAMP_DIR_KEY,
            *(key for key, _legs, _note in cache_paths.ENTRIES),
        ),
        "",
    )
    with (
        tempfile.TemporaryDirectory() as checkout,
        patch.dict(os.environ, {**blank, **exported}),
    ):
        context = BuildContext(
            static={},
            static_comments={},
            repo_root=Path(checkout),
            on_gha=False,
            on_act=False,
        )
        builder = EnvBuilder()
        cache_paths.apply(builder, context)
        idle.apply(builder, context)
        models.apply(builder, context)
        frontend_conf.finalize(builder)
        return Path(builder.values[BASE_KEY]), {**exported, **builder.values}


def _workspace_env() -> dict[str, str]:
    """Returns:
    The INFINITO_* variables the workspace job exports into its container.
    """
    env = load_yaml(_WORKSPACE)["jobs"]["test-workspace"]["env"]
    return {
        key: str(value) for key, value in env.items() if key.startswith("INFINITO_")
    }


class TestWorkspaceCachePathsLieBelowTheBase(unittest.TestCase):
    def test_the_workspace_job_passes_the_mount_guard(self) -> None:
        exported = _workspace_env()
        root, env = _derived_env(exported)
        self.assertEqual(unmounted(root, Path(exported[PIN_ROOT_KEY]), env), [])

    def test_the_workspace_job_keeps_its_caches_on_the_spare_disk(self) -> None:
        root, env = _derived_env(_workspace_env())
        self.assertEqual(root, _MOVED)
        for key, _legs, _note in cache_paths.ENTRIES:
            self.assertTrue(Path(env[key]).is_relative_to(_MOVED), key)

    def test_the_job_container_sees_the_base_at_its_host_path(self) -> None:
        workflow = read_text(str(_WORKSPACE))
        self.assertIn(f"-e {BASE_KEY} \\", workflow)
        self.assertIn(f'-v "${{{BASE_KEY}}}:${{{BASE_KEY}}}" \\', workflow)

    def test_legs_moved_without_their_base_are_refused(self) -> None:
        legs = {
            "INFINITO_CACHE_PACKAGE_HOST_PATH": f"{_MOVED}/package/data",
            "INFINITO_CACHE_REGISTRY_HOST_PATH": f"{_MOVED}/registry/mirror",
            "INFINITO_CACHE_REGISTRY_CA_HOST_PATH": f"{_MOVED}/registry/ca",
            PIN_ROOT_KEY: f"{_MOVED}/pin",
        }
        root, env = _derived_env(legs)
        self.assertEqual(len(unmounted(root, Path(legs[PIN_ROOT_KEY]), env)), 3)

    def test_a_stamp_dir_the_runner_cannot_see_is_refused(self) -> None:
        pins = f"{_MOVED}/pin"
        stamps = f"{cache_paths.machine()}/tools"
        exported = {BASE_KEY: str(_MOVED), STAMP_DIR_KEY: stamps, PIN_ROOT_KEY: pins}
        root, env = _derived_env(exported)
        [line] = unmounted(root, Path(pins), env)
        self.assertIn(f"{STAMP_DIR_KEY}={stamps}", line)


def _paths(node: object) -> list[str]:
    """Args:
        node: a parsed YAML value.

    Returns:
        Every absolute path string anywhere inside it.
    """
    if isinstance(node, dict):
        return [path for value in node.values() for path in _paths(value)]
    if isinstance(node, list):
        return [path for value in node for path in _paths(value)]
    return [node] if isinstance(node, str) and node.startswith("/") else []


class TestToolsLaneFollowsTheBase(unittest.TestCase):
    def _rendered(self, exported: dict[str, str]) -> dict:
        """Args:
            exported: what the .env the runner starts with sets; the render
                process itself exports nothing, as outside make.

        Returns:
            The rendered tools host vars.
        """
        _root, env = _derived_env(exported)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / tools_vars.TEMPLATE
            template.parent.mkdir(parents=True)
            shutil.copyfile(PROJECT_ROOT / tools_vars.TEMPLATE, template)
            blank = dict.fromkeys((BASE_KEY, MODELS_KEY), "")
            with patch.dict(os.environ, blank):
                return load_yaml(tools_vars.render(root, ["en"], env))

    def test_the_cache_base_and_the_model_store_follow_the_moved_base(self) -> None:
        rendered = self._rendered({BASE_KEY: str(_MOVED)})
        self.assertEqual(
            [rendered["DIR_CACHE"], rendered["AI_MODELS_STORE_PATH"]],
            [str(_MOVED), str(_MOVED / "models")],
        )

    def test_every_path_the_tools_lane_binds_lies_below_the_moved_base(self) -> None:
        rendered = self._rendered({BASE_KEY: str(_MOVED)})
        self.assertEqual(
            [
                path
                for path in _paths(rendered)
                if not Path(path).is_relative_to(_MOVED)
            ],
            [],
        )

    def test_the_model_store_is_the_models_directory_the_guard_checks(self) -> None:
        rendered = self._rendered(
            {BASE_KEY: str(_MOVED), MODELS_KEY: f"{_MOVED}/elsewhere"}
        )
        self.assertEqual(rendered["AI_MODELS_STORE_PATH"], f"{_MOVED}/elsewhere")

    def test_no_service_pins_a_models_directory_beside_the_store(self) -> None:
        rendered = self._rendered({BASE_KEY: str(_MOVED)})
        self.assertEqual(
            [path for path in _paths(rendered["applications"]) if "models" in path],
            [],
        )

    def test_a_render_without_the_runner_environment_fails_loudly(self) -> None:
        with self.assertRaises(KeyError):
            tools_vars.render(PROJECT_ROOT, ["en"], {})


class TestEveryCacheConsumerDerivesFromTheBase(unittest.TestCase):
    _SCANNED = ("roles/", "group_vars/", "inventories/", "compose/")
    _SUFFIXES = (".yml", ".yaml", ".j2")
    _OWNER = "group_vars/all/05_paths.yml"

    def test_no_role_or_inventory_copies_the_cache_base(self) -> None:
        spot = str(cache_paths.machine())
        copies = [
            rel
            for rel in repository_files()
            if rel.startswith(self._SCANNED)
            and rel.endswith(self._SUFFIXES)
            and rel != self._OWNER
            and spot in read_text(str(PROJECT_ROOT / rel))
        ]
        self.assertEqual(copies, [])


class TestTheLockStaysMachineWide(unittest.TestCase):
    _GUARDED = (
        MODELS_KEY,
        STAMP_DIR_KEY,
        _CONF,
        *(key for key, _legs, _note in cache_paths.ENTRIES),
    )

    def _moved(self) -> dict[str, str]:
        return {
            **dict.fromkeys(self._GUARDED, ""),
            BASE_KEY: str(_MOVED),
            PIN_ROOT_KEY: f"{_MOVED}/pin",
        }

    def test_a_moved_base_keeps_the_lock_and_the_marker_in_the_machine_place(
        self,
    ) -> None:
        seen: dict[str, object] = {}

        def record(_argv: list[str], **kwargs: object) -> int:
            seen.update(kwargs)
            return 0

        with (
            patch.dict(os.environ, self._moved()),
            patch.object(cli, "up", side_effect=record),
            patch.object(cli, "run_command", return_value=""),
        ):
            cli._up(
                [],
                Path("/srv/core"),
                print,
                recreate=False,
                takeover=False,
                bridge=None,
            )
        self.assertEqual(seen["lock"], cache_paths.machine() / LOCK_NAME)

    def test_a_moved_base_stops_the_runner_under_the_same_lock(self) -> None:
        seen: list[Path] = []
        with (
            patch.dict(os.environ, self._moved()),
            patch.object(cli, "_prepare", return_value=([], Path("/srv/core"))),
            patch.object(
                cli, "down", side_effect=lambda _c, _r, lock: seen.append(lock) or 0
            ),
        ):
            cli.main(["down"])
        self.assertEqual(seen, [cache_paths.machine() / LOCK_NAME])

    def test_a_moved_base_reads_the_bridge_record_from_the_machine_place(
        self,
    ) -> None:
        seen: list[Path] = []
        with (
            patch.dict(os.environ, {**self._moved(), "INFINITO_IMAGE": "image"}),
            patch.object(cli, "_resolved", return_value=str(PROJECT_ROOT)),
            patch.object(cli, "worktree_roots", return_value=[PROJECT_ROOT]),
            patch.object(cli, "write_mounts_override", return_value="roots.yml"),
            patch.object(cli, "read_bridge", side_effect=seen.append),
            patch.object(cli, "infra_compose_argv", return_value=[]),
        ):
            cli._prepare(None)
        self.assertEqual(seen, [cache_paths.machine() / BRIDGE_NAME])

    def test_a_runner_on_another_base_is_compared_by_its_mounts(self) -> None:
        other = str(cache_paths.machine())
        mounts = f'[{{"Type": "bind", "Source": "{other}", "Destination": "{other}"}}]'
        runner = {"INFINITO_INFRA_RUNNER_CONTAINER": "infinito-infra-runner"}
        with (
            patch.dict(os.environ, {**self._moved(), **runner}),
            patch.object(cli, "_running", return_value=True),
            patch.object(cli, "run_command", return_value=mounts),
        ):
            [line] = cli._foreign()
        self.assertIn(other, line)
        self.assertIn(str(_MOVED), line)


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


_PREPARE = "python3 -m cli.meta.cache.base"


class TestTheBaseIsPreparedBeforeTheDaemonBindsIt(unittest.TestCase):
    def test_the_workspace_job_prepares_the_base_before_mounting_it(self) -> None:
        workflow = read_text(str(_WORKSPACE))
        mount = workflow.find(f'-v "${{{BASE_KEY}}}:${{{BASE_KEY}}}"')
        self.assertLess(-1, workflow.find(_PREPARE))
        self.assertLess(workflow.find(_PREPARE), mount)

    def test_the_preparation_creates_the_base_or_refuses_with_status_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            moved = Path(tmp) / "mnt" / "cache"
            with patch.dict(os.environ, {BASE_KEY: str(moved)}):
                created = base_cli.main()
                with (
                    patch("sys.stderr"),
                    patch.object(base_cli, "prepare_base", return_value=["no"]),
                ):
                    refused = base_cli.main()
            self.assertEqual([created, refused, moved.is_dir()], [0, 2, True])


_DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${DOCKER_LOG}"
case " $* " in *" up --detach --wait "*) exit 97 ;; esac
exit 0
"""
_RUNNER_START = 97
_GIB = 1024**3
_CI_FREE = 117 * _GIB


def _dotenv_budget() -> dict[str, str]:
    """Returns:
    The cache caps, the idle window and the disk floor ``make dotenv`` copies
    from default.env.
    """
    static = parse_static_env(PROJECT_ROOT / "default.env")
    keys = (*(spec.cap_key for spec in CACHES), IDLE_KEY, FLOOR_KEY)
    return {key: static[key] for key in keys}


class TestTheWorkspaceJobReachesTheRunnerStart(unittest.TestCase):
    def _attach(
        self, exported: dict[str, str], disk: Path, free: int
    ) -> tuple[int, list[str], str]:
        """Args:
            exported: the INFINITO_* variables the job passes into its
                container, whose ``make dotenv`` derives the rest.
            disk: stands in for the host filesystem; ``/mnt/cache``, the
                machine place and the generated roots override move below it.
            free: the free bytes the disk floor check measures.

        Returns:
            The exit status of ``python -m cli.administration.infra attach``,
            which ``make install-lint`` reaches through the test runner, every
            docker call it made, and its stderr. Only docker is stubbed; it
            fails the runner start with status 97.
        """
        moved = str(disk / "mnt" / "cache")
        job = {
            key: value.replace(str(_MOVED), moved) for key, value in exported.items()
        }
        _root, env = _derived_env(job)
        docker = disk / "bin" / "docker"
        docker.parent.mkdir()
        docker.write_text(_DOCKER_STUB)
        docker.chmod(0o755)
        log = disk / "docker.log"
        log.touch()
        runner = {
            **_dotenv_budget(),
            **env,
            "INFINITO_CACHE_STACK": "true",
            "GITHUB_ACTIONS": "true",
            "INFINITO_IMAGE": "infinito-nexus-core/debian:ci",
            "INFINITO_GPU_COUNT": "0",
            ROOTS_KEY: "",
            RUNNER_CONTAINER_KEY: "infra-runner",
            "DOCKER_LOG": str(log),
            "PATH": f"{docker.parent}{os.pathsep}{os.environ['PATH']}",
        }
        with (
            tempfile.TemporaryFile("w+") as stderr,
            patch.dict(os.environ, runner),
            patch.object(cli, "machine", return_value=disk / "var" / "cache"),
            patch.object(
                cli,
                "write_mounts_override",
                side_effect=lambda _root, *args, **kwargs: write_mounts_override(
                    disk, *args, **kwargs
                ),
            ),
            patch("utils.infra.free_bytes", return_value=free),
            patch("sys.stderr", stderr),
        ):
            try:
                code = cli.main(["attach"])
            except subprocess.CalledProcessError as exc:
                code = exc.returncode
            stderr.seek(0)
            return code, log.read_text().splitlines(), stderr.read()

    def test_the_failing_job_now_passes_every_gate_up_to_the_runner_start(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp)
            code, calls, _err = self._attach(_workspace_env(), disk, _CI_FREE)
            marked = (disk / "var" / "cache" / OWNER_NAME).is_file()
            prepared = (disk / "mnt" / "cache").is_dir()
        self.assertEqual(
            [code, calls[-1].split()[-3:], marked, prepared],
            [_RUNNER_START, ["up", "--detach", "--wait"], True, True],
        )
        self.assertIn("system df --format {{json .}}", calls)

    def test_a_disk_below_the_workspace_caps_and_floor_starts_nothing(self) -> None:
        budget = {**_dotenv_budget(), **_workspace_env()}
        needed = sum(parse_size(budget[spec.cap_key]) for spec in CACHES)
        needed += parse_size(budget[FLOOR_KEY])
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp)
            code, calls, err = self._attach(_workspace_env(), disk, needed - _GIB)
            prepared = (disk / "mnt" / "cache").exists()
        self.assertEqual([code, prepared, needed], [2, False, 99 * _GIB])
        self.assertFalse([call for call in calls if " up " in f" {call} "])
        self.assertIn(FLOOR_KEY, err)

    def test_the_old_leg_pins_stop_the_job_where_the_ci_log_does(self) -> None:
        legs = {
            "INFINITO_CACHE_PACKAGE_HOST_PATH": f"{_MOVED}/package/data",
            "INFINITO_CACHE_REGISTRY_HOST_PATH": f"{_MOVED}/registry/mirror",
            "INFINITO_CACHE_REGISTRY_CA_HOST_PATH": f"{_MOVED}/registry/ca",
            PIN_ROOT_KEY: f"{_MOVED}/pin",
        }
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp)
            with (
                patch.object(cache_paths, "machine", return_value=disk / "var"),
                self.assertRaises(SystemExit) as stopped,
            ):
                self._attach(legs, disk, _CI_FREE)
        self.assertEqual(str(stopped.exception).count("lies outside"), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
