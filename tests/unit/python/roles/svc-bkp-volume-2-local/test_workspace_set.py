import copy
import importlib.util
import unittest
from unittest import mock

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

LOOKUPS = PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local" / "lookup_plugins"
WORKSPACE_ROLES = (
    "web-app-semaphore",
    "web-app-keycloak",
    "web-app-openbao",
    "web-svc-seaweedfs",
    "web-app-gitea",
)
ENGINES = ("svc-db-postgres", "svc-db-mariadb")
DUMPED = ("web-app-semaphore", "web-app-keycloak")
VOLUMES = ("web-app-openbao", "web-svc-seaweedfs", "web-app-gitea")
STATE_VOLUME = "data"
STOPPED = ("web-app-openbao", "web-svc-seaweedfs")
RUNNING = ("web-app-gitea", "web-app-semaphore")
COMPOSE = {"DEPLOYMENT_MODE": "compose"}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, LOOKUPS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DATABASES = _load("backup_database_containers")
VOLUME = _load("backup_volume")
IMAGE = _load("backup_image")
STOPS = _load("backup_stop_applications")


def role_applications(roles):
    """
    Args:
        roles: role directories to read.

    Returns:
        Their ``services`` and ``volumes`` keyed by application id, as the
        merged ``applications`` config carries them.
    """
    applications = {}
    for role in roles:
        role_dir = PROJECT_ROOT / "roles" / role
        role_vars = load_yaml_any(str(role_dir / ROLE_FILE_VARS_MAIN))
        applications[role_vars["application_id"]] = {
            "services": load_yaml_any(str(role_dir / ROLE_FILE_META_SERVICES)),
            "volumes": load_yaml_any(str(role_dir / ROLE_FILE_META_VOLUMES)) or {},
        }
    return applications


def run_lookup(module, applications, terms=None, variables=None):
    lookup = module.LookupModule()
    lookup._loader = mock.MagicMock()
    lookup._templar = None
    image = mock.MagicMock(run=lambda term, **_kw: [f"{term[0]}/{term[1]}"])
    listing = mock.MagicMock(run=lambda *_a, **_kw: [applications])
    with mock.patch.object(module, "lookup_loader") as loader:
        loader.get.side_effect = lambda name, **_kw: (
            image if name == "image" else listing
        )
        return lookup.run(terms or [], variables=variables or {})[0]


def missing_from_generation(applications, variables):
    """
    Args:
        applications: the merged config of the stack host's roles.
        variables: the play variables the lookups read.

    Returns:
        Every part of the workspace set one generation would not hold, judged
        by the subjects the role's lookups hand to baudolo.
    """
    dumped = run_lookup(DATABASES, applications)
    skipped_volumes = run_lookup(VOLUME, applications, variables=variables)
    skipped_images = run_lookup(IMAGE, applications, terms=["disabled", True])
    missing = []
    engine = applications["svc-db-postgres"]["services"]["postgres"]
    if engine["name"] not in dumped:
        missing.append("the postgres dump routine")
    for role in DUMPED:
        consumer = applications[role]["services"].get("postgres") or {}
        if consumer.get("enabled") is not True:
            missing.append(f"the {role} database")
    for role in VOLUMES:
        entry = applications[role]["volumes"].get(STATE_VOLUME)
        if not isinstance(entry, dict) or entry.get("type", "volume") != "volume":
            missing.append(f"the state volume of {role}")
            continue
        volume = VOLUME.deployed_volume_name(role, STATE_VOLUME, entry)
        if volume in skipped_volumes:
            missing.append(f"the volume {volume}")
        missing.extend(
            f"the image of {role}/{mount['service']}"
            for mount in entry.get("mounts") or []
            if f"{role}/{mount['service']}" in skipped_images
        )
    return missing


class TestWorkspaceSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.applications = role_applications(WORKSPACE_ROLES + ENGINES)

    def test_one_generation_holds_the_workspace_set(self):
        for variables in (
            COMPOSE,
            {"DEPLOYMENT_MODE": "swarm", "storage": {"backend": "local"}},
        ):
            with self.subTest(variables=variables):
                missing = missing_from_generation(self.applications, variables)
                self.assertEqual(missing, [])

    def test_negative_control_a_volume_declared_disposable_leaves_the_set(self):
        planted = copy.deepcopy(self.applications)
        planted["web-svc-seaweedfs"]["volumes"]["data"]["backup"] = False
        self.assertEqual(
            missing_from_generation(planted, COMPOSE), ["the volume seaweedfs_data"]
        )

    def test_negative_control_a_disabled_image_leaves_the_set(self):
        planted = copy.deepcopy(self.applications)
        planted["web-app-openbao"]["services"]["openbao"]["backup"] = {"disabled": True}
        self.assertEqual(
            missing_from_generation(planted, COMPOSE),
            ["the image of web-app-openbao/openbao"],
        )

    def test_negative_control_a_consumer_without_its_database_leaves_the_set(self):
        planted = copy.deepcopy(self.applications)
        planted["web-app-semaphore"]["services"].pop("postgres")
        self.assertEqual(
            missing_from_generation(planted, COMPOSE),
            ["the web-app-semaphore database"],
        )

    def test_the_signal_names_the_stopped_workspace_services_only(self):
        stops = STOPS.stop_applications(self.applications, list(self.applications))
        for role in STOPPED:
            self.assertIn(role, stops)
        for role in RUNNING:
            self.assertNotIn(role, stops)

    def test_the_signal_lists_only_applications_of_this_host(self):
        self.assertEqual(
            STOPS.stop_applications(self.applications, ["web-app-gitea"]), []
        )

    def test_negative_control_a_stop_required_gitea_joins_the_signal(self):
        planted = copy.deepcopy(self.applications)
        planted["web-app-gitea"]["services"]["gitea"]["backup"] = {
            "stop_required": True
        }
        self.assertIn("web-app-gitea", STOPS.stop_applications(planted, list(planted)))

    def test_the_lookup_reads_group_names(self):
        stops = run_lookup(
            STOPS, self.applications, variables={"group_names": ["web-app-openbao"]}
        )
        self.assertEqual(stops, ["web-app-openbao"])
        with self.assertRaises(STOPS.AnsibleError):
            run_lookup(STOPS, self.applications, variables={})


if __name__ == "__main__":
    unittest.main()
