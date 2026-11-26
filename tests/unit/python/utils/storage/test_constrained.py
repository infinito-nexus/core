import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

from plugins.filter.libretranslate_store import (
    ENGINE,
    SELECTION_KEYS,
    libretranslate_selection,
    libretranslate_unselected,
)
from utils import PROJECT_ROOT
from utils.cache.artefacts import records
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.applications.services.registry import (
    load_applications_from_roles_dir,
)
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)
from utils.storage import constrained
from utils.storage.constrained import (
    StorageDeclarationError,
    closure_storage,
    is_constrained,
    required_storage_bytes,
)

_GIB = 1024**3
_GB = 10**9
_USAGE = SimpleNamespace(free=123 * _GIB)
_ENGINE = "svc-ai-libretranslate-engine"
_WEB = "web-svc-libretranslate"
_EVERY_PAIR = {"directions": "both", "load_only": [], "model_store": True}
_EN_DE = {"directions": "both", "load_only": ["en", "de"], "model_store": True}
_EN_DE_FR_OUT = {
    "directions": "from_source",
    "load_only": ["en", "de", "fr"],
    "model_store": True,
}

_ROLES = {
    "svc-db-store": "store:\n  enabled: true\n  shared: true\n  min_storage: 5GB\n",
    "web-app-shop": (
        "shop:\n  enabled: true\n  min_storage: 1GB\n"
        "cache:\n  enabled: true\n  mem_limit: 1g\n  min_storage: 3GB\n"
        "store:\n  enabled: true\n  shared: true\n"
    ),
    "web-app-odd": "odd:\n  enabled: true\n  min_storage: plenty\n",
}
_SHOP_VARIANTS = "- {}\n- services:\n    cache:\n      enabled: false\n"


def _engine_records() -> list[dict]:
    return [record for record in records("").values() if record["role"] == _ENGINE]


def _chosen(*pairs: str) -> list[dict]:
    prefixes = tuple(f"translate-{pair}-" for pair in pairs)
    return [
        record
        for record in _engine_records()
        if not record["unpack"]
        or not pairs
        or record["upstream"].rsplit("/", 1)[-1].startswith(prefixes)
    ]


def _with_argos(package: str, role: str = _ENGINE) -> dict[str, dict]:
    extra = {
        "name": "argos-extra",
        "upstream": f"https://argos-net.com/v1/{package}",
        "unpack": "argos-packages/extra",
        "root": "",
        "role": role,
    }
    return {**records(""), extra["name"]: extra}


def _of(*services: object) -> list[tuple[str, object]]:
    return [(_ENGINE, service) for service in services]


def _bytes(chosen: list[dict]) -> int:
    return sum(
        {
            record["sha256"]: record["bytes"] + record["unpacked_bytes"]
            for record in chosen
        }.values()
    )


class TestClosureStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        roles_dir = Path(self._tmp.name) / "roles"
        for role, services in _ROLES.items():
            (roles_dir / role / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True)
            (roles_dir / role / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True)
            (roles_dir / role / ROLE_FILE_VARS_MAIN).write_text(
                f"application_id: {role}\n", encoding="utf-8"
            )
            (roles_dir / role / ROLE_FILE_META_SERVICES).write_text(
                services, encoding="utf-8"
            )
        (roles_dir / "web-app-shop" / ROLE_FILE_META_VARIANTS).write_text(
            _SHOP_VARIANTS, encoding="utf-8"
        )
        self.measure = closure_storage(roles_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_an_unlisted_provider_is_not_walked(self) -> None:
        self.assertEqual(self.measure(["web-app-shop"], {}), {"web-app-shop": 4 * _GB})

    def test_a_listed_provider_counts_once_on_its_own(self) -> None:
        self.assertEqual(
            self.measure(["web-app-shop", "svc-db-store"], {}),
            {"web-app-shop": 4 * _GB, "svc-db-store": 5 * _GB},
        )

    def test_the_round_variant_drops_a_sidecar_it_switches_off(self) -> None:
        self.assertEqual(
            self.measure(["web-app-shop"], {"web-app-shop": 1}),
            {"web-app-shop": 1 * _GB},
        )

    def test_a_role_without_application_config_declares_nothing(self) -> None:
        self.assertEqual(
            self.measure(["svc-swarm-absent"], {}), {"svc-swarm-absent": 0}
        )

    def test_an_unparsable_declaration_is_refused_by_name(self) -> None:
        with self.assertRaisesRegex(
            StorageDeclarationError, r"web-app-odd: .*odd='plenty'"
        ):
            self.measure(["web-app-shop", "web-app-odd"], {})


def _write_selecting_roles(roles_dir: Path) -> None:
    for role, entity, size in (
        ("svc-ai-alpha", "alpha", "1GB"),
        ("web-svc-beta", "beta", "2GB"),
    ):
        (roles_dir / role / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True)
        (roles_dir / role / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True)
        (roles_dir / role / ROLE_FILE_VARS_MAIN).write_text(
            f"application_id: {role}\n", encoding="utf-8"
        )
        (roles_dir / role / ROLE_FILE_META_SERVICES).write_text(
            f"{entity}:\n  enabled: true\n  cpus: 1\n  min_storage: {size}\n"
            "  directions: both\n  load_only: [en, de]\n  model_store: true\n",
            encoding="utf-8",
        )


class TestClosureSelection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        roles_dir = Path(self._tmp.name) / "roles"
        _write_selecting_roles(roles_dir)
        self.measure = closure_storage(roles_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_first_role_seeding_a_digest_carries_it_once(self) -> None:
        en_de = constrained.selection_storage_bytes(_of(_EN_DE))
        self.assertGreater(en_de, 0)
        self.assertEqual(
            self.measure(["svc-ai-alpha", "web-svc-beta"], {}),
            {"svc-ai-alpha": 1 * _GB + en_de, "web-svc-beta": 2 * _GB},
        )


class TestDockerDataRoot(unittest.TestCase):
    def test_a_daemon_that_does_not_answer_fails_closed(self) -> None:
        with (
            mock.patch.object(
                constrained.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=1),
            ),
            self.assertRaisesRegex(RuntimeError, "did not answer"),
        ):
            constrained.docker_data_root()

    def test_docker_info_runs_under_a_timeout(self) -> None:
        done = SimpleNamespace(returncode=0, stdout="/var/lib/docker\n", stderr="")
        with mock.patch.object(constrained.subprocess, "run", return_value=done) as run:
            constrained.docker_data_root()
        self.assertEqual(
            run.call_args.kwargs["timeout"], constrained.DOCKER_INFO_TIMEOUT_S
        )


class TestResolvedDockerRootFreeBytes(unittest.TestCase):
    def test_a_resolvable_root_is_measured(self) -> None:
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/"),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(constrained.resolved_docker_root_free_bytes(), _USAGE.free)
        usage.assert_called_once_with("/")

    def test_a_root_that_does_not_resolve_here_is_refused(self) -> None:
        with (
            mock.patch.object(
                constrained, "docker_data_root", return_value="/var/lib/docker-absent"
            ),
            self.assertRaisesRegex(RuntimeError, "docker-absent"),
        ):
            constrained.resolved_docker_root_free_bytes()

    def test_an_unreachable_parent_is_refused(self) -> None:
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/x"),
            mock.patch.object(
                constrained.shutil,
                "disk_usage",
                side_effect=PermissionError("denied"),
            ),
            self.assertRaisesRegex(RuntimeError, "denied"),
        ):
            constrained.resolved_docker_root_free_bytes()


class TestIsConstrained(unittest.TestCase):
    def test_need_above_free_is_constrained(self):
        self.assertTrue(
            is_constrained(free_bytes=122 * _GIB, required_bytes=381 * _GIB)
        )

    def test_need_equal_to_free_fits(self):
        self.assertFalse(
            is_constrained(free_bytes=100 * _GIB, required_bytes=100 * _GIB)
        )

    def test_need_below_free_fits(self):
        self.assertFalse(
            is_constrained(free_bytes=300 * _GIB, required_bytes=113 * _GIB)
        )

    def test_undeclared_need_never_constrains(self):
        self.assertFalse(is_constrained(free_bytes=1, required_bytes=0))


