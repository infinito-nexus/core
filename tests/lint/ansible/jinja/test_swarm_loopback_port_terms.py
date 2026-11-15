"""Lint: every ``container_ports`` term swarm drops says how swarm reaches it.

A term bound to ``DOCKER_BIND_HOST`` publishes nothing in swarm. It passes when
the role's vhost proxies to it, when it renders only outside swarm, or when it
feeds Discourse's ``expose:`` list; every other one carries
``{# nocheck: swarm-loopback-port <exec|overlay|netns|unused|open> <reason> #}`` on
its line or in the comment block above. A marker that covers no such term is
dead and fails too; an ``open`` reason cites the open criterion that tracks it
as ``NNN :LINE``. The ``*.env.j2`` templates belong to the consumer lint. See
``utils/roles/swarm_loopback.py``.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.files import read_text
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_SERVER,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)
from utils.roles.swarm_loopback import (
    bound_terms,
    candidates,
    compose_pinned,
    in_compose_branch,
    role_variables,
    vhost_reach,
)
from utils.roles.swarm_loopback_markers import (
    CATEGORIES,
    RULE,
    attached_marker,
    reason_problem,
)

from . import PROJECT_ROOT


def _offset(text: str, line: int) -> int:
    return sum(len(row) + 1 for row in text.split("\n")[: line - 1])


def _templates(role_dir: Path) -> list[Path]:
    """Returns the role's templates, without the ``*.env.j2`` readers the consumer lint owns."""
    found = (role_dir / "templates").rglob("*.j2")  # nocheck: project-walk  fixtures
    return sorted(path for path in found if not path.name.endswith(".env.j2"))


def term_problems(roles_dir: Path) -> list[str]:
    """Returns one line per swarm-dropped term without an answer and per dead marker.

    Args:
        roles_dir: the repository's ``roles`` directory, beside its ``docs``.
    """
    problems: list[str] = []
    requirements_dir = roles_dir.parent / "docs" / "requirements"
    reaches = vhost_reach(roles_dir)
    for role_dir in sorted(path for path in roles_dir.iterdir() if path.is_dir()):
        templates = _templates(role_dir)
        if not templates:
            continue
        reach = reaches.get(role_dir.name, set())
        variables = role_variables(role_dir)
        for path in templates:
            text = read_text(str(path))
            if "DOCKER_BIND_HOST" not in text and RULE not in text:
                continue
            rel = path.relative_to(role_dir).as_posix()
            where = f"{role_dir.name}/{rel}"
            lines = text.splitlines()
            attached: set[int] = set()
            pinned = compose_pinned(role_dir, rel)
            for term in bound_terms(text):
                pos = _offset(text, term.line)
                pairs = {
                    (service, protocol)
                    for service in candidates(
                        term.service, role_dir, variables, text, pos
                    )
                    for protocol in candidates(
                        term.protocol, role_dir, variables, text, pos
                    )
                }
                if (
                    term.expose
                    or pinned
                    or pairs <= reach
                    or in_compose_branch(text, pos)
                ):
                    continue
                marker = attached_marker(lines, term.line)
                if marker is None:
                    problems.append(
                        f"{where}:{term.line}: [{term.service}, {term.protocol}, DOCKER_BIND_HOST] "
                        f"publishes nothing in swarm; say how swarm reaches it with "
                        f"nocheck: {RULE} <{'|'.join(CATEGORIES)}> <reason>"
                    )
                    continue
                attached.add(marker[0])
                problem = reason_problem(marker[1], requirements_dir)
                if problem:
                    problems.append(f"{where}:{marker[0]}: the {RULE} marker {problem}")
            problems.extend(
                f"{where}:{line}: dead nocheck: {RULE}, no swarm-dropped term needs it"
                for line in sorted(suppressed_line_numbers(lines, RULE) - attached)
            )
    return problems


