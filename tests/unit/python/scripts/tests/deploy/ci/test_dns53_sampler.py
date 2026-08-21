"""One tick of the :53 sampler against canned kernel tables.

Run 32118850138 bounded the dnsmasq listener loss only to a 6m39s window
between two host DNS consumers. The sampler shrinks that to one 10s bucket,
so its filter must report a bound :53 listener and must not count connected
clients whose remote end is :53, other ports, or the embedded Docker DNS.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest

from utils.cache.files import PROJECT_ROOT

SAMPLER = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "ci" / "dns53-sampler.sh"

HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when "
    "retrnsmt   uid  timeout inode ref pointer drops"
)
EMBEDDED_DNS = "   1: 0B00007F:B044 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 1 0 x 0"
LOOPBACK_53 = "   2: 0100007F:0035 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 1 0 x 0"
CLIENT_TO_53 = "   3: 0100007F:C350 0100007F:0035 01 00000000:00000000 00:00000000 00000000     0        0 1 0 x 0"

TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


def _tick(*rows: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".udp") as table:
        table.write("\n".join([HEADER, *rows]) + "\n")
        table.flush()
        proc = subprocess.run(
            [
                "sh",
                "-c",
                'DNS53_SAMPLER_LIB=1 . "$1" && sample_once "$2"',
                "sh",
                str(SAMPLER),
                table.name,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return proc.stdout.strip()


class SamplerTickTests(unittest.TestCase):
    def test_a_bound_loopback_listener_is_reported(self):
        line = _tick(EMBEDDED_DNS, LOOPBACK_53, CLIENT_TO_53)
        self.assertRegex(line, TIMESTAMP + r" 0100007F:0035$")

    def test_a_missing_listener_reports_none(self):
        line = _tick(EMBEDDED_DNS, CLIENT_TO_53)
        self.assertRegex(line, TIMESTAMP + r" none$")


if __name__ == "__main__":
    unittest.main()
