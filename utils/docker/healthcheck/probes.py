"""Probes: one class per flavor, each deciding whether the container serves.

Pure and Ansible free. Every probe targets the loopback INSIDE the container,
so it proves that this container serves, not that some replica somewhere does.
"""

from __future__ import annotations

import shlex
from typing import Any, ClassVar

CURL = ("curl",)
CURL_NO_PROXY = ("--noproxy", "*")

_HTTP_REQUEST = (
    "echo -e 'GET /{path} HTTP/1.1\\r\\nHost: localhost\\r\\n"
    "Connection: close\\r\\n\\r\\n' >&3"
)


def curl_argv(*flags: str, url: str, hostname: str | None = None) -> list[str]:
    """Build a curl invocation as argv, for docker's exec form.

    Args:
        flags: curl flags this probe wants, e.g. ``-f`` or ``-fsS``.
        url: the URL to request.
        hostname: sent as a Host header when the vhost matters.

    Returns:
        The argv list, proxy-free.

    Every probe here targets the container's own loopback, so a request that a
    proxy picks up is wrong by definition -- the Wget probe has said so with
    ``--proxy=off`` since it was written. Both spellings come from here so the
    exec form and the shell form cannot drift: the shell form needs the
    wildcard quoted and the exec form needs it bare, which is exactly the kind
    of difference that rots when it is written out three times.
    """
    argv = [*CURL, *flags, *CURL_NO_PROXY]
    if hostname:
        argv += ["-H", f"Host: {hostname}"]
    return [*argv, url]


def curl_shell(*flags: str, url: str, hostname: str | None = None) -> str:
    """The CMD-SHELL spelling of :func:`curl_argv`, quoted for a shell."""
    return " ".join(
        shlex.quote(part) for part in curl_argv(*flags, url=url, hostname=hostname)
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

    def shell(self) -> str:
        """The same command as one shell string, so a prefix can compose with it.

        Returns:
            The CMD-SHELL payload, or the exec argv quoted for a shell.
        """
        form, *rest = self.test()
        if form == "CMD-SHELL":
            return rest[0]
        return " ".join(shlex.quote(part) for part in rest)

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
            probe = curl_shell("-f", url=self.url, hostname=self.hostname)
            return ["CMD-SHELL", " && ".join([probe] * self.samples)]
        return ["CMD", *curl_argv("-f", url=self.url, hostname=self.hostname)]


class Wget(Probe):
    flavor = "wget"
    interval = "1m"
    timeout = "10s"

    def test(self) -> list[str]:
        return ["CMD", "wget", "--spider", "--proxy=off", self.url]


class Http(Probe):
    """Whichever of wget or curl the image happens to ship.

    The wget half stays proxy-aware on purpose: busybox wget rejects
    ``--proxy=off``, and this flavor exists for images where which tool ships is
    unknown, so hardening it there would break the very case it covers.
    """

    flavor = "http"
    retries = 5
    start_period = "20s"

    def test(self) -> list[str]:
        return [
            "CMD-SHELL",
            (
                f"wget -qO- {self.url} >/dev/null"
                f" || {curl_shell('-fsS', url=self.url)} >/dev/null"
            ),
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


class Connect(Probe):
    """Proves only that the port accepts a TCP connection.

    For a service that speaks something other than HTTP there -- php-fpm answers
    FastCGI -- so neither curl nor an HTTP request over the socket can judge it.
    ``/dev/tcp`` is a bash builtin, hence the explicit interpreter.
    """

    flavor = "connect"
    interval = "1m"
    timeout = "20s"
    retries = 5
    start_period = "15m"

    def test(self) -> list[str]:
        return ["CMD", "bash", "-c", f"</dev/tcp/127.0.0.1/{self.port}"]


PROBES: dict[str, type[Probe]] = {
    probe.flavor: probe for probe in (Curl, Wget, Http, Tcp, HttpStatus, Nc, Connect)
}