class TestRequiredStorageBytes(unittest.TestCase):
    def test_unknown_role_declares_nothing(self):
        self.assertEqual(required_storage_bytes(["web-app-does-not-exist"]), 0)

    def test_empty_selection_declares_nothing(self):
        self.assertEqual(required_storage_bytes([]), 0)

    def test_a_real_role_declares_a_positive_need(self):
        self.assertGreater(required_storage_bytes(["svc-db-mariadb"]), 0)

    def test_dependencies_are_counted_once_across_apps(self):
        single = required_storage_bytes(["svc-db-mariadb"])
        twice = required_storage_bytes(["svc-db-mariadb", "svc-db-mariadb"])
        self.assertEqual(single, twice)


class TestLibretranslateSelection(unittest.TestCase):
    def test_the_round_sum_counts_what_load_only_selects(self) -> None:
        every_pair = required_storage_bytes([_ENGINE])
        en_de = required_storage_bytes([_ENGINE], {_ENGINE: 0})
        self.assertEqual(
            every_pair - en_de, _bytes(_chosen()) - _bytes(_chosen("en_de", "de_en"))
        )

    def test_two_consumers_selecting_one_digest_count_it_once(self) -> None:
        en_de = _bytes(_chosen("en_de", "de_en"))
        with tempfile.TemporaryDirectory() as tmp:
            _write_selecting_roles(Path(tmp) / "roles")
            with mock.patch.object(constrained, "PROJECT_ROOT", Path(tmp)):
                alone = required_storage_bytes(["svc-ai-alpha"])
                both = required_storage_bytes(["svc-ai-alpha", "web-svc-beta"])
        self.assertGreater(en_de, 0)
        self.assertEqual(alone, 1 * _GB + en_de)
        self.assertEqual(both, 3 * _GB + en_de)

    def test_a_full_selection_counts_every_pinned_record(self) -> None:
        self.assertEqual(len(_chosen()), 180)
        full = constrained.selection_storage_bytes(_of(_EVERY_PAIR))
        self.assertEqual(full, _bytes(_chosen()))
        self.assertGreater(full, 18 * _GB)

    def test_en_de_counts_its_two_packages_and_minisbd(self) -> None:
        chosen = _chosen("en_de", "de_en")
        self.assertEqual(len([record for record in chosen if record["unpack"]]), 2)
        self.assertEqual(len(chosen), 84)
        self.assertEqual(
            constrained.selection_storage_bytes(_of(_EN_DE)), _bytes(chosen)
        )

    def test_a_digest_selected_twice_counts_once(self) -> None:
        self.assertEqual(
            constrained.selection_storage_bytes(
                [(_ENGINE, _EN_DE), (_WEB, dict(_EN_DE))]
            ),
            _bytes(_chosen("en_de", "de_en")),
        )
        self.assertEqual(
            constrained.selection_storage_bytes(_of(_EN_DE, _EN_DE_FR_OUT)),
            _bytes(_chosen("en_de", "de_en", "en_fr")),
        )

    def test_an_unseeded_selection_or_a_plain_service_adds_nothing(self) -> None:
        for service in (
            {**_EN_DE, "model_store": False},
            {**_EN_DE, "directions": "from_source"},
            {"min_storage": "1GB"},
            None,
            "libretranslate",
        ):
            with self.subTest(service=service):
                self.assertEqual(constrained.selection_storage_bytes(_of(service)), 0)

    def test_the_store_floor_and_a_selection_share_no_digest(self) -> None:
        pinned = list(records("").values())
        floor = {record["sha256"] for record in libretranslate_unselected(pinned)}
        selected = libretranslate_selection(pinned, _EVERY_PAIR)
        self.assertEqual(len(selected), 180)
        self.assertFalse(floor & {record["sha256"] for record in selected})

    def test_the_consumers_are_the_roles_that_seed_a_selection(self) -> None:
        roles_dir = Path(PROJECT_ROOT) / "roles"
        applications = load_applications_from_roles_dir(roles_dir)
        declaring = {
            role
            for role, config in applications.items()
            for service in (config.get("services") or {}).values()
            if isinstance(service, dict)
            and all(key in service for key in SELECTION_KEYS)
        }
        seeding = {
            role
            for role in applications
            if (roles_dir / role / ROLE_FILE_VARS_MAIN).is_file()
            and "libretranslate_store("
            in read_text(str(roles_dir / role / ROLE_FILE_VARS_MAIN))
        }
        self.assertEqual(declaring, seeding)
        self.assertEqual(declaring, {_ENGINE})

    def test_a_broken_pin_is_refused_only_when_a_consumer_runs(self) -> None:
        broken = ValueError("svc-ai-x/model: broken pin")
        with mock.patch.object(constrained, "records", side_effect=broken):
            self.assertEqual(
                constrained.selection_storage_bytes(_of({"min_storage": "1GB"})), 0
            )
            with self.assertRaisesRegex(
                StorageDeclarationError, f"^{_WEB}: .*svc-ai-x/model: broken pin"
            ):
                constrained.selection_storage_bytes([(_WEB, _EN_DE)])

    def test_a_model_store_that_is_no_boolean_is_refused_by_role(self) -> None:
        with self.assertRaisesRegex(
            StorageDeclarationError, f"^{_WEB}: .*model_store 'false' is no boolean"
        ):
            constrained.selection_storage_bytes(
                [(_WEB, {**_EN_DE, "model_store": "false"})]
            )

    def test_a_load_only_that_is_no_list_is_refused_by_role(self) -> None:
        with self.assertRaisesRegex(
            StorageDeclarationError, f"^{_WEB}: .*load_only 'en,de' is no list"
        ):
            constrained.selection_storage_bytes(
                [(_WEB, {**_EN_DE, "load_only": "en,de"})]
            )

    def test_an_argos_record_without_a_pair_is_refused_by_role_and_name(
        self,
    ) -> None:
        for package in ("unpaired.argosmodel", "foo-en_de-1_0.argosmodel"):
            with (
                self.subTest(package=package),
                mock.patch.object(
                    constrained, "records", return_value=_with_argos(package)
                ),
                self.assertRaisesRegex(
                    StorageDeclarationError,
                    f"^{_ENGINE}: .*argos-extra: {package} is no translate-",
                ),
            ):
                constrained.selection_storage_bytes(_of(_EVERY_PAIR))

    def test_only_the_engine_records_are_selected(self) -> None:
        foreign = _with_argos("translate-en_zz-1_0.argosmodel", role=_WEB)
        with mock.patch.object(constrained, "records", return_value=foreign):
            self.assertEqual(
                constrained.selection_storage_bytes(_of(_EVERY_PAIR)),
                _bytes(_chosen()),
            )

    def test_the_engine_hands_its_selection_its_own_records(self) -> None:
        variables = load_yaml(
            str(Path(PROJECT_ROOT) / "roles" / _ENGINE / ROLE_FILE_VARS_MAIN)
        )
        self.assertEqual(variables["application_id"], ENGINE)
        self.assertTrue(
            any(
                "lookup('cache_artefacts', application_id)" in str(value)
                for value in variables.values()
            )
        )


