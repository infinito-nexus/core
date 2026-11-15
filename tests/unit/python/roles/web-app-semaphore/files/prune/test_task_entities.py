from __future__ import annotations

import importlib
import io
import json
import types
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from unittest import mock

fake = importlib.import_module(
    "tests.unit.python.roles.web-app-semaphore.files._semaphore_fake"
)

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
JWT = "auth_jwt_1a2b"
OTHER = "auth_approle_3c4d"
OWN = "own-entity"
WORKSPACES = "Infinito.Nexus Workspaces"
TEMPLATE = "prune task entities"
MAX_AGE = timedelta(hours=4)


def load_prune():
    """Returns:
    The module ``files/python/prune/task_entities.py``.
    """
    spec = spec_from_file_location(
        "prune_task_entities", str(fake.PYTHON_DIR / "prune" / "task_entities.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def entity(entity_id, age, *accessors):
    """Args:
    entity_id: the entity id.
    age: how long before ``NOW`` it was created.
    accessors: the mount accessor of each of its aliases.

    Returns:
        The ``data`` of the entity read.
    """
    return {
        "id": entity_id,
        "creation_time": (NOW - age).strftime("%Y-%m-%dT%H:%M:%S.123456789Z"),
        "aliases": [{"mount_accessor": accessor} for accessor in accessors],
    }


class FakeBao:
    def __init__(self, *entities):
        """Args:
        entities: the entities besides the task's own one.
        """
        self.entities = {e["id"]: e for e in (entity(OWN, MAX_AGE * 9, JWT), *entities)}
        self.deleted = []

    def request(self, method, path, body):
        if path == "auth/token/lookup-self":
            return 200, {"data": {"entity_id": OWN}}
        if path == "identity/entity/id?list=true":
            return 200, {"data": {"keys": sorted(self.entities)}}
        entity_id = path.rsplit("/", 1)[1]
        if method == "DELETE":
            self.deleted.append(entity_id)
            return 204, {}
        return 200, {"data": self.entities[entity_id]}


class TestPruneTaskEntities(unittest.TestCase):
    def setUp(self):
        self.mod = load_prune()

    def prune(self, *entities):
        bao = FakeBao(*entities)
        self.pruned = self.mod.run(bao, MAX_AGE, NOW)
        self.assertEqual(self.pruned["deleted"], bao.deleted)
        self.assertEqual(self.pruned["own"], OWN)
        return bao.deleted

    def test_an_old_task_entity_is_deleted_and_the_own_one_never(self):
        old = entity("old", MAX_AGE + timedelta(seconds=1), JWT, JWT)
        self.assertEqual(self.prune(old), ["old"])
        self.assertEqual(self.pruned["kept"], {})

    def test_an_entity_with_any_other_alias_is_never_touched(self):
        mixed = entity("mixed", MAX_AGE * 9, JWT, OTHER)
        foreign = entity("foreign", MAX_AGE * 9, OTHER)
        bare = entity("bare", MAX_AGE * 9)
        self.assertEqual(self.prune(mixed, foreign, bare), [])
        self.assertEqual(self.pruned["kept"], {})

    def test_a_task_entity_younger_than_the_longest_ttl_is_kept(self):
        self.assertEqual(self.prune(entity("young", MAX_AGE, JWT)), [])
        self.assertEqual(self.pruned["kept"], {"young": NOW})

    def test_the_task_reports_its_clock_its_own_entity_and_every_kept_one(self):
        bao = FakeBao(entity("young", timedelta(hours=1), JWT))
        client = types.SimpleNamespace(OpenBaoError=RuntimeError, login=lambda env: bao)
        stdout = io.StringIO()
        with (
            mock.patch.object(self.mod.importlib, "import_module", lambda _: client),
            redirect_stdout(stdout),
        ):
            code = self.mod.main(
                [], {"INFINITO_SRC_DIR": ".", "BAO_JWT_TOKEN_TTLS": '{"a": "4h"}'}, NOW
            )
        until = (NOW + timedelta(hours=3)).isoformat()
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                f"prune task entities: at {NOW.isoformat()}",
                f"prune task entities: own {OWN}",
                f"prune task entities: kept young until {until}",
            ],
        )

    def test_negative_control_without_the_alias_check_a_mixed_entity_goes(self):
        mixed = entity("mixed", MAX_AGE * 9, JWT, OTHER)
        with mock.patch.object(
            self.mod, "prunable", lambda e, a, m, n: n - self.mod.created(e) > m
        ):
            self.assertEqual(self.prune(mixed), ["mixed"])

    def test_the_age_bound_is_the_longest_ttl(self):
        ttls = json.loads('{"deploy": "4h", "provision": "240m", "export": "1h"}')
        self.assertEqual(self.mod.longest_ttl(ttls.values()), MAX_AGE)
        with self.assertRaisesRegex(self.mod.PruneRefusedError, "no duration"):
            self.mod.longest_ttl(["4 hours"])
        with self.assertRaisesRegex(self.mod.PruneRefusedError, "no task token ttl"):
            self.mod.longest_ttl([])


class TestTheTaskEntitiesTemplate(unittest.TestCase):
    def setUp(self):
        self.mod = fake.load_project()
        self.api = fake.FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, fake.platform_spec(), lambda seconds: None)
        self.project_id = self.api.project_id(WORKSPACES)
        self.template = self.api.templates(self.project_id)[TEMPLATE]

    def test_the_scheduled_template_runs_the_prune_script(self):
        self.assertEqual(self.template["playbook"], "task-entities.sh")
        self.assertEqual(self.template["survey_vars"], [])
        self.assertEqual(
            [
                s["cron_format"]
                for s in self.api.schedules(self.project_id)
                if s["template_id"] == self.template["id"]
            ],
            ["30 5 * * *"],
        )
        self.assertEqual(self.mod.lock_findings(self.template), [])

    def test_the_identity_reader_names_the_template(self):
        stdout = io.StringIO()
        spec = {
            "url": "http://semaphore",
            "token": "t",
            "workspaces": {"project": WORKSPACES},
        }
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
        ):
            code = self.mod.main(
                [self.mod.TASK_ENTITIES_COMMAND],
                io.StringIO(json.dumps(spec)),
                None,
                lambda s: None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"project_id": self.project_id, "template_id": self.template["id"]},
        )


if __name__ == "__main__":
    unittest.main()
