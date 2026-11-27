from __future__ import annotations

import unittest

from plugins.filter.swarm.env_literal import (
    GO_TEMPLATE_OPEN,
    GO_TEMPLATE_OPEN_LITERAL,
    FilterModule,
    swarm_env_literal,
)

EMAIL_CLAIM = (
    '{"keycloak": {"email_claim": "{{ $member := false }}{{ range index . '
    '\\"groups\\" }}{{ $member = true }}{{ end }}{{{ }}}", "scopes": ["openid"]}}'
)


def swarmkit_expansion_findings(value: str) -> list[str]:
    """Args:
        value: an env value as swarmkit receives it.

    Returns:
        Why swarmkit's Go template expansion would reject or alter the value:
        every ``{{`` must open the literal action, which prints ``{{``.
    """
    texts = value.split(GO_TEMPLATE_OPEN_LITERAL)
    return [
        f"Go template action opens in {text!r}"
        for text in texts
        if GO_TEMPLATE_OPEN in text
    ]


def swarmkit_expand(value: str) -> str:
    """Args:
        value: an env value without findings in
            :func:`swarmkit_expansion_findings`.

    Returns:
        What the container receives after swarmkit's expansion.
    """
    return GO_TEMPLATE_OPEN.join(value.split(GO_TEMPLATE_OPEN_LITERAL))


class TestSwarmEnvLiteral(unittest.TestCase):
    def test_a_go_template_value_reaches_the_container_unchanged(self):
        escaped = swarm_env_literal(EMAIL_CLAIM)
        self.assertEqual(swarmkit_expansion_findings(escaped), [])
        self.assertEqual(swarmkit_expand(escaped), EMAIL_CLAIM)

    def test_a_literal_action_in_the_value_round_trips(self):
        value = f"a{GO_TEMPLATE_OPEN_LITERAL}b{{{{{{"
        escaped = swarm_env_literal(value)
        self.assertEqual(swarmkit_expansion_findings(escaped), [])
        self.assertEqual(swarmkit_expand(escaped), value)

    def test_a_value_without_braces_is_unchanged(self):
        self.assertEqual(swarm_env_literal("plain}}value"), "plain}}value")

    def test_none_is_empty(self):
        self.assertEqual(swarm_env_literal(None), "")

    def test_the_filter_is_registered(self):
        self.assertIs(FilterModule().filters()["swarm_env_literal"], swarm_env_literal)

    def test_negative_control_an_unescaped_value_is_reported(self):
        self.assertTrue(swarmkit_expansion_findings(EMAIL_CLAIM))


if __name__ == "__main__":
    unittest.main()
