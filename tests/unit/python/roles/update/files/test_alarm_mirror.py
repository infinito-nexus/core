import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/update/files/shell/alarm_mirror.sh"
GEO = "Server = http://mirror.archlinuxarm.org/$arch/$repo"
GEO_HTTPS = "Server = https://mirror.archlinuxarm.org/$arch/$repo"
DE = "Server = http://de.mirror.archlinuxarm.org/$arch/$repo"
DE3 = "Server = http://de3.mirror.archlinuxarm.org/$arch/$repo"
DK = "Server = http://dk.mirror.archlinuxarm.org/$arch/$repo"
HEADER = ["#", "# Arch Linux ARM repository mirrorlist", "#", ""]
IMAGE = [
    *HEADER,
    "## Geo-IP based mirror selection and load balancing",
    GEO,
    "",
    "### Germany",
    DE,
    DE3,
    "",
    "### Denmark",
    DK,
]
STOCK = [
    *HEADER,
    "## Geo-IP based mirror selection and load balancing",
    GEO,
    "",
    "### Germany",
    f"# {DE}",
    f"# {DE3}",
]
TWO_GEO = [*HEADER, GEO, GEO_HTTPS, "", DE, DE3, DK]
X86 = [
    "##",
    "## Arch Linux repository mirrorlist",
    "##",
    "",
    "Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch",
    "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch",
    "Server = https://mirrors.kernel.org/archlinux/$repo/os/$arch",
]
PACMAN_FAILED = 7
DEMOTED = 3
PACMAN_STUB = (
    "#!/bin/sh\n"
    'lead="$(grep -m 1 -E \'^[[:space:]]*Server[[:space:]]*=\' "${MIRRORLIST}")"\n'
    'printf \'%s|%s\\n\' "${lead}" "$*" >> "${PACMAN_LOG}"\n'
    "echo 'resolving dependencies...'\n"
    'if [ -n "${PACMAN_SERVES}" ]; then\n'
    '\tcase "${lead}" in *"${PACMAN_SERVES}"*) exit 0 ;; esac\n'
    "fi\n"
    f"exit {PACMAN_FAILED}\n"
)
RESYNC_UPGRADE = "--sync --refresh --refresh --sysupgrade --noconfirm"


def text(lines):
    return "\n".join(lines) + "\n"


