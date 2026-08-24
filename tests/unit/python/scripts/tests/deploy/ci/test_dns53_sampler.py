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


class AnswerProbeTests(unittest.TestCase):
    def _answer(self, name: str) -> str:
        proc = subprocess.run(
            [
                "sh",
                "-c",
                'DNS53_SAMPLER_LIB=1 . "$1" && answer_once "$2"',
                "sh",
                str(SAMPLER),
                name,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def test_a_resolvable_name_is_reported_ok_with_its_latency(self):
        self.assertRegex(self._answer("localhost"), r"^ localhost=ok/\d+ms$")

    def test_an_unresolvable_name_is_reported_fail_not_skipped(self):
        self.assertRegex(
            self._answer("rescue-probe.invalid"),
            r"^ rescue-probe\.invalid=fail/\d+ms$",
        )


class ZoneProbeNameTests(unittest.TestCase):
    def _zone(self, conf: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".conf") as handle:
            handle.write(conf)
            handle.flush()
            proc = subprocess.run(
                [
                    "sh",
                    "-c",
                    'DNS53_SAMPLER_LIB=1 . "$1" && zone_probe_name "$2"',
                    "sh",
                    str(SAMPLER),
                    handle.name,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        return proc.stdout

    def test_the_owned_zone_becomes_a_probe_name(self):
        self.assertEqual(
            self._zone("no-resolv\naddress=/infinito.example/192.168.244.10\n"),
            "rescue-probe.infinito.example",
        )

    def test_a_config_without_a_zone_yields_nothing(self):
        self.assertEqual(self._zone("no-resolv\nserver=192.0.2.1\n"), "")


if __name__ == "__main__":
    unittest.main()