def _role(
    roles_dir: Path,
    name: str,
    template: str,
    *,
    vhost: bool = False,
    vars_text: str = "",
) -> None:
    role_dir = roles_dir / name
    (role_dir / ROLE_FILE_TEMPL_COMPOSE).parent.mkdir(parents=True)
    (role_dir / ROLE_FILE_TEMPL_COMPOSE).write_text(template, encoding="utf-8")
    if vhost:
        (role_dir / ROLE_FILE_META_DOMAINS).parent.mkdir(parents=True, exist_ok=True)
        (role_dir / ROLE_FILE_META_DOMAINS).write_text(
            "canonical: []\n", encoding="utf-8"
        )
    if vars_text:
        (role_dir / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True, exist_ok=True)
        (role_dir / ROLE_FILE_VARS_MAIN).write_text(vars_text, encoding="utf-8")


class TestSwarmLoopbackPortTerms(unittest.TestCase):
    def test_every_swarm_dropped_term_is_answered(self) -> None:
        problems = term_problems(PROJECT_ROOT / "roles")
        self.assertEqual(
            [], problems, f"{len(problems)} problem(s):\n  " + "\n  ".join(problems)
        )

    def test_the_rule_reports_each_unanswered_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(
                roles_dir,
                "svc-db-plain",
                "    {{ lookup('container_ports', ['plain', 'plain', DOCKER_BIND_HOST]) | indent(4) }}\n",
            )
            _role(
                roles_dir,
                "svc-db-vague",
                "{# nocheck: swarm-loopback-port somehow  it is reached somehow #}\n"
                "    {{ lookup('container_ports', ['vague', 'vague', DOCKER_BIND_HOST]) | indent(4) }}\n",
            )
            _role(
                roles_dir,
                "svc-db-terse",
                "{# nocheck: swarm-loopback-port exec #}\n"
                "    {{ lookup('container_ports', ['terse', 'terse', DOCKER_BIND_HOST]) | indent(4) }}\n",
            )
            _role(
                roles_dir,
                "web-app-dead",
                "{# nocheck: swarm-loopback-port overlay  the vhost reaches it anyway #}\n"
                "    {{ lookup('container_ports', ['dead', 'http', DOCKER_BIND_HOST]) | indent(4) }}\n",
                vhost=True,
            )
            _role(
                roles_dir,
                "web-app-agent",
                "    {{ lookup('container_ports', ['agent', 'http', DOCKER_BIND_HOST], "
                "{'service': 'agent', 'protocol': 'agent', 'ip': DOCKER_BIND_HOST}) | indent(4) }}\n",
                vhost=True,
            )
            _role(
                roles_dir,
                "svc-db-answered",
                "{# nocheck: swarm-loopback-port exec  init runs through container exec #}\n"
                "    {{ lookup('container_ports', ['answered', 'answered', DOCKER_BIND_HOST]) | indent(4) }}\n"
                "{% if not IS_SWARM_MODE %}\n"
                "    {{ lookup('container_ports', ['answered', 'debug', DOCKER_BIND_HOST]) | indent(4) }}\n"
                "{% endif %}\n",
            )
            _role(
                roles_dir,
                "svc-db-pinned",
                "    {{ lookup('container_ports', ['pinned', 'pinned', DOCKER_BIND_HOST]) | indent(4) }}\n",
                vars_text="compose_mode_force: compose\n",
            )
            problems = term_problems(roles_dir)
        self.assertEqual(5, len(problems), problems)
        self.assertTrue(
            any(
                p.startswith("svc-db-plain/templates/compose.yml.j2:1: ['plain'")
                for p in problems
            )
        )
        self.assertTrue(
            any(
                p.startswith("svc-db-vague/") and "names no category" in p
                for p in problems
            )
        )
        self.assertTrue(
            any(
                p.startswith("svc-db-terse/") and "states no reason" in p
                for p in problems
            )
        )
        self.assertTrue(
            any(p.startswith("web-app-dead/") and "dead nocheck" in p for p in problems)
        )
        self.assertTrue(
            any(
                p.startswith("web-app-agent/") and "'agent', 'agent'" in p
                for p in problems
            )
        )

    def test_an_else_branch_of_a_swarm_condition_is_compose_only(self) -> None:
        text = "{% if IS_SWARM_MODE %}\na\n{% else %}\nb\n{% endif %}\nc\n"
        self.assertFalse(in_compose_branch(text, text.index("a")))
        self.assertTrue(in_compose_branch(text, text.index("b")))
        self.assertFalse(in_compose_branch(text, text.index("c")))

    def test_an_elif_after_a_swarm_arm_is_compose_only(self) -> None:
        text = (
            "{% if IS_SWARM_MODE | bool %}\nARM_A\n{% elif x %}\nARM_B\n{% endif %}\n"
        )
        self.assertTrue(in_compose_branch(text, text.index("ARM_B")))

    def test_only_a_mode_condition_of_the_right_polarity_confines(self) -> None:
        for condition in (
            "IS_COMPOSE_MODE",
            "not IS_SWARM_MODE",
            "not (IS_SWARM_MODE | bool)",
            "compose_mode == 'compose'",
            "compose_mode != 'swarm'",
            "IS_COMPOSE_MODE | bool and not DOCKER_IN_CONTAINER | bool",
        ):
            text = f"{{% if {condition} %}}\nARM_A\n{{% endif %}}\n"
            self.assertTrue(in_compose_branch(text, text.index("ARM_A")), condition)
        for condition in (
            "not IS_COMPOSE_MODE",
            "IS_COMPOSE_MODE or x",
            "x != 'swarm'",
            "IS_DEV_MODE",
            "compose_mode == 'swarm'",
        ):
            text = f"{{% if {condition} %}}\nARM_A\n{{% endif %}}\n"
            self.assertFalse(in_compose_branch(text, text.index("ARM_A")), condition)
        text = "{% if not IS_COMPOSE_MODE %}\nARM_A\n{% else %}\nARM_B\n{% endif %}\n"
        self.assertTrue(in_compose_branch(text, text.index("ARM_B")))

    def test_an_expose_term_and_a_bare_bind_host_are_no_swarm_terms(self) -> None:
        text = (
            "{{ lookup('container_ports', ['d', 'http', DOCKER_BIND_HOST], key='expose') }}\n"
            '- "{{ DOCKER_BIND_HOST }}:8080:80"\n'
        )
        terms = bound_terms(text)
        self.assertEqual(1, len(terms))
        self.assertTrue(terms[0].expose)

    def test_a_marker_on_a_comment_block_above_covers_the_term(self) -> None:
        lines = [
            "{# nocheck: swarm-loopback-port exec  init runs in the container #}",
            "{# more #}",
            "term",
        ]
        self.assertEqual(
            (1, "exec  init runs in the container"), attached_marker(lines, 3)
        )
        self.assertIsNone(
            attached_marker(
                ["{# nocheck: swarm-loopback-port exec x #}", "code", "term"], 3
            )
        )

    def test_a_wrapped_vhost_input_credits_its_continuation_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(
                roles_dir,
                "web-app-wrapped",
                "    {{ lookup('container_ports', ['web', 'http', DOCKER_BIND_HOST]) | indent(4) }}\n"
                "    {{ lookup('container_ports', ['admin', 'http', DOCKER_BIND_HOST]) | indent(4) }}\n",
            )
            server = roles_dir / "web-app-wrapped" / ROLE_FILE_META_SERVER
            server.parent.mkdir(parents=True)
            server.write_text(
                "csp:\n"
                "  web:\n"
                "    http_port: \"{{ lookup('config', 'web-app-wrapped', 'services.broker.ports.local.http') if SSO\n"
                "      else lookup('config', 'web-app-wrapped', 'services.web.ports.local.http') }}\"\n"
                "    internal_port: \"{{ lookup('config', 'web-app-wrapped', 'services.admin.ports.local.http') }}\"\n",
                encoding="utf-8",
            )
            problems = term_problems(roles_dir)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("['admin', 'http'", problems[0])


if __name__ == "__main__":
    unittest.main()
