"""Flag ``network_mode: host`` in ``compose.yml.j2`` templates when the
line is NOT inside a ``{% if DEPLOYMENT_MODE == 'compose' %}`` (or
equivalent compose-only) Jinja gate.

``docker stack deploy`` has had inconsistent / incomplete support for
``network_mode: host`` across versions; the swarm-correct pattern is
``ports: [{target, published, mode: host}]`` (per-port host binding)
combined with a placement constraint. Leaving ``network_mode: host``
unguarded means the role likely cannot be reliably deployed under
swarm.

Per-line opt-out: ``# nocheck: network-mode-host-without-swarm-gate``
on the offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "network-mode-host-without-swarm-gate"

_NETWORK_MODE_HOST = re.compile(r"^\s*network_mode:\s*[\"']?host[\"']?")
_IF = re.compile(r"\{%\s*if\s+(?P<expr>.+?)\s*%\}")
_ELIF = re.compile(r"\{%\s*elif\s+(?P<expr>.+?)\s*%\}")
_ELSE = re.compile(r"\{%\s*else\s*%\}")
_ENDIF = re.compile(r"\{%\s*endif\s*%\}")
_COMPOSE_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*!=\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*==\s*['\"]compose['\"]"
)
_SWARM_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*==\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*!=\s*['\"]compose['\"]"
)


def _frame_is_compose_only(expr: str, in_else: bool) -> bool:
    if not in_else:
        return bool(_COMPOSE_ONLY_GATE.search(expr))
    return bool(_SWARM_ONLY_GATE.search(expr))


def _is_inside_compose_only_gate(lines: list[str], target_idx: int) -> bool:
    stack: list[tuple[str, bool]] = []
    for i, raw in enumerate(lines):
        if i == target_idx:
            return any(_frame_is_compose_only(e, b) for e, b in stack)
        if _IF.search(raw):
            stack.append((_IF.search(raw).group("expr"), False))
        elif _ELIF.search(raw) and stack:
            stack[-1] = (_ELIF.search(raw).group("expr"), False)
        elif _ELSE.search(raw) and stack:
            stack[-1] = (stack[-1][0], True)
        elif _ENDIF.search(raw) and stack:
            stack.pop()
    return False


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith("compose.yml.j2")
    )


class TestComposeTemplateNoUnguardedNetworkModeHost(unittest.TestCase):
    def test_no_unguarded_network_mode_host_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _NETWORK_MODE_HOST.match(line):
                    continue
                if _is_inside_compose_only_gate(lines, idx):
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
                "Found `network_mode: host` in compose.yml.j2 templates "
                "without a compose-only gate. swarm support for "
                "`network_mode: host` is inconsistent across docker "
                "versions; the swarm-correct pattern is per-port host "
                "binding.\n\n"
                "Fix: split by mode. Example for an 80/443 frontend:\n\n"
                "    {% if DEPLOYMENT_MODE == 'swarm' %}\n"
                "        ports:\n"
                "          - target: 80\n"
                "            published: 80\n"
                "            protocol: tcp\n"
                "            mode: host\n"
                "          - target: 443\n"
                "            published: 443\n"
                "            protocol: tcp\n"
                "            mode: host\n"
                "    {% else %}\n"
                '        network_mode: "host"\n'
                "    {% endif %}\n\n"
                "If the service needs to be on every node (typical for an edge "
                "proxy), pair the ports form with `deploy.mode: global` rather "
                "than `placement: manager` so swarm-native "
                "distribution still applies.\n\n"
                "Mark with `# nocheck: network-mode-host-without-swarm-gate` "
                "only when the role is intentionally compose-only by design.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