class TestAlarmMirror(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "pacman"
        stub.write_text(PACMAN_STUB)
        stub.chmod(0o755)
        self.mirrorlist = self.root / "mirrorlist"
        self.pacman_log = self.root / "pacman.log"
        self.env = dict(os.environ)
        self.env["PATH"] = f"{bin_dir}{os.pathsep}{self.env['PATH']}"
        self.env["MIRRORLIST"] = str(self.mirrorlist)
        self.env["PACMAN_LOG"] = str(self.pacman_log)

    def run_helper(self, verb, lines=None, serves=""):
        """Run the helper the way the role does, with a pacman stub on PATH.

        Args:
            verb: demote or retry.
            lines: the mirrorlist's lines before the run, or None to keep the
                mirrorlist an earlier run left.
            serves: the host whose upgrade the stub lets succeed while it is
                the first Server; every other first Server, and every one when
                empty, fails with PACMAN_FAILED.

        Returns:
            Tuple of exit code, stdout, and the mirrorlist's lines after the
            run, or None when there is no mirrorlist.
        """
        if lines is not None:
            self.mirrorlist.write_text(text(lines))
        env = dict(self.env, PACMAN_SERVES=serves)
        done = subprocess.run(
            ["bash", str(SCRIPT), verb, str(self.mirrorlist)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if not self.mirrorlist.exists():
            return done.returncode, done.stdout, None
        after = self.mirrorlist.read_text()  # nocheck: cache-read rewritten
        return done.returncode, done.stdout, after.splitlines()

    def pacman_calls(self):
        """Read the pacman stub's log.

        Returns:
            One (first Server, argv) pair per pacman call, in call order.
        """
        if not self.pacman_log.exists():
            return []
        return [
            tuple(line.split("|", 1))
            for line in read_text(str(self.pacman_log)).splitlines()
        ]

    def servers(self, lines):
        return [line for line in lines if line.startswith("Server")]

    def test_demote_moves_the_geo_host_behind_the_last_server(self):
        code, out, after = self.run_helper("demote", IMAGE)
        self.assertEqual(code, DEMOTED)
        self.assertEqual(self.servers(after), [DE, DE3, DK, GEO])
        self.assertEqual(out, f"{DE}\n")

    def test_demote_keeps_every_other_line_in_place(self):
        _, _, after = self.run_helper("demote", IMAGE)
        self.assertEqual(after, [line for line in IMAGE if line != GEO] + [GEO])

    def test_demote_twice_changes_nothing_the_second_time(self):
        self.run_helper("demote", IMAGE)
        code, out, after = self.run_helper("demote")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(self.servers(after), [DE, DE3, DK, GEO])

    def test_demote_leaves_a_geo_only_mirrorlist_untouched(self):
        code, out, after = self.run_helper("demote", STOCK)
        self.assertEqual((code, out, after), (0, "", STOCK))

    def test_demote_moves_every_geo_line_behind_the_last_server(self):
        code, out, after = self.run_helper("demote", TWO_GEO)
        self.assertEqual(code, DEMOTED)
        self.assertEqual(out, f"{DE}\n")
        self.assertEqual(self.servers(after)[:3], [DE, DE3, DK])
        self.assertEqual(sorted(self.servers(after)[3:]), sorted([GEO, GEO_HTTPS]))

    def test_demote_keeps_the_mirrorlist_mode(self):
        self.mirrorlist.write_text(text(IMAGE))
        self.mirrorlist.chmod(0o640)
        code, _, _ = self.run_helper("demote")
        self.assertEqual(code, DEMOTED)
        self.assertEqual(self.mirrorlist.stat().st_mode & 0o777, 0o640)
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()), ["bin", "mirrorlist"]
        )

    def test_a_missing_mirrorlist_counts_as_one_without_the_geo_host(self):
        for verb, expected in (("demote", 0), ("retry", 1)):
            with self.subTest(verb=verb):
                code, out, after = self.run_helper(verb)
                self.assertEqual((code, out, after), (expected, "", None))
        self.assertEqual(self.pacman_calls(), [])

    def test_an_x86_64_mirrorlist_stays_untouched(self):
        for verb, expected in (("demote", 0), ("retry", 1)):
            with self.subTest(verb=verb):
                code, out, after = self.run_helper(verb, X86)
                self.assertEqual((code, out, after), (expected, "", X86))
        self.assertEqual(self.pacman_calls(), [])

    def test_retry_moves_on_resyncs_and_upgrades_from_the_next_mirror(self):
        self.run_helper("demote", IMAGE)
        code, out, after = self.run_helper("retry", serves="de3.mirror")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"{DE3}\n")
        self.assertEqual(self.pacman_calls(), [(DE3, RESYNC_UPGRADE)])
        self.assertEqual(self.servers(after), [DE3, DK, DE, GEO])

    def test_retry_tries_every_further_concrete_mirror_once(self):
        self.run_helper("demote", IMAGE)
        code, out, after = self.run_helper("retry")
        self.assertEqual(code, PACMAN_FAILED)
        self.assertEqual(out, "")
        self.assertEqual(
            self.pacman_calls(), [(DE3, RESYNC_UPGRADE), (DK, RESYNC_UPGRADE)]
        )
        self.assertEqual(self.servers(after)[0], DK)

    def test_retry_never_lets_the_geo_host_lead(self):
        self.run_helper("demote", IMAGE)
        self.run_helper("retry")
        leads = [lead for lead, _ in self.pacman_calls()]
        self.assertTrue(leads)
        self.assertNotIn(GEO, leads)

    def test_retry_never_lets_a_second_geo_line_lead(self):
        code, _, _ = self.run_helper("retry", TWO_GEO)
        leads = [lead for lead, _ in self.pacman_calls()]
        self.assertEqual(code, PACMAN_FAILED)
        self.assertEqual(leads, [DE3, DK])

    def test_retry_keeps_pacman_output_off_stdout(self):
        self.run_helper("demote", IMAGE)
        _, out, _ = self.run_helper("retry", serves="dk.mirror")
        self.assertEqual(out, f"{DK}\n")

    def test_retry_without_a_further_concrete_mirror_fails_untouched(self):
        lines = [*HEADER, DE, GEO]
        code, out, after = self.run_helper("retry", lines)
        self.assertEqual((code, out, after), (1, "", lines))
        self.assertEqual(self.pacman_calls(), [])

    def test_an_unknown_verb_fails_on_any_mirrorlist(self):
        for lines in (IMAGE, X86):
            with self.subTest(lines=lines[-1]):
                code, _, after = self.run_helper("rotate", lines)
                self.assertEqual(code, 2)
                self.assertEqual(after, lines)


if __name__ == "__main__":
    unittest.main()
