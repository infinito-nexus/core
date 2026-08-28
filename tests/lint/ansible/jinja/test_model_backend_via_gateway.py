"""Keep model traffic on the gateway instead of a provider URL.

Rationale
=========
``svc-ai-litellm`` is the single entrypoint to every model backend: it owns the
model list, the per-consumer virtual keys and the routing. An application that
addresses a provider directly bypasses all three, so its traffic carries no
consumer identity, ignores the routing, and keeps working after the model list
moved on.

The gateway itself is the one legitimate holder of provider URLs, because
routing to them is its job.

Per-line opt-out
================
Add ``# nocheck: model-backend-via-gateway`` on the offending line or on the
immediately preceding non-empty line, together with the reason this consumer
cannot go through the gateway.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "model-backend-via-gateway"

_GATEWAY_ROLE = "svc-ai-litellm"

_PROVIDER_URL = re.compile(r"\{\{[^}]*\b(OLLAMA|LMSTUDIO)_BASE_LOCAL_URL\b")


class TestModelBackendViaGateway(unittest.TestCase):
    def test_only_the_gateway_addresses_a_provider_directly(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            parts = rel.split("/")
            if len(parts) < 2 or parts[0] != "roles" or "/templates/" not in rel:
                continue
            if parts[1] == _GATEWAY_ROLE:
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _PROVIDER_URL.search(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "These templates address a model provider directly instead of "
                f"routing through {_GATEWAY_ROLE}, so their traffic carries no "
                "consumer identity and ignores the gateway's model list.\n\n"
                "Fix: declare `services.litellm` in the role's meta/services.yml "
                "and a `litellm_api_key` credential in its meta/secrets.yml, then "
                "point the application at LITELLM_BASE_LOCAL_URL with that key. "
                "The gateway provisions the virtual key for every role that "
                "declares both.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
