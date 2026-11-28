"""Lint: the infinito image turns the systemd-resolved stub listener off.

Fedora's systemd enables systemd-resolved, whose stub holds 127.0.0.53:53 and
127.0.0.54:53, so docker refused to publish svc-dns-knot on 0.0.0.0:53 with
"address already in use"."""

import configparser
import unittest
from pathlib import PurePosixPath

from utils import PROJECT_ROOT
from utils.cache.files import read_text

from . import dockerfile_commands

DROP_IN_DIR = PurePosixPath("/etc/systemd/resolved.conf.d")


def written_drop_ins(text: str) -> list[configparser.ConfigParser]:
    """Args:
        text: a Dockerfile.

    Returns:
        Every resolved.conf drop-in a ``RUN`` writes with ``printf``, parsed.
    """
    drop_ins: list[configparser.ConfigParser] = []
    for argv in dockerfile_commands(text):
        if argv[:1] != ["printf"] or ">" not in argv[:-1]:
            continue
        target = PurePosixPath(argv[argv.index(">") + 1])
        if target.parent != DROP_IN_DIR or target.suffix != ".conf":
            continue
        drop_in = configparser.ConfigParser(interpolation=None)
        drop_in.optionxform = str
        drop_in.read_string(argv[1].replace("\\n", "\n"))
        drop_ins.append(drop_in)
    return drop_ins


def _stub_off(text: str) -> bool:
    return any(
        drop_in.get("Resolve", "DNSStubListener", fallback=None) == "no"
        for drop_in in written_drop_ins(text)
    )


class TestResolvedStubOff(unittest.TestCase):
    def test_the_image_writes_the_stub_off_drop_in(self):
        self.assertTrue(_stub_off(read_text(str(PROJECT_ROOT / "Dockerfile"))))

    def test_negative_control_a_missing_or_commented_drop_in_is_flagged(self):
        self.assertFalse(_stub_off("RUN systemctl mask getty.target\n"))
        self.assertFalse(
            _stub_off(
                "# printf '[Resolve]\\nDNSStubListener=no\\n' "
                ">/etc/systemd/resolved.conf.d/x.conf\n"
            )
        )
        self.assertFalse(
            _stub_off(
                "RUN printf '[Resolve]\\nDNSStubListener=yes\\n' "
                ">/etc/systemd/resolved.conf.d/x.conf\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
