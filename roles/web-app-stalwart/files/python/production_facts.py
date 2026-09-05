#!/usr/bin/env python3
"""Assert the public mail facts of a deployed Stalwart server.

Read-only: this queries DNS and opens one TCP connection to the SMTP port, so a
misconfigured zone fails the deploy instead of silently degrading deliverability.
Only hard facts are checked -- records, ports and banners that either match the
deployed configuration or do not; mail flow is covered by the role's other suites.

A minimal DNS client lives in this file on purpose: the project ships no DNS
library, `dig` is not guaranteed on a target host, and the checks must behave
identically in DiD, in CI and on a production server.

# nocheck: file-size — the client and the assertions cannot be split: this runs
# through `ansible.builtin.script`, which ships exactly one file to the target.
"""

from __future__ import annotations

import argparse
import secrets
import socket
import struct
import sys
import time
from pathlib import Path

TYPE_A = 1
TYPE_CNAME = 5
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33

CLASS_IN = 1
RCODE_NXDOMAIN = 3
_MAX_POINTER_HOPS = 64
_UDP_SIZE = 4096


class DnsError(RuntimeError):
    """A DNS query could not be completed against any configured resolver."""


def encode_name(name: str) -> bytes:
    """Encode a domain name into DNS wire format (length-prefixed labels)."""
    out = bytearray()
    for label in name.rstrip(".").split("."):
        if not label:
            continue
        raw = label.encode() if label.isascii() else label.encode("idna")
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def decode_name(buf: bytes, offset: int) -> tuple[str, int]:
    """Decode a possibly compressed name; returns (name, offset after the name).

    The returned offset is the position after the name *as encoded at* ``offset``
    -- following a compression pointer must not advance the caller's cursor.
    """
    labels: list[str] = []
    jumped = False
    cursor = offset
    after = offset
    for _ in range(_MAX_POINTER_HOPS):
        if cursor >= len(buf):
            raise DnsError("truncated name in DNS response")
        length = buf[cursor]
        if length == 0:
            cursor += 1
            if not jumped:
                after = cursor
            return ".".join(labels), after
        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(buf):
                raise DnsError("truncated compression pointer in DNS response")
            pointer = ((length & 0x3F) << 8) | buf[cursor + 1]
            if not jumped:
                after = cursor + 2
            jumped = True
            cursor = pointer
            continue
        start = cursor + 1
        end = start + length
        if end > len(buf):
            raise DnsError("truncated label in DNS response")
        labels.append(buf[start:end].decode("utf-8", "replace"))
        cursor = end
    raise DnsError("compression pointer loop in DNS response")


def build_query(name: str, rtype: int, txid: int) -> bytes:
    """Build a recursion-desired query packet for one name/type."""
    header = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    return header + encode_name(name) + struct.pack("!HH", rtype, CLASS_IN)


def _decode_rdata(rtype: int, buf: bytes, offset: int, rdlength: int) -> object:
    if rtype in (TYPE_A, TYPE_AAAA):
        family = socket.AF_INET if rtype == TYPE_A else socket.AF_INET6
        return socket.inet_ntop(family, buf[offset : offset + rdlength])
    if rtype == TYPE_TXT:
        parts: list[str] = []
        cursor = offset
        end = offset + rdlength
        while cursor < end:
            chunk = buf[cursor]
            cursor += 1
            parts.append(buf[cursor : cursor + chunk].decode("utf-8", "replace"))
            cursor += chunk
        return "".join(parts)
    if rtype == TYPE_MX:
        preference = struct.unpack("!H", buf[offset : offset + 2])[0]
        target, _ = decode_name(buf, offset + 2)
        return (preference, target)
    if rtype == TYPE_SRV:
        priority, weight, port = struct.unpack("!HHH", buf[offset : offset + 6])
        target, _ = decode_name(buf, offset + 6)
        return (priority, weight, port, target)
    if rtype in (TYPE_PTR, TYPE_CNAME):
        return decode_name(buf, offset)[0]
    return buf[offset : offset + rdlength]


def parse_response(buf: bytes, txid: int, rtype: int) -> list[object]:
    """Return the decoded answer records of the requested type."""
    if len(buf) < 12:
        raise DnsError("short DNS response")
    resp_id, flags, qdcount, ancount, _ns, _ar = struct.unpack("!HHHHHH", buf[:12])
    if resp_id != txid:
        raise DnsError("DNS transaction id mismatch")
    rcode = flags & 0x000F
    if rcode == RCODE_NXDOMAIN:
        return []
    if rcode != 0:
        raise DnsError(f"DNS server returned rcode {rcode}")

    offset = 12
    for _ in range(qdcount):
        _, offset = decode_name(buf, offset)
        offset += 4

    answers: list[object] = []
    for _ in range(ancount):
        _, offset = decode_name(buf, offset)
        atype, _aclass, _ttl, rdlength = struct.unpack(
            "!HHIH", buf[offset : offset + 10]
        )
        offset += 10
        if atype == rtype:
            answers.append(_decode_rdata(atype, buf, offset, rdlength))
        offset += rdlength
    return answers


