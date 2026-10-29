from __future__ import annotations

import configparser
import hashlib
import posixpath
import re
import unittest
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATES = PROJECT_ROOT / "roles" / "web-app-nextcloud" / "templates"
FILES = PROJECT_ROOT / "roles" / "web-app-nextcloud" / "files"

SIGNALING_SECRET = "base64:signaling-fixture-secret"
INTERNAL_SECRET = "base64:internal-fixture-secret"
RECORDING_SECRET = "recording-fixture-secret"

VARIABLES = {
    "NEXTCLOUD_HPB_SIGNALING_PORT": 8081,
    "NEXTCLOUD_HPB_SIGNALING_SECRET": SIGNALING_SECRET,
    "NEXTCLOUD_HPB_INTERNAL_SECRET": INTERNAL_SECRET,
    "NEXTCLOUD_HPB_BACKEND_URL": "https://next.example.org",
    "NEXTCLOUD_HPB_SIGNALING_LOCATION": "/standalone-signaling/",
    "NEXTCLOUD_HPB_SIGNALING_MAX_STREAM_BITRATE": 1048576,
    "NEXTCLOUD_HPB_SIGNALING_MAX_SCREEN_BITRATE": 2097152,
    "NEXTCLOUD_HPB_NATS_URL": "nats://talk_nats:4222",
    "NEXTCLOUD_HPB_JANUS_URL": "ws://talk:8188",
    "NEXTCLOUD_RECORDING_PORT": 1234,
    "NEXTCLOUD_RECORDING_SECRET": RECORDING_SECRET,
    "NEXTCLOUD_RECORDING_DIRECTORY": "/tmp",
    "NEXTCLOUD_HPB_MEDIA_PORT_START": 61000,
    "NEXTCLOUD_HPB_MEDIA_PORT_END": 61999,
    "NEXTCLOUD_HPB_MEDIA_PUBLIC_IP": "203.0.113.7",
    "NEXTCLOUD_HPB_JANUS_BASE_IMAGE": "alpine",
    "NEXTCLOUD_HPB_JANUS_BASE_VERSION": "3.23.3",
    "NEXTCLOUD_HPB_JANUS_REPOSITORY": "https://github.com/meetecho/janus-gateway.git",
    "NEXTCLOUD_HPB_JANUS_REF": "v1.4.0",
    "NEXTCLOUD_HPB_JANUS_CONFIG_TARGET": "/usr/local/etc/janus/janus.jcfg",
    "NEXTCLOUD_RECORDING_BASE_IMAGE": "python",
    "NEXTCLOUD_RECORDING_BASE_VERSION": "3.14.3-alpine3.23",
    "NEXTCLOUD_RECORDING_REPOSITORY": "https://github.com/nextcloud/nextcloud-talk-recording.git",
    "NEXTCLOUD_RECORDING_REF": "v0.2.1",
    "NEXTCLOUD_RECORDING_USER_ID": 122,
    "NEXTCLOUD_RECORDING_CONFIG_TARGET": "/conf/recording.conf",
    "NEXTCLOUD_RECORDING_CA_CERT": "/tmp/infinito/ca/root-ca.crt",
}

AIO_SIGNALING = {
    "http": {"listen": "0.0.0.0:8081"},
    "app": {"debug": "false"},
    "clients": {"internalsecret": INTERNAL_SECRET},
    "backend": {
        "backends": "backend-1",
        "allowall": "false",
        "timeout": "10",
        "connectionsperhost": "8",
        "skipverify": "false",
    },
    "backend-1": {
        "urls": "https://next.example.org",
        "secret": SIGNALING_SECRET,
        "maxstreambitrate": "1048576",
        "maxscreenbitrate": "2097152",
    },
    "nats": {"url": "nats://127.0.0.1:4222"},
    "mcu": {
        "type": "janus",
        "url": "ws://127.0.0.1:8188",
        "maxstreambitrate": "1048576",
        "maxscreenbitrate": "2097152",
    },
}

