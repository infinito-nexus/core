"""The knowledge index holds no secret.

A knowledge tree is staged the way the role stages it, from the platform
documentation and two role READMEs of this repository plus a tenant source,
and seeded with every secret shape the repository's redactor knows, an Ansible
Vault block, an e-mail address and inventory files. The index is built from
it with a stub embedder into a memory store, and no seeded value and no secret
pattern may reach a stored passage.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from utils.agents.redact import redact

from . import PROJECT_ROOT

_PACKAGE_PARENT = str(PROJECT_ROOT / "roles" / "web-svc-assistant" / "files" / "python")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

index = importlib.import_module("assistant.index")
sources = importlib.import_module("assistant.sources")

PLATFORM_DOCS = PROJECT_ROOT / "docs" / "administration"
ROLE_READMES = ("web-svc-translate", "svc-ai-ollama")

KEY_BODY = "MIIEowIBAAKCAQEA" + "seeded"
VAULT_BODY = "6162636465" + "6667686970"
AWS_KEY = "AKIA" + "ZQXWVUTSRQPONMLK"
GITHUB_TOKEN = "ghp_" + "Z" * 36
BEARER = "seededbearer" + "token0123456789"
URL_PASSWORD = "seeded" + "urlpass"
PASSWORD = "seeded" + "password42"
API_KEY = "seeded" + "apikey4242"
EMAIL = "anna.biber" + "@example.org"

SEEDED = {
    "private key": f"-----BEGIN RSA {'PRIVATE'} KEY-----\n{KEY_BODY}\n-----END RSA {'PRIVATE'} KEY-----",
    "vault": "$ANSIBLE_" + f"VAULT;1.1;AES256\n  {VAULT_BODY}\n  71727374757677787980",
    "aws key": AWS_KEY,
    "github token": GITHUB_TOKEN,
    "bearer": f"Bearer {BEARER}",
    "url credentials": f"https://biber:{URL_PASSWORD}@git.example/repo",
    "password line": f"password: {PASSWORD}",
    "api key line": f"api_key = {API_KEY}",
    "email": EMAIL,
}
SEEDED_VALUES = (
    KEY_BODY,
    VAULT_BODY,
    AWS_KEY,
    GITHUB_TOKEN,
    BEARER,
    URL_PASSWORD,
    PASSWORD,
    API_KEY,
    EMAIL,
)
INVENTORY_ONLY = "inventory-only-marker-7f3a"


class StubEmbedder:
    def embed(self, texts):
        return [[float(len(text))] for text in texts]


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list = []

    async def replace(self, rows) -> None:
        self.rows = list(rows)


def _stage(knowledge: Path) -> None:
    shutil.copytree(PLATFORM_DOCS, knowledge / "platform")
    for role in ROLE_READMES:
        target = knowledge / "roles" / role
        target.mkdir(parents=True)
        shutil.copy(PROJECT_ROOT / "roles" / role / "README.md", target / "README.md")
    tenant = knowledge / "tenant" / "acme"
    (tenant / "inventories" / "acme").mkdir(parents=True)
    (tenant / "host_vars").mkdir()
    seeded = "\n\n".join(
        f"## {name}\n\nThe {name} is {value} here." for name, value in SEEDED.items()
    )
    (tenant / "operations.md").write_text(
        f"# Operations\n\nThe office opens at nine.\n\n{seeded}\n"
    )
    (tenant / "inventories" / "acme" / "README.md").write_text(
        f"# Inventory\n\n{INVENTORY_ONLY}\n"
    )
    (tenant / "host_vars" / "notes.md").write_text(f"# Host\n\n{INVENTORY_ONLY}\n")
    (tenant / ".env").write_text(f"SECRET={INVENTORY_ONLY}\n")
    manifest = [
        {
            "name": "platform",
            "root": "platform",
            "url": "https://code.example/docs/administration",
        },
        *(
            {
                "name": role,
                "root": f"roles/{role}",
                "url": f"https://code.example/roles/{role}",
            }
            for role in ROLE_READMES
        ),
        {"name": "acme", "root": "tenant/acme", "url": "https://acme.example/help"},
    ]
    (knowledge / sources.MANIFEST).write_text(json.dumps(manifest))


class TestIndexHoldsNoSecret(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        knowledge = Path(cls._tmp.name)
        _stage(knowledge)
        cls.store = MemoryStore()
        documents = sources.documents(knowledge, sources.load_manifest(knowledge))
        cls.count = asyncio.run(index.build(documents, StubEmbedder(), cls.store, 1200))
        cls.texts = [row[0].text for row in cls.store.rows]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_every_source_reached_the_index(self) -> None:
        sources_indexed = {row[0].source for row in self.store.rows}
        self.assertEqual(sources_indexed, {"platform", *ROLE_READMES, "acme"})
        self.assertEqual(self.count, len(self.texts))

    def test_no_seeded_secret_value_reached_the_index(self) -> None:
        leaked = [
            value
            for value in SEEDED_VALUES
            if any(value in text for text in self.texts)
        ]
        self.assertEqual(leaked, [])

    def test_no_secret_pattern_matches_a_stored_passage(self) -> None:
        matching = [
            row[0].url for row in self.store.rows if redact(row[0].text) != row[0].text
        ]
        self.assertEqual(matching, [])

    def test_inventory_and_env_files_were_never_read(self) -> None:
        self.assertFalse(any(INVENTORY_ONLY in text for text in self.texts))

    def test_the_prose_around_a_secret_stays_answerable(self) -> None:
        self.assertTrue(any("The office opens at nine." in text for text in self.texts))


if __name__ == "__main__":
    unittest.main()