def _is_truncated(buf: bytes) -> bool:
    if len(buf) < 12:
        return False
    return bool((struct.unpack("!H", buf[2:4])[0] >> 9) & 1)


def _query_one(resolver: str, packet: bytes, timeout: float) -> bytes:
    family = socket.getaddrinfo(resolver, 53, type=socket.SOCK_DGRAM)[0][0]
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (resolver, 53))
        return sock.recv(_UDP_SIZE)


def _query_one_tcp(resolver: str, packet: bytes, timeout: float) -> bytes:
    family = socket.getaddrinfo(resolver, 53, type=socket.SOCK_STREAM)[0][0]
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((resolver, 53))
        sock.sendall(struct.pack("!H", len(packet)) + packet)
        header = _recv_exact(sock, 2)
        return _recv_exact(sock, struct.unpack("!H", header)[0])


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise DnsError("connection closed mid-response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def system_resolvers() -> list[str]:
    """Nameserver addresses from /etc/resolv.conf, in file order."""
    try:
        lines = Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2:
                found.append(parts[1])
    return found


def query(name: str, rtype: int, resolvers: list[str], timeout: float) -> list[object]:
    """Query every resolver in turn; the first usable answer wins."""
    errors: list[str] = []
    for resolver in resolvers:
        txid = secrets.randbelow(65536)
        packet = build_query(name, rtype, txid)
        try:
            raw = _query_one(resolver, packet, timeout)
            if _is_truncated(raw):
                raw = _query_one_tcp(resolver, packet, timeout)
        except (OSError, DnsError, struct.error, IndexError) as exc:
            errors.append(f"{resolver}: {exc}")
            continue
        try:
            answers = parse_response(raw, txid, rtype)
        except (DnsError, struct.error, IndexError) as exc:
            errors.append(f"{resolver}: {exc}")
        else:
            return answers
    raise DnsError(
        f"no resolver answered for {name}: {'; '.join(errors) or 'none configured'}"
    )


class Report:
    """Collects pass/warn/fail lines and decides the exit code."""

    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0
        self.checks: dict[str, int] = {}

    def record(self, name: str, failures_before: int) -> None:
        """Mark check *name* passed when it added no failure since ``failures_before``."""
        self.checks[name] = int(self.failures == failures_before)

    def ok(self, message: str) -> None:
        print(f"OK:   {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"WARN: {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print(f"FAIL: {message}", file=sys.stderr)


def _resolve_addresses(host: str, resolvers: list[str], timeout: float) -> list[str]:
    addresses = [str(a) for a in query(host, TYPE_A, resolvers, timeout)]
    addresses.extend(str(a) for a in query(host, TYPE_AAAA, resolvers, timeout))
    return addresses


def check_host_address(args, resolvers, report: Report) -> list[str]:
    """The mail host resolves to at least one address."""
    addresses = _resolve_addresses(args.mail_host, resolvers, args.timeout)
    if not addresses:
        report.fail(f"{args.mail_host} has no A/AAAA record")
        return []
    report.ok(f"{args.mail_host} resolves to {', '.join(addresses)}")
    return addresses


def check_mx(args, resolvers, report: Report) -> None:
    """The zone has exactly one MX and it is the mail host (role writes solo)."""
    records = query(args.mail_domain, TYPE_MX, resolvers, args.timeout)
    targets = [str(target).rstrip(".").lower() for _pref, target in records]
    if not targets:
        report.fail(f"{args.mail_domain} has no MX record")
        return
    expected = args.mail_host.rstrip(".").lower()
    if expected not in targets:
        report.fail(f"MX of {args.mail_domain} is {targets}, expected {expected}")
        return
    if len(targets) > 1:
        report.fail(f"MX of {args.mail_domain} is not solo: {targets}")
        return
    report.ok(f"MX of {args.mail_domain} -> {expected}")


def check_spf(args, resolvers, report: Report) -> None:
    """A single v=spf1 record exists and authorises the mail host."""
    records = [
        str(r) for r in query(args.mail_domain, TYPE_TXT, resolvers, args.timeout)
    ]
    spf = [r for r in records if r.lower().startswith("v=spf1")]
    if not spf:
        report.fail(f"{args.mail_domain} has no v=spf1 TXT record")
        return
    if len(spf) > 1:
        report.fail(
            f"{args.mail_domain} has {len(spf)} SPF records; exactly one is valid"
        )
        return
    value = spf[0]
    host = args.mail_host.rstrip(".").lower()
    if f"a:{host}" not in value.lower() and " mx" not in f" {value.lower()}":
        report.fail(
            f"SPF of {args.mail_domain} authorises neither 'mx' nor 'a:{host}': {value}"
        )
        return
    report.ok(f"SPF of {args.mail_domain}: {value}")


def check_dmarc(args, resolvers, report: Report) -> None:
    """_dmarc TXT exists, is a DMARC1 record and declares a policy."""
    name = f"_dmarc.{args.mail_domain}"
    records = [str(r) for r in query(name, TYPE_TXT, resolvers, args.timeout)]
    dmarc = [r for r in records if r.lower().startswith("v=dmarc1")]
    if not dmarc:
        report.fail(f"{name} has no v=DMARC1 TXT record")
        return
    if "p=" not in dmarc[0].lower():
        report.fail(f"{name} declares no policy (p=): {dmarc[0]}")
        return
    report.ok(f"DMARC of {args.mail_domain}: {dmarc[0]}")


def check_dkim(args, resolvers, report: Report) -> None:
    """The deployed selector publishes a DKIM1 record with a non-empty key."""
    if not args.dkim_selector:
        report.warn("no DKIM selector supplied; skipping the DKIM record check")
        return
    name = f"{args.dkim_selector}._domainkey.{args.mail_domain}"
    records = [str(r) for r in query(name, TYPE_TXT, resolvers, args.timeout)]
    dkim = [r for r in records if "v=dkim1" in r.lower()]
    if not dkim:
        report.fail(f"{name} has no v=DKIM1 TXT record")
        return
    key = ""
    for field in dkim[0].split(";"):
        stripped = field.strip()
        if stripped.lower().startswith("p="):
            key = stripped[2:].strip()
    if not key:
        report.fail(f"{name} publishes an empty DKIM key (p=): {dkim[0]}")
        return
    report.ok(f"DKIM {args.dkim_selector} of {args.mail_domain}: {len(key)}-char key")


def check_srv(args, resolvers, report: Report) -> None:
    """Every advertised SRV points at the mail host on its implicit-TLS port."""
    for service, port in (("_submissions", 465), ("_imaps", 993), ("_pop3s", 995)):
        name = f"{service}._tcp.{args.mail_domain}"
        records = query(name, TYPE_SRV, resolvers, args.timeout)
        if not records:
            report.fail(f"{name} has no SRV record")
            continue
        matches = [
            rec
            for rec in records
            if rec[2] == port
            and str(rec[3]).rstrip(".").lower() == args.mail_host.rstrip(".").lower()
        ]
        if not matches:
            report.fail(
                f"{name} does not point at {args.mail_host}:{port} (got {records})"
            )
            continue
        report.ok(f"{name} -> {args.mail_host}:{port}")


def check_ptr(args, addresses: list[str], resolvers, report: Report) -> None:
    """PTR must not contradict the mail host; an absent PTR is only a warning.

    A wrong PTR is a deliverability bug this deploy can cause. A missing one is
    usually outside the role's reach -- rDNS is only provisioned for Hetzner.
    """
    expected = args.mail_host.rstrip(".").lower()
    for address in addresses:
        if ":" in address:
            continue
        reverse = ".".join(reversed(address.split("."))) + ".in-addr.arpa"
        names = [
            str(n).rstrip(".").lower()
            for n in query(reverse, TYPE_PTR, resolvers, args.timeout)
        ]
        if not names:
            report.warn(
                f"{address} has no PTR record (rDNS is provisioned for Hetzner only)"
            )
            continue
        if expected not in names:
            report.fail(f"PTR of {address} is {names}, expected {expected}")
            continue
        report.ok(f"PTR of {address} -> {expected}")


def check_smtp_banner(args, report: Report) -> None:
    """Port 25 answers with a 220 greeting carrying the mail host FQDN."""
    try:
        with socket.create_connection(
            (args.mail_host, args.smtp_port), timeout=args.timeout
        ) as sock:
            sock.settimeout(args.timeout)
            banner = sock.recv(512).decode("utf-8", "replace").strip()
    except OSError as exc:
        report.fail(f"{args.mail_host}:{args.smtp_port} is not reachable: {exc}")
        return
    if not banner.startswith("220"):
        report.fail(
            f"{args.mail_host}:{args.smtp_port} greeting is not 220: {banner!r}"
        )
        return
    if args.mail_host.rstrip(".").lower() not in banner.lower():
        report.fail(
            f"SMTP greeting does not carry {args.mail_host} (rejectNonFqdn identity): {banner!r}"
        )
        return
    report.ok(f"SMTP greeting on {args.mail_host}:{args.smtp_port}: {banner}")


def run_checks(args, resolvers: list[str]) -> Report:
    """Run every hard-fact check once and return the collected report."""
    report = Report()

    def run(name: str, fn, *fn_args):
        before = report.failures
        result = fn(*fn_args)
        report.record(name, before)
        return result

    addresses = run("host_address", check_host_address, args, resolvers, report)
    run("mx", check_mx, args, resolvers, report)
    run("spf", check_spf, args, resolvers, report)
    run("dmarc", check_dmarc, args, resolvers, report)
    run("dkim", check_dkim, args, resolvers, report)
    run("srv", check_srv, args, resolvers, report)
    if addresses:
        run("ptr", check_ptr, args, addresses, resolvers, report)
    run("smtp_banner", check_smtp_banner, args, report)
    return report


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_metrics(report: Report, args, path: str) -> None:
    """Render *report* as a Prometheus textfile at *path*.

    Written to a sibling temp file and renamed, because node_exporter's
    textfile collector reads whole files and would otherwise pick up a
    half-written scrape.
    """
    scope = f'host="{_label(args.mail_host)}",domain="{_label(args.mail_domain)}"'
    lines = [
        "# HELP stalwart_mail_fact_up Whether one production mail configuration check passed.",
        "# TYPE stalwart_mail_fact_up gauge",
    ]
    for name, passed in sorted(report.checks.items()):
        lines.append(
            f'stalwart_mail_fact_up{{{scope},check="{_label(name)}"}} {passed}'
        )
    lines += [
        "# HELP stalwart_mail_facts_failures Failing production mail configuration checks.",
        "# TYPE stalwart_mail_facts_failures gauge",
        f"stalwart_mail_facts_failures{{{scope}}} {report.failures}",
        "# HELP stalwart_mail_facts_warnings Non-fatal findings from the same run.",
        "# TYPE stalwart_mail_facts_warnings gauge",
        f"stalwart_mail_facts_warnings{{{scope}}} {report.warnings}",
        "# HELP stalwart_mail_facts_last_run_timestamp_seconds When the checks last completed.",
        "# TYPE stalwart_mail_facts_last_run_timestamp_seconds gauge",
        f"stalwart_mail_facts_last_run_timestamp_seconds{{{scope}}} {int(time.time())}",
    ]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix(f"{target.suffix}.{secrets.token_hex(4)}")
    staged.write_text("\n".join(lines) + "\n", encoding="utf-8")
    staged.replace(target)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mail-host", required=True, help="Public FQDN of the mail server"
    )
    parser.add_argument(
        "--mail-domain", required=True, help="Zone carrying MX/SPF/DMARC"
    )
    parser.add_argument(
        "--dkim-selector", default="", help="Selector published by the server"
    )
    parser.add_argument("--smtp-port", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--resolver",
        action="append",
        default=[],
        help="Resolver to query (repeatable); defaults to /etc/resolv.conf",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=6,
        help="Whole-suite retries; absorbs DNS propagation right after a deploy",
    )
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument(
        "--metrics-file",
        default="",
        help="Write the outcome as a Prometheus textfile for node_exporter to expose",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    resolvers = args.resolver or system_resolvers()
    if not resolvers:
        print("FAIL: no resolver configured; pass --resolver", file=sys.stderr)
        return 1

    print(
        f"Checking {args.mail_host} (zone {args.mail_domain}) via {', '.join(resolvers)}"
    )
    report = Report()
    for attempt in range(1, args.retries + 1):
        try:
            report = run_checks(args, resolvers)
        except DnsError as exc:
            report = Report()
            report.fail(str(exc))
        if report.failures == 0:
            break
        if attempt < args.retries:
            print(
                f"--- {report.failures} failure(s); retry {attempt}/{args.retries - 1} ---"
            )
            time.sleep(args.retry_delay)

    if args.metrics_file:
        write_metrics(report, args, args.metrics_file)

    if report.failures:
        print(
            f"Production mail facts FAILED: {report.failures} failure(s).",
            file=sys.stderr,
        )
        return 1
    print(f"Production mail facts passed ({report.warnings} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
