"""Lint: the infinito image turns the systemd-resolved stub listener off.

Fedora's systemd enables systemd-resolved, whose stub holds 127.0.0.53:53 and
127.0.0.54:53, so docker refused to publish svc-dns-knot on 0.0.0.0:53 with
"address already in use"."""

import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text

DROP_IN = re.compile(
    r"\[Resolve\]\\nDNSStubListener=no\\n'\s*>\s*/etc/systemd/resolved\.conf\.d/[\w.-]+\.conf"
)


def _stub_off(text: str) -> bool:
    joined = re.sub(r"\\\n", " ", text)
    return any(
        line.lstrip().startswith("RUN") and DROP_IN.search(line)
        for line in joined.splitlines()
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
