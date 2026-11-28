"""Every container log line carries its application as journald tag and label."""

from __future__ import annotations

import json
import unittest

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    nodes,
    select_autoescape,
)

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from .test_sandbox_runtime import BASE, LOGGING, TEMPLATES, _ansible_bool, _lookup

APPLICATION = "web-app-fixture"
LABEL = LOGGING["DOCKER_LOG_LABEL"]
LOGGING_TEMPLATE = "roles/sys-svc-container/templates/logging.yml.j2"


def _environment(root) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(root)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = _ansible_bool
    env.globals["lookup"] = _lookup
    return env


def _logging(**extra) -> dict:
    rendered = (
        _environment(PROJECT_ROOT)
        .get_template(LOGGING_TEMPLATE)
        .render(application_id=APPLICATION, DOCKER_LOG_LABEL=LABEL, **extra)
    )
    return load_yaml_str(rendered)


def _enclosing_blocks(source: str, target: str) -> list[int]:
    """
    Args:
        source: the text of a Jinja template.
        target: a template path the source renders.

    Returns:
        Per reference to ``target``, how many ``if``/``for`` blocks enclose it.
    """
    found = []

    def walk(node, depth: int) -> None:
        if isinstance(node, nodes.Const) and node.value == target:
            found.append(depth)
        nested = depth + isinstance(node, (nodes.If, nodes.For))
        for child in node.iter_child_nodes():
            walk(child, nested)

    walk(Environment(autoescape=True).parse(source), 0)
    return found


class TestComposeLoggingBlock(unittest.TestCase):
    def test_the_block_tags_and_labels_every_line_with_the_application(self) -> None:
        self.assertEqual(
            {
                "labels": {LABEL: APPLICATION},
                "logging": {
                    "driver": "journald",
                    "options": {"tag": APPLICATION, "labels": LABEL},
                },
            },
            _logging(),
        )

    def test_a_service_with_its_own_labels_keeps_the_log_options(self) -> None:
        rendered = _logging(logging_labels_declared=True)
        self.assertNotIn("labels", rendered)
        self.assertEqual(
            {"tag": APPLICATION, "labels": LABEL}, rendered["logging"]["options"]
        )

    def test_the_container_base_renders_the_block_unconditionally(self) -> None:
        base = read_text(str(TEMPLATES / "base.yml.j2"))
        self.assertEqual(
            [0],
            _enclosing_blocks(base, LOGGING_TEMPLATE),
            "base.yml.j2 must render the logging block once, outside any branch",
        )

    def test_negative_control_a_conditional_include_is_detected(self) -> None:
        source = "\n".join(
            [
                "{% if 'web-svc-loki' in group_names %}",
                f"    {{{{ lookup('template', '{LOGGING_TEMPLATE}') | indent(4) }}}}",
                "{% endif %}",
            ]
        )
        self.assertEqual([1], _enclosing_blocks(source, LOGGING_TEMPLATE))


class TestDaemonLoggingDefault(unittest.TestCase):
    def _daemon(self) -> dict:
        variables = {**BASE, "IS_COMPOSE_MODE": False, "IS_SWARM_MODE": True}
        return json.loads(
            _environment(TEMPLATES).get_template("daemon.json.j2").render(variables)
        )

    def test_the_daemon_defaults_to_journald(self) -> None:
        self.assertEqual("journald", self._daemon()["log-driver"])

    def test_the_default_tag_is_the_application_label_with_the_name_as_fallback(
        self,
    ) -> None:
        self.assertEqual(
            {
                "tag": "{{with index .ContainerLabels "
                + json.dumps(LABEL)
                + "}}{{.}}{{else}}{{.Name}}{{end}}",
                "labels": LABEL,
            },
            self._daemon()["log-opts"],
        )


if __name__ == "__main__":
    unittest.main()
