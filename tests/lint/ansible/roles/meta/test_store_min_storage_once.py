from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from humanfriendly import parse_size

from utils.cache import hosts
from utils.cache.artefacts import ARGOS_NET, checked, store_bytes, unpacked_bytes
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_META_SERVICES

STORE_ROLE = "svc-ai-models"
STORE_SERVICE = "models"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
ARGOS_UPSTREAM = f"https://{ARGOS_NET}/"


def _min_storage(role_dir: Path) -> dict[str, int]:
    services = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    return {
        str(key): int(parse_size(str(conf["min_storage"])))
        for key, conf in (services or {}).items()
        if isinstance(conf, dict) and conf.get("min_storage") is not None
    }


def _findings(roles_dir: Path) -> list[str]:
    declared_artefacts = checked()
    need = store_bytes(declared_artefacts) + unpacked_bytes(declared_artefacts)
    declared = _min_storage(roles_dir / STORE_ROLE).get(STORE_SERVICE)
    drift = (
        f"{STORE_ROLE}: services.{STORE_SERVICE}.min_storage is {declared}, "
        f"but the declared artefacts need {need} bytes, packed and unpacked"
    )
    found = [] if declared == need else [drift]
    found.extend(
        f"{role_dir.name}: declares services.{STORE_SERVICE}.min_storage; only "
        f"{STORE_ROLE} counts the store"
        for role_dir in sorted(roles_dir.iterdir())
        if role_dir.name != STORE_ROLE and STORE_SERVICE in _min_storage(role_dir)
    )
    return found


def _scratch_findings(min_storage: int, *, second_owner: bool = False) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        roles = Path(tmp) / "roles"
        (roles / STORE_ROLE / "meta").mkdir(parents=True)
        (roles / STORE_ROLE / ROLE_FILE_META_NETWORKS).write_text(
            "cache:\n"
            "  repos:\n"
            "    raw-huggingface:\n"
            "      flavor: raw\n"
            "      upstream: https://huggingface.co/\n"
            "    raw-argos-net:\n"
            "      flavor: raw\n"
            f"      upstream: {ARGOS_UPSTREAM}\n"
            "  hosts:\n"
            "    huggingface.co:\n"
            "      repo: raw-huggingface\n"
            "    argos-net.com:\n"
            "      repo: raw-argos-net\n"
            "  artefacts:\n"
            "    model:\n"
            f"      url: https://huggingface.co/org/repo/resolve/{COMMIT}/m.gguf\n"
            f'      revision: "{COMMIT}"\n'
            f'      sha256: "{"a" * 64}"\n'
            '      bytes: "42"\n'
            "    argos-en-de:\n"
            "      url: https://argos-net.com/v1/translate-en_de-1_9.argosmodel\n"
            '      revision: "1_9"\n'
            f'      sha256: "{"b" * 64}"\n'
            '      bytes: "40"\n'
            '      unpacked_bytes: "55"\n',
            encoding="utf-8",
        )
        (roles / STORE_ROLE / ROLE_FILE_META_SERVICES).write_text(
            f"{STORE_SERVICE}:\n  min_storage: {min_storage}\n", encoding="utf-8"
        )
        if second_owner:
            (roles / "svc-ai-engine" / "meta").mkdir(parents=True)
            (roles / "svc-ai-engine" / ROLE_FILE_META_SERVICES).write_text(
                f"{STORE_SERVICE}:\n  min_storage: 42\n", encoding="utf-8"
            )
        with patch("utils.cache.hosts.ROLES_DIR", roles):
            return _findings(roles)


class TestStoreMinStorageOnce(unittest.TestCase):
    def test_only_the_store_role_declares_store_bytes(self) -> None:
        findings = _findings(hosts.ROLES_DIR)
        self.assertFalse(findings, "\n".join(findings))

    def test_an_argos_package_counts_packed_and_unpacked_once(self) -> None:
        self.assertEqual(_scratch_findings(42 + 40 + 55), [])

    def test_the_guard_reports_a_drifted_store_and_a_second_owner(self) -> None:
        findings = _scratch_findings(42 + 40, second_owner=True)
        self.assertEqual(
            [line.split(":")[0] for line in findings], [STORE_ROLE, "svc-ai-engine"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
