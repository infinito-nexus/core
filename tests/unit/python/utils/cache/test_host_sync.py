from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

from cli.meta.cache.host_sync.__main__ import main
from utils.cache.apt_sources import apt_targets
from utils.cache.host_sync import (
    APT_DROP_IN,
    APT_DROP_IN_TEXT,
    CACHE_DIR,
    PACMAN_CONF,
    PACMAN_DEFAULT_CACHE,
    SOURCE_PARTS,
    SOURCES_LIST,
    HostSyncError,
    shared_folder,
    state_dir,
    sync,
)
from utils.cache.hosts import CachedHost, CachedRepo, Declarations, declarations
from utils.cache.render import render_artifacts
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache.host import sync as handler
from utils.env.parser import parse_static_env_with_comments

from . import PROJECT_ROOT

NEXUS = "http://127.0.0.1:8081"
SHARED = "/var/cache/infinito/core/cache/shared"
MIRRORS = (
    "http://de.archive.ubuntu.com/ubuntu/ http://ftp.halifax.rwth-aachen.de/ubuntu/"
)
PACMAN_SH = PROJECT_ROOT / "scripts" / "docker" / "cache" / "pacman.sh"
DECLARED = Declarations(
    repos=[
        CachedRepo(
            name="apt-debian",
            flavor="apt",
            upstream="http://deb.debian.org/debian",
            distribution="bookworm",
            mirror="apt-debian-mirror",
        ),
        CachedRepo(
            name="apt-debian-mirror",
            flavor="apt",
            upstream="http://ftp.debian.org/debian",
            distribution="bookworm",
        ),
        CachedRepo(
            name="apt-debian-security",
            flavor="apt",
            upstream="http://deb.debian.org/debian-security",
            distribution="bookworm-security",
            mirror="apt-debian-security-mirror",
        ),
        CachedRepo(
            name="apt-debian-security-mirror",
            flavor="apt",
            upstream="http://security.debian.org/debian-security",
            distribution="bookworm-security",
        ),
        CachedRepo(
            name="apt-ubuntu",
            flavor="apt",
            upstream="${UBUNTU_PRIMARY}",
            distribution="jammy",
            mirror="apt-ubuntu-mirror",
        ),
        CachedRepo(
            name="apt-ubuntu-mirror",
            flavor="apt",
            upstream="${UBUNTU_FALLBACK}",
            distribution="jammy",
        ),
        CachedRepo(
            name="apt-ubuntu-security",
            flavor="apt",
            upstream="${UBUNTU_PRIMARY}",
            distribution="jammy-security",
            mirror="apt-ubuntu-security-mirror",
        ),
        CachedRepo(
            name="apt-ubuntu-security-mirror",
            flavor="apt",
            upstream="${UBUNTU_FALLBACK}",
            distribution="jammy-security",
        ),
        CachedRepo(name="pypi-proxy", flavor="pypi", upstream="https://pypi.org/"),
    ],
    hosts=[
        CachedHost(
            host="archive.ubuntu.com", paths=(("/ubuntu/", "apt-ubuntu"),), listen=(80,)
        ),
        CachedHost(
            host="deb.debian.org",
            paths=(
                ("/debian/", "apt-debian"),
                ("/debian-security/", "apt-debian-security"),
            ),
            listen=(80,),
        ),
        CachedHost(
            host="security.ubuntu.com",
            paths=(("/ubuntu/", "apt-ubuntu-security"),),
            listen=(80,),
        ),
    ],
)
PACMAN = """[options]
#CacheDir    = /var/cache/pacman/pkg/
HoldPkg     = pacman glibc
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

[core]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorlist
"""
DEBIAN = """deb http://deb.debian.org/debian bookworm main contrib
deb-src http://deb.debian.org/debian bookworm main
deb http://deb.debian.org/debian bookworm-updates main
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://security.debian.org/debian-security bookworm-security main
# deb http://deb.debian.org/debian bookworm-backports main
"""
DEBIAN_SYNCED = """deb http://127.0.0.1:8081/repository/apt-debian/ bookworm main contrib
deb http://deb.debian.org/debian bookworm main contrib
deb-src http://deb.debian.org/debian bookworm main
deb http://127.0.0.1:8081/repository/apt-debian/ bookworm-updates main
deb http://deb.debian.org/debian bookworm-updates main
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://127.0.0.1:8081/repository/apt-debian-security/ bookworm-security main
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://security.debian.org/debian-security bookworm-security main
# deb http://deb.debian.org/debian bookworm-backports main
"""
DOCKER = "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable\n"
UBUNTU = """Types: deb deb-src
URIs: http://archive.ubuntu.com/ubuntu/
Suites: jammy jammy-updates
Components: main restricted
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu/
Suites: jammy-security
Components: universe
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mQINBFufwdoBEADv
 -----END PGP PUBLIC KEY BLOCK-----
"""
UBUNTU_COPIES = (
    """Types: deb
URIs: http://127.0.0.1:8081/repository/apt-ubuntu/
Suites: jammy jammy-updates
Components: main restricted
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

""",
    """Types: deb
URIs: http://127.0.0.1:8081/repository/apt-ubuntu-security/
Suites: jammy-security
Components: universe
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mQINBFufwdoBEADv
 -----END PGP PUBLIC KEY BLOCK-----

""",
)
TRIXIE = """Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates trixie-backports
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb
URIs: http://deb.debian.org/debian-security
Suites: trixie-security
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
"""
TRIXIE_COPIES = (
    """Types: deb
URIs: http://127.0.0.1:8081/repository/apt-debian/
Suites: trixie trixie-updates trixie-backports
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

""",
    """Types: deb
URIs: http://127.0.0.1:8081/repository/apt-debian-security/
Suites: trixie-security
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

""",
)
MODERNIZED = """Types: deb
URIs: http://127.0.0.1:8081/repository/apt-debian/
Suites: bookworm
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://127.0.0.1:8081/repository/apt-debian/ http://deb.debian.org/debian
Suites: bookworm-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://127.0.0.1:8081/repository/apt-debian-security/
Suites: bookworm-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""
MODERNIZED_REVERTED = """Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""
NOBLE = """deb http://de.archive.ubuntu.com/ubuntu/ noble main universe
deb http://de.archive.ubuntu.com/ubuntu/ noble-updates main universe
deb http://de.archive.ubuntu.com/ubuntu/ noble-backports main universe
deb http://de.archive.ubuntu.com/ubuntu/ noble-security main universe
"""
SKIPPED = """deb [trusted=true] http://deb.debian.org/debian bookworm main
deb [ allow-insecure=1 ] http://deb.debian.org/debian bookworm contrib
deb [arch=amd64 allow-weak=on] http://deb.debian.org/debian-security bookworm-security main
deb [allow-downgrade-to-insecure=YES] http://security.debian.org/debian-security bookworm-security main
deb ["trusted"=%79es] http://deb.debian.org/debian bookworm non-free
"""
SKIPPED_STANZAS = """Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm
Components: main
Trusted: on

Types: deb
URIs: http://deb.debian.org/debian-security
Suites: bookworm-security
Components: main
Allow-Weak: true

Types: deb
URIs: http://deb.debian.org/debian
Suites: bookworm
Components: contrib
Enabled: false
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir files


class FakeRun:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[list[str]] = []
        self.fetched: list[str] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        error = "E: refused" if self.returncode else ""
        if command[0] == "pacman-conf":
            text = _read(Path(command[2]))
            dirs = [
                m["dir"] for line in text.splitlines() if (m := CACHE_DIR.match(line))
            ]
            listed = "\n".join(dirs or [PACMAN_DEFAULT_CACHE]) + "\n"
            return subprocess.CompletedProcess(command, self.returncode, listed, error)
        options = dict(
            command[i + 1].split("=", 1)
            for i, part in enumerate(command)
            if part == "-o"
        )
        parts = Path(options["Dir::Etc::SourceParts"])
        self.fetched = [
            _read(Path(options["Dir::Etc::SourceList"])),
            *(_read(path) for path in sorted(parts.iterdir())),
        ]
        return subprocess.CompletedProcess(command, self.returncode, "", error)


def _host(root: Path, os_id: str, files: dict[Path, str]) -> None:
    for relative, text in {Path("etc/os-release"): f"ID={os_id}\n", **files}.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()  # nocheck: cache-read tempdir files
        for p in sorted(root.rglob("*"))  # nocheck: project-walk tempdir host
        if p.is_file()
    }


def _sync(root: Path, enabled: bool = True, run: FakeRun | None = None) -> list[str]:
    return sync(
        root,
        enabled=enabled,
        shared=SHARED,
        nexus=NEXUS,
        ubuntu_mirrors=MIRRORS,
        run=run or FakeRun(),
        declared=DECLARED,
    )


def _cache_dirs(text: str) -> list[str]:
    return [m["dir"] for line in text.splitlines() if (m := CACHE_DIR.match(line))]


class HostCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def read(self, relative: Path) -> str:
        return _read(self.root / relative)


class TestArchHost(HostCase):
    def test_host_reads_the_folder_the_stack_publishes_into(self) -> None:
        _host(self.root, "arch", {PACMAN_CONF: PACMAN})
        _sync(self.root)
        stack = self.root / "stack"
        _host(stack, "arch", {PACMAN_CONF: PACMAN})
        subprocess.run(
            [
                "bash",
                str(PACMAN_SH),
                str(stack / PACMAN_CONF),
                str(stack / "shared"),
                "",
            ],
            check=True,
            capture_output=True,
        )
        published = _cache_dirs(self.read(Path("stack") / PACMAN_CONF))[-1]
        self.assertEqual(published, shared_folder(str(stack / "shared")))
        self.assertEqual(
            _cache_dirs(self.read(PACMAN_CONF)),
            [PACMAN_DEFAULT_CACHE, shared_folder(SHARED)],
        )

    def test_host_keeps_downloading_into_its_own_cache(self) -> None:
        own = PACMAN.replace("HoldPkg", "CacheDir = /srv/pkg/\nHoldPkg")
        _host(self.root, "arch", {PACMAN_CONF: own})
        _sync(self.root)
        self.assertEqual(
            _cache_dirs(self.read(PACMAN_CONF)), ["/srv/pkg/", shared_folder(SHARED)]
        )

    def test_signature_checks_and_every_line_stay(self) -> None:
        _host(self.root, "arch", {PACMAN_CONF: PACMAN})
        _sync(self.root)
        synced = self.read(PACMAN_CONF).splitlines()
        added = [line for line in synced if line not in PACMAN.splitlines()]
        self.assertEqual(
            [line for line in synced if line not in added], PACMAN.splitlines()
        )
        self.assertTrue(all(line.startswith("CacheDir = ") for line in added))

    def test_a_rejected_conf_writes_nothing(self) -> None:
        _host(self.root, "arch", {PACMAN_CONF: PACMAN})
        before = _snapshot(self.root)
        with self.assertRaises(HostSyncError):
            _sync(self.root, run=FakeRun(1))
        self.assertEqual(_snapshot(self.root), before)

    def test_a_listed_folder_is_left_alone(self) -> None:
        listed = PACMAN.replace(
            "HoldPkg", f"CacheDir = {shared_folder(SHARED)}\nHoldPkg"
        )
        _host(self.root, "arch", {PACMAN_CONF: listed})
        before = _snapshot(self.root)
        _sync(self.root)
        self.assertEqual(_snapshot(self.root), before)


class TestAptHost(HostCase):
    def test_debian_entries_point_at_nexus_before_their_fallback(self) -> None:
        _host(
            self.root,
            "debian",
            {SOURCES_LIST: DEBIAN, SOURCE_PARTS / "docker.list": DOCKER},
        )
        _sync(self.root)
        self.assertEqual(self.read(SOURCES_LIST), DEBIAN_SYNCED)
        self.assertEqual(self.read(SOURCE_PARTS / "docker.list"), DOCKER)

    def test_entries_without_signature_checks_or_over_https_stay(self) -> None:
        kept = "deb [trusted=yes] http://deb.debian.org/debian bookworm main\ndeb https://deb.debian.org/debian bookworm main\n"
        _host(self.root, "debian", {SOURCES_LIST: kept})
        before = _snapshot(self.root)
        self.assertEqual(
            _sync(self.root),
            ["no host source is one the cache serves; nothing written"],
        )
        self.assertEqual(_snapshot(self.root), before)

    def test_deb822_stanzas_get_a_deb_only_copy_with_every_field(self) -> None:
        _host(self.root, "ubuntu", {SOURCE_PARTS / "ubuntu.sources": UBUNTU})
        _sync(self.root)
        first, second = UBUNTU.split("\n\n")
        expected = f"{UBUNTU_COPIES[0]}{first}\n\n{UBUNTU_COPIES[1]}{second}"
        self.assertEqual(self.read(SOURCE_PARTS / "ubuntu.sources"), expected)

    def test_apt_keeps_no_second_copy_of_a_package(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        _sync(self.root)
        self.assertEqual(self.read(APT_DROP_IN), APT_DROP_IN_TEXT)

    def test_the_update_fetches_the_copies_alone(self) -> None:
        listed = "deb http://archive.ubuntu.com/ubuntu/ jammy main\ndeb http://archive.ubuntu.com/ubuntu/ jammy-updates main\n"
        _host(
            self.root,
            "ubuntu",
            {SOURCES_LIST: listed, SOURCE_PARTS / "ubuntu.sources": UBUNTU},
        )
        run = FakeRun()
        _sync(self.root, run=run)
        copies = (
            "deb http://127.0.0.1:8081/repository/apt-ubuntu/ jammy main\n"
            "deb http://127.0.0.1:8081/repository/apt-ubuntu/ jammy-updates main\n"
        )
        self.assertEqual(run.fetched, [copies, "".join(UBUNTU_COPIES)])

    def test_the_update_fails_on_a_transient_error_too(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        run = FakeRun()
        _sync(self.root, run=run)
        update = next(call for call in run.calls if call[0] == "apt-get")
        self.assertIn(("-o", "APT::Update::Error-Mode=any"), list(pairwise(update)))

    def test_every_spelling_of_an_insecure_or_disabled_source_stays(self) -> None:
        _host(
            self.root,
            "debian",
            {SOURCES_LIST: SKIPPED, SOURCE_PARTS / "skipped.sources": SKIPPED_STANZAS},
        )
        before = _snapshot(self.root)
        self.assertEqual(
            _sync(self.root),
            ["no host source is one the cache serves; nothing written"],
        )
        self.assertEqual(_snapshot(self.root), before)

    def test_every_stock_suite_of_a_trixie_host_points_at_nexus(self) -> None:
        _host(self.root, "debian", {SOURCE_PARTS / "debian.sources": TRIXIE})
        _sync(self.root)
        first, second = TRIXIE.split("\n\n")
        expected = f"{TRIXIE_COPIES[0]}{first}\n\n{TRIXIE_COPIES[1]}{second}"
        self.assertEqual(self.read(SOURCE_PARTS / "debian.sources"), expected)

    def test_each_pocket_of_a_shared_ubuntu_mirror_reaches_its_repository(
        self,
    ) -> None:
        _host(self.root, "ubuntu", {SOURCES_LIST: NOBLE})
        _sync(self.root)
        copied = [
            line.split()[1]
            for line in self.read(SOURCES_LIST).splitlines()
            if line.split()[1].startswith(NEXUS)
        ]
        repository = f"{NEXUS}/repository"
        self.assertEqual(
            copied,
            [
                f"{repository}/apt-ubuntu/",
                f"{repository}/apt-ubuntu/",
                f"{repository}/apt-ubuntu/",
                f"{repository}/apt-ubuntu-security/",
            ],
        )

    def test_a_country_alias_of_a_proxied_archive_routes_like_it(self) -> None:
        listed = (
            "deb http://us.archive.ubuntu.com/ubuntu/ resolute main\n"
            "deb http://ports.ubuntu.com/ubuntu-ports resolute main\n"
            "deb http://archive.ubuntu.com.example/ubuntu/ resolute main\n"
        )
        _host(self.root, "ubuntu", {SOURCES_LIST: listed})
        _sync(self.root)
        copy = "deb http://127.0.0.1:8081/repository/apt-ubuntu/ resolute main\n"
        self.assertEqual(self.read(SOURCES_LIST), copy + listed)

    def test_two_archives_never_share_a_copied_repository_and_suite(self) -> None:
        listed = (
            "deb http://archive.ubuntu.com/ubuntu/ noble main\n"
            "deb [signed-by=/etc/apt/keyrings/mirror.gpg] http://de.archive.ubuntu.com/ubuntu/ noble universe\n"
            "deb http://archive.ubuntu.com/ubuntu/ noble restricted\n"
        )
        _host(self.root, "ubuntu", {SOURCES_LIST: listed})
        run = FakeRun()
        _sync(self.root, run=run)
        self.assertEqual(
            run.fetched[0],
            "deb http://127.0.0.1:8081/repository/apt-ubuntu/ noble main\n"
            "deb http://127.0.0.1:8081/repository/apt-ubuntu/ noble restricted\n",
        )

    def test_the_first_file_apt_reads_claims_a_repository_and_suite(self) -> None:
        mirror = (
            "Types: deb\n"
            "URIs: http://de.archive.ubuntu.com/ubuntu/\n"
            "Suites: noble\n"
            "Components: universe\n"
            "Signed-By: /etc/apt/keyrings/mirror.gpg\n"
        )
        main = "deb http://archive.ubuntu.com/ubuntu/ noble main\n"
        _host(
            self.root,
            "ubuntu",
            {
                SOURCE_PARTS / "00-mirror.sources": mirror,
                SOURCE_PARTS / "50-main.list": main,
            },
        )
        _sync(self.root)
        self.assertEqual(self.read(SOURCE_PARTS / "50-main.list"), main)
        self.assertIn(
            f"URIs: {NEXUS}/repository/apt-ubuntu/\n",
            self.read(SOURCE_PARTS / "00-mirror.sources"),
        )

    def test_a_suite_its_archive_has_no_repository_for_stays(self) -> None:
        listed = (
            "deb http://security.ubuntu.com/ubuntu/ noble main\n"
            "deb http://deb.debian.org/debian-security trixie main\n"
        )
        _host(self.root, "ubuntu", {SOURCES_LIST: listed})
        before = _snapshot(self.root)
        self.assertEqual(
            _sync(self.root),
            ["no host source is one the cache serves; nothing written"],
        )
        self.assertEqual(_snapshot(self.root), before)

    def test_a_failing_update_writes_nothing(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        before = _snapshot(self.root)
        with self.assertRaises(HostSyncError):
            _sync(self.root, run=FakeRun(100))
        self.assertEqual(_snapshot(self.root), before)


class TestRevert(HostCase):
    def test_off_without_a_sync_touches_nothing(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        before = _snapshot(self.root)
        run = FakeRun()
        self.assertEqual(_sync(self.root, enabled=False, run=run), [])
        self.assertEqual(_snapshot(self.root), before)
        self.assertEqual(run.calls, [])

    def test_off_restores_every_byte(self) -> None:
        for os_id, files in (
            ("arch", {PACMAN_CONF: PACMAN}),
            ("debian", {SOURCES_LIST: DEBIAN}),
        ):
            with self.subTest(os_id=os_id):
                root = self.root / os_id
                _host(root, os_id, files)
                before = _snapshot(root)
                _sync(root)
                self.assertNotEqual(_snapshot(root), before)
                _sync(root, enabled=False)
                self.assertEqual(_snapshot(root), before)
                self.assertFalse(state_dir(root).exists())

    def test_a_pacman_conf_changed_since_the_sync_is_kept(self) -> None:
        _host(self.root, "arch", {PACMAN_CONF: PACMAN})
        _sync(self.root)
        edited = (
            self.read(PACMAN_CONF) + "\n[extra]\nInclude = /etc/pacman.d/mirrorlist\n"
        )
        (self.root / PACMAN_CONF).write_text(edited, encoding="utf-8")
        with self.assertRaises(HostSyncError):
            _sync(self.root, enabled=False)
        self.assertEqual(self.read(PACMAN_CONF), edited)

    def test_an_apt_file_changed_since_the_sync_keeps_all_but_the_copies(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        _sync(self.root)
        added = (
            "deb http://example.org/debian trixie main\n"
            "deb http://127.0.0.1:8081/repository/apt-debian-mirror/ trixie main\n"
        )
        upgraded = self.read(SOURCES_LIST).replace("bookworm", "trixie") + added
        (self.root / SOURCES_LIST).write_text(upgraded, encoding="utf-8")
        reverted = _sync(self.root, enabled=False)
        self.assertEqual(
            self.read(SOURCES_LIST), DEBIAN.replace("bookworm", "trixie") + added
        )
        self.assertIn(
            f"left {self.root / SOURCES_LIST} as it is: changed since the sync",
            reverted,
        )
        self.assertFalse((self.root / APT_DROP_IN).exists())
        self.assertFalse(state_dir(self.root).exists())

    def test_a_modernized_host_loses_every_copy_and_keeps_its_own_sources(
        self,
    ) -> None:
        backports = "deb http://deb.debian.org/debian bookworm-backports main\n"
        _host(
            self.root,
            "debian",
            {SOURCES_LIST: DEBIAN, SOURCE_PARTS / "backports.list": backports},
        )
        _sync(self.root)
        (self.root / SOURCES_LIST).rename(self.root / f"{SOURCES_LIST}.bak")
        listed = self.root / SOURCE_PARTS / "backports.list"
        listed.rename(listed.with_name("backports.list.bak"))
        _host(self.root, "debian", {SOURCE_PARTS / "debian.sources": MODERNIZED})
        _sync(self.root, enabled=False)
        self.assertEqual(
            self.read(SOURCE_PARTS / "debian.sources"), MODERNIZED_REVERTED
        )
        self.assertEqual(self.read(Path(f"{SOURCES_LIST}.bak")), DEBIAN)
        self.assertEqual(self.read(SOURCE_PARTS / "backports.list.bak"), backports)
        self.assertFalse((self.root / SOURCES_LIST).exists())
        self.assertFalse(listed.exists())
        self.assertFalse(state_dir(self.root).exists())

    def test_an_added_source_loses_each_copy_and_keeps_its_comments(self) -> None:
        nexus = f"{NEXUS}/repository/apt-debian/"
        stanzas = (
            "# the cache first\n"
            f"Types: deb\nURIs: {nexus}\nSuites: trixie\nComponents: main\n\n"
            "Types: deb deb-src\nURIs: http://deb.debian.org/debian\n"
            f"# the cache as a second source\n {nexus}\n"
            "Suites: trixie\nComponents: main\n"
        )
        listed = (
            f"deb-src {nexus} trixie main\n"
            "deb-src http://deb.debian.org/debian trixie main\n"
        )
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        _sync(self.root)
        _host(
            self.root,
            "debian",
            {
                SOURCE_PARTS / "local.sources": stanzas,
                SOURCE_PARTS / "local.list": listed,
            },
        )
        _sync(self.root, enabled=False)
        self.assertEqual(
            self.read(SOURCE_PARTS / "local.sources"),
            "# the cache first\n\n"
            "Types: deb deb-src\nURIs: http://deb.debian.org/debian\n"
            "# the cache as a second source\n"
            "Suites: trixie\nComponents: main\n",
        )
        self.assertEqual(
            self.read(SOURCE_PARTS / "local.list"),
            "deb-src http://deb.debian.org/debian trixie main\n",
        )

    def test_a_source_untouched_since_the_sync_keeps_its_own_nexus_entry(
        self,
    ) -> None:
        own = "deb http://127.0.0.1:8081/repository/apt-debian/ bookworm main\n"
        _host(
            self.root,
            "debian",
            {SOURCES_LIST: DEBIAN, SOURCE_PARTS / "own.list": own},
        )
        _sync(self.root)
        upgraded = self.read(SOURCES_LIST).replace("bookworm", "trixie")
        (self.root / SOURCES_LIST).write_text(upgraded, encoding="utf-8")
        _sync(self.root, enabled=False)
        self.assertEqual(self.read(SOURCE_PARTS / "own.list"), own)
        self.assertEqual(self.read(SOURCES_LIST), DEBIAN.replace("bookworm", "trixie"))

    def test_a_source_put_back_by_hand_keeps_its_own_nexus_entry(self) -> None:
        own = DEBIAN + "deb http://127.0.0.1:8081/repository/apt-debian/ trixie main\n"
        _host(self.root, "debian", {SOURCES_LIST: own})
        _sync(self.root)
        self.assertNotEqual(self.read(SOURCES_LIST), own)
        (self.root / SOURCES_LIST).write_text(own, encoding="utf-8")
        _sync(self.root, enabled=False)
        self.assertEqual(self.read(SOURCES_LIST), own)
        self.assertFalse(state_dir(self.root).exists())

    def test_a_rerun_is_idempotent(self) -> None:
        _host(self.root, "debian", {SOURCES_LIST: DEBIAN})
        _sync(self.root)
        once = _snapshot(self.root)
        _sync(self.root)
        self.assertEqual(_snapshot(self.root), once)

    def test_other_hosts_are_refused(self) -> None:
        _host(self.root, "manjaro", {PACMAN_CONF: PACMAN})
        before = _snapshot(self.root)
        with self.assertRaises(HostSyncError):
            _sync(self.root)
        self.assertEqual(_snapshot(self.root), before)


class TestTargets(unittest.TestCase):
    def test_every_declared_archive_maps_each_pocket_to_its_repository(self) -> None:
        targets = apt_targets(NEXUS, MIRRORS, DECLARED)
        named = {
            archive: {
                key: target.url.rsplit("/", 2)[-2] for key, target in pockets.items()
            }
            for archive, pockets in targets.items()
        }
        ubuntu = {"": "apt-ubuntu", "security": "apt-ubuntu-security"}
        self.assertEqual(
            named,
            {
                "deb.debian.org/debian": {"": "apt-debian"},
                "ftp.debian.org/debian": {"": "apt-debian"},
                "deb.debian.org/debian-security": {"security": "apt-debian-security"},
                "security.debian.org/debian-security": {
                    "security": "apt-debian-security"
                },
                "de.archive.ubuntu.com/ubuntu": ubuntu,
                "ftp.halifax.rwth-aachen.de/ubuntu": ubuntu,
                "archive.ubuntu.com/ubuntu": {"": "apt-ubuntu"},
                "security.ubuntu.com/ubuntu": {"security": "apt-ubuntu-security"},
            },
        )

    def test_the_repository_declarations_serve_each_primary_apt_repository(
        self,
    ) -> None:
        declared = declarations()
        siblings = {repo.mirror for repo in declared.repos}
        primary = {
            repo.name
            for repo in declared.repos
            if repo.flavor == "apt" and repo.name not in siblings
        }
        served = {
            target.url.rsplit("/", 2)[-2]
            for pockets in apt_targets(NEXUS, MIRRORS, declared).values()
            for target in pockets.values()
        }
        self.assertTrue(primary)
        self.assertEqual(served, primary)


class TestCommandLine(unittest.TestCase):
    def test_a_flag_other_than_true_or_false_is_refused(self) -> None:
        with self.assertRaises(SystemExit) as exit_, patch("sys.stderr"):
            main(["--sync", "yes"])
        self.assertEqual(exit_.exception.code, 2)

    def test_a_refused_sync_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as scratch, patch("sys.stderr"):
            _host(Path(scratch), "manjaro", {})
            self.assertEqual(main(["--sync", "true", "--root", scratch]), 1)
            self.assertEqual(main(["--sync", "false", "--root", scratch]), 0)


class TestKeyRendersNothing(unittest.TestCase):
    def test_every_cache_render_is_the_same_on_and_off(self) -> None:
        renders = []
        for value in ("false", "true"):
            with (
                tempfile.TemporaryDirectory() as scratch,
                patch.dict(os.environ, {handler.KEY: value}),
            ):
                root = Path(scratch)
                render_artifacts(
                    root, root / "compose" / "package-cache" / "upstreams.conf"
                )
                renders.append(_snapshot(root))
        self.assertTrue(renders[0])
        self.assertEqual(renders[0], renders[1])

    def test_the_default_is_off(self) -> None:
        static, comments = parse_static_env_with_comments(PROJECT_ROOT / "default.env")
        builder = EnvBuilder()
        context = BuildContext(
            static=static,
            static_comments=comments,
            repo_root=PROJECT_ROOT,
            on_gha=False,
            on_act=False,
        )
        with patch.dict(os.environ, {handler.KEY: ""}):
            handler.apply(builder, context)
        self.assertEqual(builder.values, {handler.KEY: "false"})
        self.assertTrue(builder.comments[handler.KEY])


if __name__ == "__main__":
    unittest.main()