class TestDockerRootFreeBytes(unittest.TestCase):
    """The daemon reports its data root in ITS namespace, which need not be ours.

    A caller running inside a container of that daemon sees a path that does not
    resolve, which used to raise FileNotFoundError out of shutil.disk_usage and
    abort the nested swarm drill of every workspace job.
    """

    def test_resolvable_root_is_measured_directly(self):
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/"),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(
                constrained.docker_root_free_bytes(local_vantage="/nonexistent"),
                _USAGE.free,
            )
        usage.assert_called_once_with("/")

    def test_unresolvable_root_falls_to_the_local_vantage(self):
        with (
            mock.patch.object(
                constrained, "docker_data_root", return_value="/var/lib/docker-absent"
            ),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(
                constrained.docker_root_free_bytes(local_vantage="/"),
                _USAGE.free,
            )
        usage.assert_called_once_with("/")

    def test_unreachable_daemon_still_raises(self):
        with (
            mock.patch.object(
                constrained, "docker_data_root", side_effect=RuntimeError("no daemon")
            ),
            self.assertRaises(RuntimeError),
        ):
            constrained.docker_root_free_bytes(local_vantage="/")

    def test_local_vantage_has_no_default(self):
        with self.assertRaises(TypeError):
            constrained.docker_root_free_bytes()


if __name__ == "__main__":
    unittest.main()
