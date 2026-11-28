import unittest
import unittest.mock as mock

from cli.meta.ci.host_rows import round_variants
from utils import PROJECT_ROOT
from utils.storage import constrained
from utils.storage.constrained import (
    STORE_ROLE,
    host_storage_constrained,
    is_constrained,
    model_store_bytes,
    required_storage_bytes,
    shared_disk_storage_bytes,
    store_consumers,
)
from utils.tests.swarm.extend_inventory import SWARM_NODES

_GIB = 1024**3
_MIB = 1024**2
_N8N = "web-app-n8n"
_N8N_0_WALKED = int(79.22 * _GIB)
_STORE = 7023309299
_N8N_0_FREE = 88673 * _MIB


def _n8n_0_constrained(*, store_nodes: int) -> bool:
    with (
        mock.patch.object(
            constrained, "required_storage_bytes", return_value=_N8N_0_WALKED + _STORE
        ),
        mock.patch.object(constrained, "model_store_bytes", return_value=_STORE),
        mock.patch.object(
            constrained, "docker_root_free_bytes", return_value=_N8N_0_FREE
        ),
    ):
        return host_storage_constrained(
            [_N8N], {}, local_vantage="/", store_nodes=store_nodes
        )


class TestStoreConsumers(unittest.TestCase):
    def test_the_engines_that_include_the_store_consume_it(self) -> None:
        consumers = store_consumers(PROJECT_ROOT / "roles")
        for role in ("svc-ai-ollama", "svc-ai-s1", "web-app-openwebui"):
            with self.subTest(role=role):
                self.assertIn(role, consumers)

    def test_the_store_role_is_no_consumer_of_itself(self) -> None:
        self.assertNotIn(STORE_ROLE, store_consumers(PROJECT_ROOT / "roles"))


class TestModelStoreBytes(unittest.TestCase):
    def test_n8n_0_seeds_the_store_its_engines_read(self) -> None:
        self.assertEqual(
            model_store_bytes([_N8N], round_variants(_N8N, 0)),
            model_store_bytes(["svc-ai-ollama"], None),
        )
        self.assertGreater(model_store_bytes(["svc-ai-ollama"], None), 0)

    def test_n8n_1_reads_no_store(self) -> None:
        self.assertEqual(model_store_bytes([_N8N], round_variants(_N8N, 1)), 0)

    def test_a_walked_store_role_is_not_counted_twice(self) -> None:
        self.assertEqual(model_store_bytes([STORE_ROLE], None), 0)

    def test_the_host_need_counts_the_store_once(self) -> None:
        with mock.patch.object(constrained, "_store_bytes", return_value=0):
            unstored = required_storage_bytes(["svc-ai-ollama"])
        self.assertEqual(
            required_storage_bytes(["svc-ai-ollama"]),
            unstored + model_store_bytes(["svc-ai-ollama"], None),
        )


class TestSharedDiskBudget(unittest.TestCase):
    def test_every_store_node_beyond_the_first_adds_one_store(self) -> None:
        with (
            mock.patch.object(constrained, "required_storage_bytes", return_value=10),
            mock.patch.object(constrained, "model_store_bytes", return_value=3),
        ):
            self.assertEqual(
                [
                    shared_disk_storage_bytes([_N8N], {}, store_nodes=nodes)
                    for nodes in (1, 2, 3)
                ],
                [10, 13, 16],
            )

    def test_the_lab_seeds_every_swarm_node_on_one_disk(self) -> None:
        self.assertEqual(len(SWARM_NODES), 3)

    def test_n8n_0_on_the_lab_disk_is_constrained(self) -> None:
        self.assertTrue(_n8n_0_constrained(store_nodes=len(SWARM_NODES)))

    def test_n8n_0_on_a_disk_of_its_own_fits(self) -> None:
        self.assertFalse(_n8n_0_constrained(store_nodes=1))

    def test_the_old_walk_left_n8n_0_unconstrained(self) -> None:
        self.assertFalse(
            is_constrained(free_bytes=_N8N_0_FREE, required_bytes=_N8N_0_WALKED)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
