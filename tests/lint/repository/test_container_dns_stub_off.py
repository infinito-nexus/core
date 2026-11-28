import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text

from . import dockerfile_commands, shell_commands

DROP_IN_DIR = "/etc/systemd/resolved.conf.d/"
SETTING = "DNSStubListener=no"
WRITERS = {
    "Dockerfile": dockerfile_commands,
    "compose/target/init.sh": shell_commands,
}


def _turns_stub_off(commands):
    """Args:
        commands: the argv of every command an image build or init runs.

    Returns:
        Whether one command prints the setting into a resolved.conf.d drop-in.
    """
    for argv in commands:
        if argv[:1] != ["printf"] or ">" not in argv:
            continue
        target = argv[argv.index(">") + 1 :][:1]
        if (
            any(SETTING in word for word in argv[1 : argv.index(">")])
            and target
            and target[0].startswith(DROP_IN_DIR)
        ):
            return True
    return False


class TestContainerDnsStubOff(unittest.TestCase):
    def test_images_turn_the_stub_listener_off(self):  # nocheck: test.text-presence -- tokenizes the file into commands; the rule taints tokenizer output  # fmt: skip
        for path, commands in WRITERS.items():
            with self.subTest(path=path):
                self.assertTrue(
                    _turns_stub_off(commands(read_text(str(PROJECT_ROOT / path))))
                )

    def test_negative_control_a_missing_drop_in_is_flagged(self):
        self.assertFalse(
            _turns_stub_off(
                shell_commands("systemctl mask getty.target\nenable_sshd\n")
            )
        )
        self.assertFalse(
            _turns_stub_off(
                shell_commands(
                    "printf '[Resolve]\\nDNSStubListener=yes\\n' >"
                    "/etc/systemd/resolved.conf.d/x.conf\n"
                )
            )
        )
        self.assertFalse(
            _turns_stub_off(
                shell_commands(
                    "printf '[Resolve]\\nDNSStubListener=no\\n' >/tmp/x.conf\n"
                )
            )
        )
        self.assertTrue(
            _turns_stub_off(
                shell_commands(
                    "printf '[Resolve]\\nDNSStubListener=no\\n' >"
                    "/etc/systemd/resolved.conf.d/x.conf\n"
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