AIO_RECORDING = {
    "logs": {"level": "30"},
    "http": {"listen": "0.0.0.0:1234"},
    "backend": {
        "allowall": "false",
        "secret": RECORDING_SECRET,
        "backends": "backend-1",
        "skipverify": "false",
        "maxmessagesize": "1024",
        "videowidth": "1920",
        "videoheight": "1080",
        "directory": "/tmp",
    },
    "backend-1": {
        "url": "https://next.example.org",
        "secret": RECORDING_SECRET,
        "skipverify": "false",
    },
    "signaling": {"signalings": "signaling-1"},
    "signaling-1": {
        "url": "https://next.example.org/standalone-signaling/",
        "internalsecret": INTERNAL_SECRET,
    },
    "ffmpeg": {"extensionaudio": ".ogg", "extensionvideo": ".webm"},
    "recording": {
        "browser": "firefox",
        "driverPath": "/usr/bin/geckodriver",
        "browserPath": "/usr/bin/firefox",
    },
}

STOCK_JANUS = [
    "general:{",
    'configs_folder="/usr/local/etc/janus"',
    'plugins_folder="/usr/local/lib/janus/plugins"',
    'transports_folder="/usr/local/lib/janus/transports"',
    'events_folder="/usr/local/lib/janus/events"',
    'loggers_folder="/usr/local/lib/janus/loggers"',
    "debug_level=4",
    'admin_secret="janusoverlord"',
    "protected_folders=[",
    *[
        f'"{folder}",'
        for folder in (
            "/bin",
            "/boot",
            "/dev",
            "/etc",
            "/initrd",
            "/lib",
            "/lib32",
            "/lib64",
            "/proc",
            "/sbin",
            "/sys",
            "/usr",
            "/var",
            "/opt/janus/bin",
            "/opt/janus/etc",
            "/opt/janus/include",
            "/opt/janus/lib",
            "/opt/janus/lib32",
            "/opt/janus/lib64",
        )
    ],
    '"/opt/janus/sbin"',
    "]",
    "}",
    "certificates:{",
    "}",
    "media:{",
    "}",
    "nat:{",
    'ice_ignore_list="vmnet"',
    "}",
    "plugins:{",
    "}",
    "transports:{",
    "}",
    "loggers:{",
    "}",
    "events:{",
    "}",
]


