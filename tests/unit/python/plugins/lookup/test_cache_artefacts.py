from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleLookupError

from plugins.lookup.cache_artefacts import LookupModule

HUB = "huggingface.co"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
URL_A = f"https://{HUB}/org/repo/resolve/{COMMIT}/a.gguf"
URL_B = f"https://{HUB}/org/repo/resolve/{COMMIT}/b.gguf"
BASE = "http://cache.test"

SERVING_ROLE = f"""\
cache:
  repos:
    raw-huggingface:
      flavor: raw
      upstream: https://{HUB}/
  hosts:
    {HUB}:
      repo: raw-huggingface
"""


def _block(name: str, url: str, revision: str, sha256: str) -> str:
    return (
        "cache:\n"
        "  artefacts:\n"
        f"    {name}:\n"
        f"      url: {url}\n"
        f'      revision: "{revision}"\n'
        f'      sha256: "{sha256}"\n'
        '      bytes: "42"\n'
    )


class TestCacheArtefactsLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.roles = Path(self._tmp.name) / "roles"
        self._role("svc-cache-test", SERVING_ROLE)
        self._role("svc-models-a", _block("model-a", URL_A, COMMIT, DIGEST_A))
        self._role("svc-models-b", _block("model-b", URL_B, COMMIT, DIGEST_B))
        patcher = patch("utils.cache.hosts.ROLES_DIR", self.roles)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _role(self, name: str, networks: str) -> None:
        meta = self.roles / name / "meta"
        meta.mkdir(parents=True)
        (meta / "networks.yml").write_text(networks, encoding="utf-8")

    def test_returns_every_record_keyed_by_name(self) -> None:
        [found] = LookupModule().run([])
        self.assertEqual(sorted(found), ["model-a", "model-b"])
        self.assertEqual(found["model-a"]["sha256"], DIGEST_A)
        self.assertEqual(found["model-a"]["bytes"], 42)

    def test_narrows_to_the_roles_named_as_terms(self) -> None:
        [found] = LookupModule().run(["svc-models-b"])
        self.assertEqual(list(found), ["model-b"])

    def test_rewrites_url_under_the_base_and_keeps_upstream(self) -> None:
        [found] = LookupModule().run(["svc-models-a"], base=BASE)
        record = found["model-a"]
        self.assertEqual(
            [record["url"], record["upstream"]],
            [f"{BASE}/{HUB}/org/repo/resolve/{COMMIT}/a.gguf", URL_A],
        )

    def test_an_empty_base_keeps_the_upstream(self) -> None:
        [found] = LookupModule().run(["svc-models-a"], base="")
        self.assertEqual(found["model-a"]["url"], URL_A)

    def test_a_contract_break_fails_naming_role_and_artefact(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/main/c.gguf"
        self._role("svc-models-c", _block("model-c", url, "main", DIGEST_A))
        with self.assertRaisesRegex(AnsibleLookupError, "svc-models-c/model-c"):
            LookupModule().run(["svc-models-a"])

    def test_a_malformed_base_fails(self) -> None:
        with self.assertRaisesRegex(AnsibleLookupError, "ends in a slash"):
            LookupModule().run([], base=f"{BASE}/")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
