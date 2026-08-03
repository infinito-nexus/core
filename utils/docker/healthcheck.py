"""Container healthcheck probes, one class per flavor.

Pure and Ansible free: the lookup plugin resolves a service's configuration
and hands it to :func:`build`, which picks the flavor and renders the
compose ``healthcheck`` mapping.

All probes target the loopback inside the container, so they prove that
this container serves, not that some replica somewhere does.
"""

from __future__ import annotations

from typing import Any, ClassVar

from utils.cache.yaml import dump_yaml_str

_HTTP_REQUEST = (
    "echo -e 'GET /{path} HTTP/1.1\\r\\nHost: localhost\\r\\n"
    "Connection: close\\r\\n\\r\\n' >&3"
)


class Probe:
    """Base for every flavor: timings plus the argv docker executes."""

    flavor: ClassVar[str] = ""
    interval: ClassVar[str] = "30s"
    timeout: ClassVar[str] = "5s"
    retries: ClassVar[int] = 3
    start_period: ClassVar[str] = "30s"

    def __init__(self, **context: Any) -> None:
        self.port = context.get("port", "")
        self.path = context.get("path", "")
        self.hostname = context.get("hostname")
        self.samples = context.get("samples", 1)
        self.context = context

    @property
    def url(self) -> str:
        return f"http://127.0.0.1{f':{self.port}' if self.port else ''}/{self.path}"

    def test(self) -> list[str]:
        raise NotImplementedError

    def block(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Assemble the healthcheck mapping.

        Args:
            overrides: service level values that win over the flavor defaults.
        """
        block: dict[str, Any] = {"test": self.test()}
        for key in ("interval", "timeout", "retries", "start_period"):
            block[key] = overrides.get(key, getattr(self, key))
        return block


class Custom(Probe):
    """A service that spells its probe out instead of picking a flavor."""

    flavor = "custom"

    def test(self) -> list[str]:
        return list(self.context["test"])


class Curl(Probe):
    """curl against the loopback, optionally sampling the whole replica pool.

    ``retries`` counts CONSECUTIVE failures, and a request that leaves the
    container is load balanced across the service VIP. With N replicas and
    one of them alive, a round robin never produces more than N-1 failures
    in a row, so a streak based check is arithmetically blind to losing all
    but one backend. Chaining ``samples`` requests into a single probe makes
    one probe cover the whole pool instead.
    """

    flavor = "curl"
    interval = "1m"
    timeout = "10s"

    def test(self) -> list[str]:
        if self.samples > 1:
            host = f"-H 'Host: {self.hostname}' " if self.hostname else ""
            return [
                "CMD-SHELL",
                " && ".join([f"curl -f {host}{self.url}"] * self.samples),
            ]
        argv = ["CMD", "curl", "-f"]
        if self.hostname:
            argv += ["-H", f"Host: {self.hostname}"]
        return [*argv, self.url]


class Wget(Probe):
    flavor = "wget"
    interval = "1m"
    timeout = "10s"

    def test(self) -> list[str]:
        return ["CMD", "wget", "--spider", "--proxy=off", self.url]


class Http(Probe):
    """Whichever of wget or curl the image happens to ship."""

    flavor = "http"
    retries = 5
    start_period = "20s"

    def test(self) -> list[str]:
        return [
            "CMD-SHELL",
            f"wget -qO- {self.url} >/dev/null || curl -fsS {self.url} >/dev/null",
        ]


class Tcp(Probe):
    """Speaks HTTP over a bash socket, for images without curl or wget."""

    flavor = "tcp"

    def request(self) -> str:
        return _HTTP_REQUEST.format(path=self.path)

    def test(self) -> list[str]:
        return [
            "CMD",
            "bash",
            "-c",
            (
                f"exec 3<>/dev/tcp/localhost/{self.port} && {self.request()} && "
                "cat <&3 | grep -q 'HTTP/1'"
            ),
        ]


class HttpStatus(Tcp):
    """Like :class:`Tcp`, but insists the status line is 2xx or 3xx."""

    flavor = "http_status"

    def test(self) -> list[str]:
        return [
            "CMD",
            "bash",
            "-c",
            (
                f"exec 3<>/dev/tcp/localhost/{self.port} && {self.request()} && "
                "head -n1 <&3 | grep -qE '^HTTP/1\\.[01] [23][0-9][0-9]'"
            ),
        ]


class Nc(Probe):
    flavor = "nc"
    timeout = "3s"
    start_period = "10s"

    def test(self) -> list[str]:
        return ["CMD-SHELL", f"nc -z localhost {self.port} || exit 1"]


class MsmtpCurl(Probe):
    """Probes http, and on the first run also sends one test mail.

    The /tmp/email_sent marker keeps a repeating probe from tripping SMTP
    rate limits, and a disabled email provider drops the mail branch so an
    unrelated SMTP outage cannot flap the container into unhealthy.
    """

    flavor = "msmtp_curl"
    timeout = "20s"
    retries = 5
    start_period = "120s"

    def test(self) -> list[str]:
        mail = ""
        if self.context.get("email_enabled"):
            domain = self.context.get("domain", "")
            blackhole = self.context.get("blackhole", "")
            mail = (
                "if [ ! -f /tmp/email_sent ]; then "
                f"echo 'Subject: testmessage from {domain}\\n\\nSUCCESSFULL' "
                f"| msmtp -t {blackhole} && touch /tmp/email_sent; fi && "
            )
        return ["CMD-SHELL", f"{mail}curl -f {self.url} || exit 1"]


PROBES: dict[str, type[Probe]] = {
    probe.flavor: probe for probe in (Curl, Wget, Http, Tcp, HttpStatus, Nc, MsmtpCurl)
}


def known_flavors() -> str:
    return ", ".join(sorted(PROBES))


def build(flavor: str, overrides: dict[str, Any], **context: Any) -> str:
    """Render a service's healthcheck block as YAML, starting at column zero.

    Args:
        flavor: key into PROBES, or empty to use an explicit ``test`` argv.
        overrides: the service's healthcheck entry from services.yml.
        context: port, path, hostname, samples and any flavor specific extras.

    Raises:
        KeyError: the flavor is unknown.
    """
    probe = (PROBES[flavor] if flavor else Custom)(**context)
    return dump_yaml_str({"healthcheck": probe.block(overrides)}, width=10**6).rstrip(
        "\n"
    )