def _render(source: str, **overrides) -> str:
    env = Environment(
        trim_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["hash"] = lambda value, algorithm: hashlib.new(
        algorithm, str(value).encode()
    ).hexdigest()
    env.filters["bool"] = bool
    env.filters["dirname"] = posixpath.dirname
    return env.from_string(source).render({**VARIABLES, **overrides})


def _template(name: str) -> str:
    return read_text(str(TEMPLATES / name))


def _build_args(dockerfile: str) -> str:
    compose = _template("compose.yml.j2")
    args: dict[str, str] = {}
    for arg in re.findall(r"^ARG (\w+)$", dockerfile, re.MULTILINE):
        passed = re.search(rf'^\s+{arg}: "(.*)"$', compose, re.MULTILINE)
        if passed is None:
            raise AssertionError(f"compose.yml.j2 passes no build arg {arg}")
        args[arg] = _render(passed.group(1))
    return re.sub(r"\$\{(\w+)\}", lambda match: args[match.group(1)], dockerfile)


def _build(name: str) -> str:
    return _build_args(read_text(str(FILES / "Dockerfiles" / name / "Dockerfile")))


def _ini(text: str) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(text)
    return {section: dict(parser[section]) for section in parser.sections()}


def _settings(text: str) -> list[str]:
    return [joined for line in text.splitlines() if (joined := "".join(line.split()))]


class TestSignalingConfig(unittest.TestCase):
    def test_matches_what_the_aio_start_script_wrote_apart_from_the_split(self):
        rendered = _ini(_render(_template("signaling.conf.j2")))
        sessions = rendered.pop("sessions")
        expected = {
            **AIO_SIGNALING,
            "nats": {"url": "nats://talk_nats:4222"},
            "mcu": {**AIO_SIGNALING["mcu"], "url": "ws://talk:8188"},
        }
        self.assertEqual(rendered, expected)
        self.assertEqual(sorted(sessions), ["blockkey", "hashkey"])

    def test_session_keys_have_the_shape_aio_generated_and_stay_stable(self):
        first = _ini(_render(_template("signaling.conf.j2")))["sessions"]
        second = _ini(_render(_template("signaling.conf.j2")))["sessions"]
        self.assertEqual(first, second)
        for key in ("hashkey", "blockkey"):
            self.assertRegex(first[key], r"^[0-9a-f]{32}$")
        self.assertNotEqual(first["hashkey"], first["blockkey"])
        self.assertNotIn(first["hashkey"], SIGNALING_SECRET)

    def test_negative_control_another_signaling_secret_changes_the_keys(self):
        first = _ini(_render(_template("signaling.conf.j2")))["sessions"]
        other = _ini(
            _render(
                _template("signaling.conf.j2"),
                NEXTCLOUD_HPB_SIGNALING_SECRET="base64:another-secret",
            )
        )["sessions"]
        self.assertNotEqual(first["hashkey"], other["hashkey"])
        self.assertNotEqual(first["blockkey"], other["blockkey"])

    def test_negative_control_a_changed_setting_breaks_parity(self):
        drifted = _template("signaling.conf.j2").replace(
            "allowall = false", "allowall = true"
        )
        self.assertNotEqual(drifted, _template("signaling.conf.j2"))
        rendered = _ini(_render(drifted))
        rendered.pop("sessions")
        self.assertNotEqual(rendered["backend"], AIO_SIGNALING["backend"])


class TestRecordingConfig(unittest.TestCase):
    def test_matches_what_the_aio_start_script_wrote(self):
        self.assertEqual(_ini(_render(_template("recording.conf.j2"))), AIO_RECORDING)

    def test_negative_control_a_dropped_setting_breaks_parity(self):
        drifted = _template("recording.conf.j2").replace("maxmessagesize = 1024\n", "")
        self.assertNotEqual(drifted, _template("recording.conf.j2"))
        self.assertNotEqual(_ini(_render(drifted)), AIO_RECORDING)


class TestJanusConfig(unittest.TestCase):
    def test_without_direct_media_it_equals_the_stock_janus_config(self):
        rendered = _render(_template("janus.jcfg.j2"), NEXTCLOUD_HPB_MEDIA_DIRECT=False)
        self.assertEqual(_settings(rendered), STOCK_JANUS)

    def test_direct_media_adds_exactly_the_three_overrides(self):
        rendered = _settings(
            _render(_template("janus.jcfg.j2"), NEXTCLOUD_HPB_MEDIA_DIRECT=True)
        )
        expected = list(STOCK_JANUS)
        expected.insert(expected.index("media:{") + 1, 'rtp_port_range="61000-61999"')
        expected.insert(expected.index("nat:{") + 1, 'nat_1_1_mapping="203.0.113.7"')
        expected.insert(expected.index("nat:{") + 2, "keep_private_host=true")
        self.assertEqual(rendered, expected)

    def test_negative_control_an_unguarded_override_breaks_the_stock_config(self):
        drifted = _template("janus.jcfg.j2").replace(
            "{% if NEXTCLOUD_HPB_MEDIA_DIRECT | bool %}\n\trtp_port_range",
            "{% if true %}\n\trtp_port_range",
        )
        self.assertNotEqual(drifted, _template("janus.jcfg.j2"))
        rendered = _render(drifted, NEXTCLOUD_HPB_MEDIA_DIRECT=False)
        self.assertNotEqual(_settings(rendered), STOCK_JANUS)


class TestTalkDockerfiles(unittest.TestCase):
    AIO_JANUS_BUILD_PACKAGES: ClassVar[list[str]] = [
        "ca-certificates",
        "git",
        "autoconf",
        "automake",
        "build-base",
        "pkgconfig",
        "libtool",
        "util-linux",
        "glib-dev",
        "zlib-dev",
        "openssl-dev",
        "jansson-dev",
        "libnice-dev",
        "libconfig-dev",
        "libsrtp-dev",
        "libusrsctp-dev",
        "gengetopt-dev",
        "libwebsockets-dev",
    ]

    def test_janus_builds_the_pinned_tag_on_the_pinned_base(self):
        rendered = _build("Janus")
        self.assertEqual(
            re.findall(r"^FROM (\S+)", rendered, re.MULTILINE),
            ["alpine:3.23.3", "alpine:3.23.3"],
        )
        self.assertIn(
            'git clone --recursive "https://github.com/meetecho/janus-gateway.git" '
            '--depth=1 --single-branch --branch "v1.4.0" /src',
            rendered,
        )
        self.assertIn(
            "/src/configure --disable-rabbitmq --disable-mqtt --disable-boringssl",
            rendered,
        )
        build_stage = rendered.split("\nFROM ")[1]
        for package in self.AIO_JANUS_BUILD_PACKAGES:
            with self.subTest(package=package):
                self.assertRegex(build_stage, rf"\n\s+{re.escape(package)}( \\|;)")
        self.assertIn(
            'ENTRYPOINT ["janus", "--disable-colors", "--log-stdout", '
            '"--full-trickle", "--debug-level", "3"]',
            rendered,
        )

    def test_recording_installs_the_pinned_release_on_the_pinned_base(self):
        rendered = _build("Recording")
        self.assertEqual(
            re.findall(r"^FROM (\S+)", rendered, re.MULTILINE),
            ["python:3.14.3-alpine3.23"],
        )
        self.assertIn(
            'git clone --recursive "https://github.com/nextcloud/nextcloud-talk-recording.git" '
            '--depth=1 --single-branch --branch "v0.2.1" /src',
            rendered,
        )
        self.assertIn('useradd -d "/tmp" --system recording -u "122"', rendered)
        self.assertIn('mkdir -p "/conf"', rendered)
        self.assertIn(
            """printf '{"policies":{"Certificates":{"Install":["%s"]}}}\\n' """
            '"/tmp/infinito/ca/root-ca.crt" > /etc/firefox/policies/policies.json',
            rendered,
        )
        self.assertIn("USER 122", rendered)
        self.assertIn(
            'ENTRYPOINT ["python", "-m", "nextcloud.talk.recording"]', rendered
        )

    def test_the_compose_command_points_each_binary_at_its_rendered_config(self):
        compose = _template("compose.yml.j2")
        self.assertIn(
            'command: ["--config={{ NEXTCLOUD_HPB_JANUS_CONFIG_TARGET }}"]', compose
        )
        self.assertIn(
            'command: ["--config", "{{ NEXTCLOUD_RECORDING_CONFIG_TARGET }}"]', compose
        )

    def test_no_image_ships_a_start_script_that_writes_its_config(self):
        for name in ("Janus", "Recording"):
            with self.subTest(dockerfile=name):
                rendered = _build(name)
                self.assertNotRegex(rendered, r"ENTRYPOINT \[\"[^\"]*\.sh\"")
                self.assertNotIn(
                    "COPY",
                    rendered.split("\nFROM ")[-1].replace("COPY --from=build", ""),
                )
                self.assertNotIn("SECRET", rendered)

    def test_negative_control_an_arg_compose_does_not_pass_fails_the_build(self):
        with self.assertRaisesRegex(AssertionError, "JANUS_UNPASSED"):
            _build_args("ARG JANUS_UNPASSED\nFROM ${JANUS_UNPASSED}\n")


if __name__ == "__main__":
    unittest.main()
