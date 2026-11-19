"""A journald restart onto Storage=persistent moves the journal to /var/log/journal."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "sys-svc-journalctl"
TOPIC = "restart-systemd-journald"


def handlers_on(topic: str) -> list[dict]:
    """
    Args:
        topic: a handler listen topic.

    Returns:
        The role's handlers listening on it, in run order.
    """
    handlers = load_yaml_any(str(ROLE / "handlers" / "main.yml"))
    return [
        handler
        for handler in handlers
        if topic
        in (
            [handler.get("listen")]
            if isinstance(handler.get("listen"), str)
            else handler.get("listen") or []
        )
    ]


def argv(handler: dict) -> list[str]:
    """
    Args:
        handler: one handler task.

    Returns:
        The argv of its command module, or [] for any other module.
    """
    command = handler.get("ansible.builtin.command") or handler.get("command") or {}
    return list(command.get("argv") or []) if isinstance(command, dict) else []


class TestPersistentStorage(unittest.TestCase):
    def test_the_template_asks_for_persistent_storage(self):
        self.assertRegex(
            read_text(str(ROLE / "templates" / "journald.conf.j2")),
            re.compile(r"^Storage=persistent$", re.MULTILINE),
        )

    def test_the_restart_is_followed_by_a_flush(self):
        handlers = handlers_on(TOPIC)
        flushes = [
            index
            for index, handler in enumerate(handlers)
            if argv(handler) == ["journalctl", "--flush"]
        ]
        self.assertTrue(
            flushes,
            "a restarted journald stays on /run/log/journal until a flush request, "
            "so a host that booted with a volatile journal never fills "
            "/var/log/journal, the only path the log collector reads",
        )
        self.assertGreater(flushes[0], 0, "the flush must run after the restart")


if __name__ == "__main__":
    unittest.main()
