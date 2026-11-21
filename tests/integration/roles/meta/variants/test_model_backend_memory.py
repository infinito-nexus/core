from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import Any

from humanfriendly import parse_size

from utils.cache.applications import get_variants

SERVING_MEM_LIMIT_FLOOR = parse_size("3g", binary=True)
EVIDENCE = (
    "A 2 GiB cgroup was filled by llmster plus llama-server holding the "
    "Llama-3.2-1B Q4_K_M weights and an 8192-token cache, and the kernel "
    "OOM-killed the engine while three probe requests ran (CI run 44423631737, "
    "Zammad#2). A variant that preloads a model MUST leave it at least "
    "3 GiB, or its first concurrent requests die as HTTP 400 'terminated'."
)
REACH = ("svc-ai-lmstudio", 0, "lmstudio")


def _serving(variants: Mapping[str, list[Any]]) -> list[tuple[str, int, str, Any]]:
    """Every service of every variant that preloads a model.

    Args:
        variants: ``{role: [variant_config, ...]}`` as ``get_variants`` builds it.

    Returns:
        ``(role, variant index, service, mem_limit)`` per serving service.
    """
    return [
        (role, index, service, config.get("mem_limit"))
        for role, entries in sorted(variants.items())
        for index, entry in enumerate(entries)
        for service, config in sorted(((entry or {}).get("services") or {}).items())
        if isinstance(config, Mapping) and config.get("preload_models")
    ]


def _findings(variants: Mapping[str, list[Any]]) -> list[str]:
    """Serving services whose memory ceiling is below the floor.

    Args:
        variants: ``{role: [variant_config, ...]}`` as ``get_variants`` builds it.

    Returns:
        One line per service that preloads a model under too small a ceiling.
    """
    return [
        f"{role} variant {index}: {service}.mem_limit={limit}"
        for role, index, service, limit in _serving(variants)
        if limit is None
        or parse_size(str(limit), binary=True) < SERVING_MEM_LIMIT_FLOOR
    ]


def _lmstudio(mem_limit: str) -> dict[str, list[Any]]:
    """A variants map with one LM Studio variant preloading a model.

    Args:
        mem_limit: the ceiling the variant gives the service.

    Returns:
        The map ``_findings`` reads.
    """
    return {
        "svc-ai-lmstudio": [
            {
                "services": {
                    "lmstudio": {
                        "preload_models": "{{ AI_LOCAL_MODELS }}",
                        "mem_limit": mem_limit,
                    },
                    "docs": {"enabled": True},
                }
            }
        ],
        "svc-ai-ollama": [
            {"services": {"ollama": {"preload_models": [], "mem_limit": "2g"}}}
        ],
    }


class TestModelBackendMemory(unittest.TestCase):
    def test_every_serving_variant_leaves_a_loaded_model_room(self) -> None:
        findings = _findings(get_variants())
        self.assertEqual(findings, [], EVIDENCE + "\n" + "\n".join(findings))

    def test_the_scan_reaches_the_lm_studio_serving_variant(self) -> None:
        reached = {
            (role, index, service)
            for role, index, service, _ in _serving(get_variants())
        }
        self.assertIn(REACH, reached)

    def test_a_two_gigabyte_serving_variant_is_reported(self) -> None:
        self.assertEqual(
            _findings(_lmstudio("2g")),
            ["svc-ai-lmstudio variant 0: lmstudio.mem_limit=2g"],
        )

    def test_a_four_gigabyte_serving_variant_passes(self) -> None:
        self.assertEqual(_findings(_lmstudio("4g")), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
