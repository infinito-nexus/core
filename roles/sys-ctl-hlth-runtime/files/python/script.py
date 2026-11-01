#!/usr/bin/env python3
# nocheck: file-size - sys-service installs this one file on every node, which runs it without the repository, so the engine pipeline cannot move into importable modules
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

PROBE_MARKER = "INFINITO-RUNTIME-PROBE"
HARDENED_SETTINGS = ("expose_php", "session.upload_progress.enabled")
PHP_PROBE = (
    f'echo "\\n{PROBE_MARKER}|", ini_get("expose_php"), "|", '
    'ini_get("session.upload_progress.enabled"), "\\n";'
)
NO_BINARY_EXIT_CODES = frozenset({126, 127})
EXEC_TIMEOUT_SECONDS = 60
ENABLED_VALUES = frozenset({"1", "on", "yes", "true"})

SCANNERS = ("trivy", "grype", "osv")
SBOM_BUILDER = "syft"
ENGINES = (*SCANNERS, SBOM_BUILDER)
SBOM_READERS = frozenset({"grype", "osv"})
RUNTIME_ENGINE = "grype"
RUNTIME_ARTIFACT_TYPE = "binary"
TARGET_KINDS = ("host", "container")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NEGLIGIBLE", "NONE", "UNKNOWN")
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
OSV_DB_LAYOUT = "osv-scalibr"
OSV_MISSING_DB = re.compile(r"could not load db for (.+?) ecosystem")
SUCCESS = frozenset({0})
OSV_ACCEPTED_EXIT_CODES = frozenset({0, 1, 128})
OSV_SOURCE_PURL_TYPES = ("deb", "apk")
UPSTREAM_QUALIFIER = re.compile(r"([?&])upstream=([^&#]+)")
HOST_ROOT = "/host"
WORK = "/work"
SBOM = "/sbom"
CACHE = "/cache"
DOCKER_SOCKET = "/var/run/docker.sock"
JOB_TIMEOUT_SECONDS = 4 * 3600
DB_ATTEMPTS = 3
DB_RETRY_SECONDS = 30
DB_MARKERS = {
    "trivy": ("db/trivy.db", "java-db/trivy-java.db"),
    "grype": ("6/vulnerability.db",),
    "osv": (OSV_DB_LAYOUT,),
}


@dataclass(frozen=True)
class Container:
    id: str
    name: str
    stack: str | None
    service: str | None
    image: str
    image_name: str


@dataclass(frozen=True)
class PhpProbe:
    settings: dict


class ProbeError(RuntimeError):
    pass


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ScanConfig:
    """What the vulnerability scan covers and when it fails.

    Args:
        targets: subset of :data:`TARGET_KINDS`.
        engines: subset of :data:`ENGINES` holding at least one scanner.
        severity: severities that fail the scan.
        fixed_only: fail only on findings with a fixed version.
        workers: parallel engine runs.
        db_update: download and refresh the databases; ``False`` reads
            databases that were provided and fails when one is missing.
    """

    targets: tuple[str, ...]
    engines: tuple[str, ...]
    severity: frozenset[str]
    fixed_only: bool
    workers: int
    db_update: bool

    def scanners(self) -> tuple[str, ...]:
        return tuple(engine for engine in SCANNERS if engine in self.engines)

    def reads_sbom(self, engine: str) -> bool:
        return engine in SBOM_READERS and SBOM_BUILDER in self.engines

    def runtime_pass(self) -> bool:
        """Whether Grype scans the source-built runtimes Syft found.

        Only Grype matches a runtime compiled from source, such as the PHP
        of the official ``php`` images, through its CPE; Trivy and OSV do
        not see it. Without Grype in the list, Grype still scans the
        binary-classified packages of every SBOM.
        """
        return RUNTIME_ENGINE not in self.engines and SBOM_BUILDER in self.engines

    def databases(self) -> tuple[str, ...]:
        """The scanners whose database the scan needs."""
        needed = set(self.scanners()) | (
            {RUNTIME_ENGINE} if self.runtime_pass() else set()
        )
        return tuple(engine for engine in SCANNERS if engine in needed)


@dataclass(frozen=True)
class Target:
    """One thing a scanner reads.

    Args:
        key: file-name-safe identity.
        kind: ``host`` or ``container``.
        ref: the image id, or :data:`HOST_ROOT`.
        label: the image name or the host name.
        owners: ``(stack, service)`` of every container running the image.
    """

    key: str
    kind: str
    ref: str
    label: str
    owners: tuple[tuple[str | None, str | None], ...]


@dataclass(frozen=True)
class Finding:
    """One vulnerable package as one engine reports it.

    Args:
        engine: the scanner.
        target: :attr:`Target.key`.
        package: package name.
        installed: installed version.
        fixed: fixed version(s), empty when there is none.
        ids: vulnerability ids, CVE ids first.
        severity: one of :data:`SEVERITIES`.
    """

    engine: str
    target: str
    package: str
    installed: str
    fixed: str
    ids: tuple[str, ...]
    severity: str

    @property
    def id(self) -> str:
        return self.ids[0]


@dataclass(frozen=True)
class Suppression:
    id: str
    until: dt.date


@dataclass(frozen=True)
class Suppressions:
    """Accepted CVEs.

    Args:
        containers: ``{stack: {service: [Suppression]}}``.
        host: ``{engine: [Suppression]}`` for host findings.
    """

    containers: Mapping[str, Mapping[str, Sequence[Suppression]]]
    host: Mapping[str, Sequence[Suppression]]


@dataclass(frozen=True)
class Step:
    """One engine run.

    Args:
        label: what the run is, for error lines.
        argv: the command.
        accept: exit codes that mean success.
    """

    label: str
    argv: tuple[str, ...]
    accept: frozenset[int]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the PHP hardening and the vulnerabilities of this node."
    )
    parser.add_argument(
        "--hardened",
        required=True,
        help='JSON: {"<stack>": ["<service mounting php_hardening>", ...]}',
    )
    parser.add_argument(
        "--scan",
        required=True,
        help="JSON: targets, engines, severity, fixed_only, workers, db_update",
    )
    parser.add_argument(
        "--images",
        required=True,
        help='JSON: {"<engine>": "<image>:<version>"}',
    )
    parser.add_argument(
        "--suppressions",
        required=True,
        help='JSON: {"containers": {stack: {service: [..]}}, "host": {engine: [..]}}',
    )
    parser.add_argument("--cache-dir", required=True, help="SBOM cache and scratch")
    parser.add_argument(
        "--database-dir", required=True, help="Vulnerability databases, one per scanner"
    )
    parser.add_argument(
        "--host-excludes",
        required=True,
        help="JSON: absolute host paths the host scan skips",
    )
    return parser.parse_args(argv)


def identity(labels: dict | None) -> tuple[str | None, str | None]:
    """Return the ``(stack, service)`` a container belongs to.

    Args:
        labels: the container's ``Config.Labels``, ``None`` when it has none.

    Returns:
        The swarm stack and service or the compose project and service;
        ``(None, None)`` for a container started outside both.
    """
    if not labels:
        return None, None
    stack = labels.get("com.docker.stack.namespace")
    if stack:
        service = labels["com.docker.swarm.service.name"]
        return stack, service.removeprefix(f"{stack}_")
    project = labels.get("com.docker.compose.project")
    if project:
        return project, labels["com.docker.compose.service"]
    return None, None


def running_containers() -> list[Container]:
    ids = subprocess.run(
        ["container", "ps", "-q", "--no-trunc"],
        capture_output=True,
        text=True,
        check=True,
        timeout=EXEC_TIMEOUT_SECONDS,
    ).stdout.split()
    if not ids:
        return []
    inspected = json.loads(
        subprocess.run(
            ["container", "inspect", "--type", "container", *ids],
            capture_output=True,
            text=True,
            check=True,
            timeout=EXEC_TIMEOUT_SECONDS,
        ).stdout
    )
    containers = []
    for entry in inspected:
        stack, service = identity(entry["Config"]["Labels"])
        containers.append(
            Container(
                id=entry["Id"],
                name=entry["Name"].lstrip("/"),
                stack=stack,
                service=service,
                image=entry["Image"],
                image_name=entry["Config"]["Image"],
            )
        )
    return containers


def parse_probe(stdout: str) -> PhpProbe:
    """Read the probe line out of the ``php -r`` output.

    Args:
        stdout: everything php printed, startup warnings included.

    Returns:
        Whether each of HARDENED_SETTINGS is on.
    """
    for line in stdout.splitlines():
        if not line.startswith(f"{PROBE_MARKER}|"):
            continue
        values = line.split("|")[1:]
        if len(values) != len(HARDENED_SETTINGS):
            raise ProbeError(f"malformed probe line: {line!r}")
        return PhpProbe(
            settings={
                name: value.strip().lower() in ENABLED_VALUES
                for name, value in zip(HARDENED_SETTINGS, values, strict=True)
            },
        )
    raise ProbeError(f"php printed no probe line: {stdout.strip()!r}")


def probe_php(container_id: str) -> PhpProbe | None:
    """Run the PHP probe inside a container.

    Args:
        container_id: the container to exec into.

    Returns:
        The probe result, or ``None`` when the container has no ``php``.
    """
    try:
        result = subprocess.run(
            ["container", "exec", container_id, "php", "-r", PHP_PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=EXEC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"php did not answer within {exc.timeout}s") from exc
    if result.returncode in NO_BINARY_EXIT_CODES:
        return None
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip()
        raise ProbeError(f"php exited {result.returncode}: {output}")
    return parse_probe(result.stdout)


def check(
    containers: list[Container],
    hardened: dict,
    probe,
) -> tuple[list[str], list[str]]:
    """Evaluate the PHP hardening of every container.

    Args:
        containers: the running containers.
        hardened: ``{stack: [service, ...]}`` that must run hardened PHP.
        probe: callable returning a :class:`PhpProbe` or ``None`` per id.

    Returns:
        ``(failures, infos)`` as printable lines.
    """
    failures: list[str] = []
    infos: list[str] = []
    for container in sorted(containers, key=lambda c: c.name):
        in_hardened_stack = container.stack in hardened
        must_harden = (
            in_hardened_stack and container.service in hardened[container.stack]
        )
        if not in_hardened_stack:
            continue
        try:
            result = probe(container.id)
        except ProbeError as exc:
            failures.append(f"{container.name}: {exc}")
            continue
        if result is None:
            if must_harden:
                failures.append(
                    f"{container.name}: declares php_hardening but has no php to verify it"
                )
            continue
        enabled = [name for name, on in result.settings.items() if on]
        if not enabled:
            continue
        message = f"{container.name}: {', '.join(enabled)} on"
        if must_harden:
            failures.append(f"{message}, the php_hardening ini is not in effect")
        else:
            infos.append(f"{message} (sidecar without php_hardening)")
    return failures, infos


def scan_config(raw: Mapping) -> ScanConfig:
    """Validate the scan configuration.

    Args:
        raw: ``targets``, ``engines``, ``severity``, ``fixed_only``,
            ``workers`` and ``db_update``.

    Raises:
        ConfigError: a value is missing, unknown or contradictory.
    """
    required = {"targets", "engines", "severity", "fixed_only", "workers", "db_update"}
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigError(f"scan config lacks {', '.join(missing)}")
    for key, known in (
        ("targets", TARGET_KINDS),
        ("engines", ENGINES),
        ("severity", SEVERITIES),
    ):
        values = raw[key]
        if not isinstance(values, list) or not values:
            raise ConfigError(f"{key} must be a non-empty list")
        unknown = sorted(set(values) - set(known))
        if unknown:
            raise ConfigError(
                f"unknown {key}: {', '.join(unknown)}; expected {', '.join(known)}"
            )
    for key in ("fixed_only", "db_update"):
        if not isinstance(raw[key], bool):
            raise ConfigError(f"{key} must be true or false")
    workers = raw["workers"]
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ConfigError("workers must be a positive integer")
    config = ScanConfig(
        targets=tuple(kind for kind in TARGET_KINDS if kind in raw["targets"]),
        engines=tuple(engine for engine in ENGINES if engine in raw["engines"]),
        severity=frozenset(raw["severity"]),
        fixed_only=raw["fixed_only"],
        workers=workers,
        db_update=raw["db_update"],
    )
    if not config.scanners():
        raise ConfigError(
            f"engines name no scanner; expected one of {', '.join(SCANNERS)}"
        )
    if RUNTIME_ENGINE not in config.engines and SBOM_BUILDER not in config.engines:
        raise ConfigError(
            f"source-built runtimes need {RUNTIME_ENGINE} or {SBOM_BUILDER} in engines"
        )
    if (
        "osv" in config.engines
        and "host" in config.targets
        and not config.reads_sbom("osv")
    ):
        raise ConfigError("osv reads no OS packages of the host without syft")
    return config


def suppressions_from_json(raw: Mapping) -> Suppressions:
    def entries(items: Iterable[Mapping]) -> tuple[Suppression, ...]:
        return tuple(
            Suppression(id=item["id"], until=dt.date.fromisoformat(item["until"]))
            for item in items
        )

    return Suppressions(
        containers={
            stack: {service: entries(items) for service, items in services.items()}
            for stack, services in raw["containers"].items()
        },
        host={engine: entries(items) for engine, items in raw["host"].items()},
    )


def vulnerability_ids(ids: Iterable[str]) -> tuple[str, ...]:
    """Return the distinct ids, CVE ids first, each part sorted."""
    unique = {item for item in ids if item}
    cves = sorted(item for item in unique if CVE_PATTERN.match(item))
    return (*cves, *sorted(unique - set(cves)))


def cvss_severity(score: str) -> str:
    """Map a CVSS base score to its qualitative rating."""
    if not score:
        return "UNKNOWN"
    value = float(score)
    if value >= 9.0:
        return "CRITICAL"
    if value >= 7.0:
        return "HIGH"
    if value >= 4.0:
        return "MEDIUM"
    if value > 0.0:
        return "LOW"
    return "NONE"


def parse_trivy(report: Mapping, target: str) -> list[Finding]:
    """Normalise a ``trivy --format json`` report."""
    return [
        Finding(
            engine="trivy",
            target=target,
            package=vuln["PkgName"],
            installed=vuln["InstalledVersion"],
            fixed=vuln.get("FixedVersion") or "",
            ids=vulnerability_ids(
                [vuln["VulnerabilityID"], *(vuln.get("VendorIDs") or [])]
            ),
            severity=vuln["Severity"].upper(),
        )
        for result in report.get("Results") or []
        for vuln in result.get("Vulnerabilities") or []
    ]


def parse_grype(report: Mapping, target: str) -> list[Finding]:
    """Normalise a ``grype -o json`` report."""
    findings = []
    for match in report["matches"]:
        vuln = match["vulnerability"]
        artifact = match["artifact"]
        fix = vuln["fix"]
        related = [item["id"] for item in match.get("relatedVulnerabilities") or []]
        findings.append(
            Finding(
                engine="grype",
                target=target,
                package=artifact["name"],
                installed=artifact["version"],
                fixed=", ".join(fix["versions"]) if fix["state"] == "fixed" else "",
                ids=vulnerability_ids([vuln["id"], *related]),
                severity=vuln["severity"].upper(),
            )
        )
    return findings


def _osv_fixed(vulns: Iterable[Mapping], package: Mapping) -> str:
    fixed = {
        event["fixed"]
        for vuln in vulns
        for affected in vuln.get("affected") or []
        if affected["package"]["name"] == package["name"]
        and affected["package"]["ecosystem"] == package["ecosystem"]
        for version_range in affected.get("ranges") or []
        for event in version_range.get("events") or []
        if "fixed" in event
    }
    return ", ".join(sorted(fixed))


def parse_osv(report: Mapping, target_of: Callable[[str], str]) -> list[Finding]:
    """Normalise an ``osv-scanner --format json`` report.

    Args:
        report: the report.
        target_of: maps a result's ``source.path`` to its target key.

    Returns:
        One finding per package and OSV group. The severity is the group's
        highest CVSS score mapped by :func:`cvss_severity`; the fixed
        versions are the ``fixed`` events of the group's ranges for that
        package.
    """
    findings = []
    for result in report.get("results") or []:
        target = target_of(result["source"]["path"])
        for entry in result["packages"]:
            package = entry["package"]
            by_id = {vuln["id"]: vuln for vuln in entry.get("vulnerabilities") or []}
            for group in entry.get("groups") or []:
                members = [by_id[item] for item in group["ids"] if item in by_id]
                ids = [*group["ids"], *(group.get("aliases") or [])]
                for vuln in members:
                    ids += [*(vuln.get("aliases") or []), *(vuln.get("upstream") or [])]
                findings.append(
                    Finding(
                        engine="osv",
                        target=target,
                        package=package["name"],
                        installed=package["version"],
                        fixed=_osv_fixed(members, package),
                        ids=vulnerability_ids(ids),
                        severity=cvss_severity(group.get("max_severity") or ""),
                    )
                )
    return findings


def osv_sbom(cyclonedx: Mapping) -> dict:
    """Return a CycloneDX copy whose distro purls name the source package.

    OSV keys Debian, Ubuntu and Alpine advisories by source package, while
    Syft names the binary package and carries the source in the ``upstream``
    qualifier (``libssl3`` from ``openssl``).

    Args:
        cyclonedx: a Syft ``cyclonedx-json`` document.
    """
    document = json.loads(json.dumps(cyclonedx))
    for component in document.get("components") or []:
        purl = component.get("purl") or ""
        kind = purl.removeprefix("pkg:").partition("/")[0]
        match = UPSTREAM_QUALIFIER.search(purl)
        if kind not in OSV_SOURCE_PURL_TYPES or match is None:
            continue
        head, sep, qualifiers = purl.partition("?")
        path, _, version = head.partition("@")
        source, _, source_version = urllib.parse.unquote(match.group(2)).partition("@")
        namespace = path.rpartition("/")[0]
        component["purl"] = (
            f"{namespace}/{source}@{source_version or version}{sep}{qualifiers}"
        )
    return document


def runtime_sbom(syft: Mapping) -> dict | None:
    """Return a Syft JSON copy that holds only the binary-classified packages.

    Args:
        syft: a Syft ``syft-json`` document.

    Returns:
        The reduced document, or ``None`` when Syft classified no binary.
    """
    binaries = [
        artifact
        for artifact in syft.get("artifacts") or []
        if artifact.get("type") == RUNTIME_ARTIFACT_TYPE
    ]
    if not binaries:
        return None
    reduced = {key: value for key, value in syft.items() if key != "files"}
    reduced["artifacts"] = binaries
    reduced["artifactRelationships"] = []
    return reduced


def failing(finding: Finding, config: ScanConfig) -> bool:
    """Whether a finding reaches the configured threshold."""
    if finding.severity not in config.severity:
        return False
    return bool(finding.fixed) or not config.fixed_only


def matching(rules: Sequence[Suppression], finding: Finding) -> Suppression | None:
    """Return the suppression naming one of the finding's ids, latest first."""
    hits = [rule for rule in rules if rule.id in finding.ids]
    return max(hits, key=lambda rule: rule.until) if hits else None


def _owner_label(owner: tuple[str | None, str | None]) -> str:
    stack, service = owner
    if stack is None:
        return "unmanaged container"
    return f"{stack}/{service}"


@dataclass(frozen=True)
class Verdict:
    """One finding at the threshold, judged for one owner.

    Args:
        finding: the finding.
        target: the target it was found in.
        owner: the ``(stack, service)`` it is judged for, ``(None, None)``
            for the host and for unmanaged containers.
        rule: the suppression that names it, ``None`` when none does.
        suppressed: whether that suppression is still in force.
    """

    finding: Finding
    target: Target
    owner: tuple[str | None, str | None]
    rule: Suppression | None
    suppressed: bool

    def where(self) -> str:
        scope = self.target.label
        if self.target.kind == "container":
            scope = f"{_owner_label(self.owner)} {scope}"
        return f"{self.finding.engine} {self.target.kind} {scope}"

    def detail(self) -> str:
        finding = self.finding
        fixed = f"fixed in {finding.fixed}" if finding.fixed else "no fix"
        return f"{finding.id} {finding.severity} {finding.package} {finding.installed} ({fixed})"


def verdicts(
    findings: Iterable[Finding],
    targets: Mapping[str, Target],
    config: ScanConfig,
    suppressions: Suppressions,
    today: dt.date,
) -> list[Verdict]:
    """Judge the findings against the threshold and the suppressions.

    A role's suppressions cover only the containers of its own stack and
    service; a host suppression covers only the engine it is declared
    under.
    """
    judged = []
    for finding in sorted(
        set(findings),
        key=lambda f: (f.target, f.engine, f.package, f.id, f.installed),
    ):
        if not failing(finding, config):
            continue
        target = targets[finding.target]
        if target.kind == "host":
            scopes = [((None, None), suppressions.host.get(finding.engine, ()))]
        else:
            scopes = [
                (
                    owner,
                    suppressions.containers.get(owner[0], {}).get(owner[1], ())
                    if owner[0] is not None
                    else (),
                )
                for owner in sorted(set(target.owners), key=str)
            ]
        for owner, rules in scopes:
            rule = matching(rules, finding)
            judged.append(
                Verdict(
                    finding,
                    target,
                    owner,
                    rule,
                    rule is not None and rule.until >= today,
                )
            )
    return judged


def evaluate(
    findings: Iterable[Finding],
    targets: Mapping[str, Target],
    config: ScanConfig,
    suppressions: Suppressions,
    today: dt.date,
) -> tuple[list[str], list[str]]:
    """Return :func:`verdicts` as ``(failures, infos)`` printable lines."""
    failures: list[str] = []
    infos: list[str] = []
    for verdict in verdicts(findings, targets, config, suppressions, today):
        line = f"{verdict.where()}: {verdict.detail()}"
        if verdict.suppressed:
            infos.append(f"{line} suppressed until {verdict.rule.until}")
            continue
        if verdict.rule is not None:
            infos.append(
                f"{verdict.where()}: suppression of {verdict.rule.id} expired on {verdict.rule.until}"
            )
        failures.append(line)
    return failures, infos


def container_targets(containers: Iterable[Container]) -> list[Target]:
    """Group the running containers by image."""
    grouped: dict[str, list[Container]] = {}
    for container in containers:
        grouped.setdefault(container.image, []).append(container)
    targets = []
    for image, members in sorted(grouped.items()):
        members.sort(key=lambda c: c.name)
        targets.append(
            Target(
                key=image.removeprefix("sha256:"),
                kind="container",
                ref=image,
                label=members[0].image_name,
                owners=tuple((member.stack, member.service) for member in members),
            )
        )
    return targets


def host_target(hostname: str) -> Target:
    return Target(key="host", kind="host", ref=HOST_ROOT, label=hostname, owners=())


def _env(pairs: Mapping[str, str]) -> list[str]:
    args = []
    for key, value in sorted(pairs.items()):
        args += ["-e", f"{key}={value}"]
    return args


ENGINE_ENV = {
    "trivy": {},
    "grype": {"GRYPE_DB_CACHE_DIR": CACHE, "GRYPE_CHECK_FOR_APP_UPDATE": "false"},
    "osv": {"OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY": CACHE},
    "syft": {"SYFT_CHECK_FOR_APP_UPDATE": "false"},
}
TRIVY_COMMON = (
    "--cache-dir",
    CACHE,
    "--disable-telemetry",
    "--skip-version-check",
    "--quiet",
)


@dataclass(frozen=True)
class Layout:
    """Where one scan run keeps its files.

    Args:
        runtime: the command that starts a container, e.g. ``container run``.
        databases: the database root, one directory per scanner.
        sbom: the SBOM directory.
        work: the per-run scratch directory.
        excludes: absolute host paths the host scan skips.
    """

    runtime: tuple[str, ...]
    databases: Path
    sbom: Path
    work: Path
    excludes: tuple[str, ...]


def run_argv(
    layout: Layout,
    engine: str,
    image: str,
    args: Sequence[str],
    *,
    target: Target | None,
    extra_env: Mapping[str, str],
) -> tuple[str, ...]:
    """Build the command that runs one engine container.

    Args:
        layout: where the run keeps its files.
        engine: the engine, which picks its database mount and environment.
        image: the engine image.
        args: the engine's arguments.
        target: the target, which picks the host or Docker socket mount;
            ``None`` for a run that reads neither.
        extra_env: environment on top of the engine's own.
    """
    mounts = ["-v", f"{layout.sbom}:{SBOM}", "-v", f"{layout.work}:{WORK}"]
    if engine in SCANNERS:
        mounts += ["-v", f"{layout.databases / engine}:{CACHE}"]
    if target is not None and target.kind == "host":
        mounts += ["-v", f"/:{HOST_ROOT}:ro"]
    if target is not None and target.kind == "container":
        mounts += ["-v", f"{DOCKER_SOCKET}:{DOCKER_SOCKET}:ro"]
    environment = {"TMPDIR": WORK, **ENGINE_ENV[engine], **extra_env}
    return (*layout.runtime, "--rm", *mounts, *_env(environment), image, *args)


def _relative_excludes(layout: Layout) -> list[str]:
    return [f"./{path.strip('/')}" for path in layout.excludes]


def db_steps(engine: str, layout: Layout, image: str) -> list[Step]:
    """Download or refresh one engine's database."""
    if engine == "trivy":
        return [
            Step(
                f"trivy {name}",
                run_argv(
                    layout,
                    engine,
                    image,
                    ["image", flag, *TRIVY_COMMON],
                    target=None,
                    extra_env={},
                ),
                SUCCESS,
            )
            for name, flag in (
                ("database", "--download-db-only"),
                ("java database", "--download-java-db-only"),
            )
        ]
    if engine == "grype":
        return [
            Step(
                "grype database",
                run_argv(
                    layout, engine, image, ["db", "update"], target=None, extra_env={}
                ),
                SUCCESS,
            )
        ]
    return []


def sbom_paths(layout: Layout, target: Target) -> tuple[Path, Path]:
    return (
        layout.sbom / f"{target.key}.syft.json",
        layout.sbom / f"{target.key}.cdx.json",
    )


def sbom_step(layout: Layout, image: str, target: Target) -> Step:
    """Build one target's SBOM in Syft and CycloneDX JSON."""
    if target.kind == "host":
        source = [f"dir:{HOST_ROOT}", "--override-default-catalogers", "image"]
        for path in _relative_excludes(layout):
            source += ["--exclude", path]
    else:
        source = [f"docker:{target.ref}"]
    args = [
        "scan",
        *source,
        "-o",
        f"syft-json={SBOM}/{target.key}.syft.json",
        "-o",
        f"cyclonedx-json={SBOM}/{target.key}.cdx.json",
        "-q",
    ]
    return Step(
        f"syft {target.kind} {target.label}",
        run_argv(layout, "syft", image, args, target=target, extra_env={}),
        SUCCESS,
    )


def trivy_step(layout: Layout, image: str, target: Target, config: ScanConfig) -> Step:
    args = [
        "rootfs" if target.kind == "host" else "image",
        *TRIVY_COMMON,
        "--skip-db-update",
        "--skip-java-db-update",
        "--scanners",
        "vuln",
        "--format",
        "json",
        "--output",
        f"{WORK}/{target.key}.trivy.json",
    ]
    if not config.db_update:
        args += ["--cache-backend", "memory"]
    if target.kind == "host":
        args += [
            "--skip-dirs",
            ",".join(f"{HOST_ROOT}{path}" for path in layout.excludes),
            HOST_ROOT,
        ]
    else:
        args += ["--image-src", "docker", target.ref]
    return Step(
        f"trivy {target.kind} {target.label}",
        run_argv(layout, "trivy", image, args, target=target, extra_env={}),
        SUCCESS,
    )


def grype_step(layout: Layout, image: str, target: Target, config: ScanConfig) -> Step:
    if config.reads_sbom("grype"):
        source = [f"sbom:{SBOM}/{target.key}.syft.json"]
    elif target.kind == "host":
        source = [f"dir:{HOST_ROOT}"]
        for path in _relative_excludes(layout):
            source += ["--exclude", path]
    else:
        source = [f"docker:{target.ref}"]
    args = [*source, "-o", "json", "--file", f"{WORK}/{target.key}.grype.json", "-q"]
    return Step(
        f"grype {target.kind} {target.label}",
        run_argv(
            layout,
            "grype",
            image,
            args,
            target=target,
            extra_env={"GRYPE_DB_AUTO_UPDATE": "false"},
        ),
        SUCCESS,
    )


def osv_args(config: ScanConfig, output: str) -> list[str]:
    args = ["--offline-vulnerabilities", "--format", "json", "--output-file", output]
    if config.db_update:
        args.append("--download-offline-databases")
    return args


def osv_sbom_step(
    layout: Layout, image: str, targets: Sequence[Target], config: ScanConfig
) -> Step:
    """Scan every target's rewritten CycloneDX in one OSV run."""
    args = ["scan", "source", *osv_args(config, f"{WORK}/osv.json")]
    for target in targets:
        args += ["-L", f"{WORK}/{target.key}.osv.cdx.json"]
    return Step(
        "osv sbom",
        run_argv(layout, "osv", image, args, target=None, extra_env={}),
        OSV_ACCEPTED_EXIT_CODES,
    )


def osv_image_steps(
    layout: Layout, image: str, target: Target, config: ScanConfig
) -> list[Step]:
    """Export one image and scan the archive; OSV reads no docker socket."""
    archive = layout.work / "osv-image.tar"
    return [
        Step(
            f"export {target.label}",
            (layout.runtime[0], "save", "--output", str(archive), target.ref),
            SUCCESS,
        ),
        Step(
            f"osv container {target.label}",
            run_argv(
                layout,
                "osv",
                image,
                [
                    "scan",
                    "image",
                    "--archive",
                    f"{WORK}/osv-image.tar",
                    *osv_args(config, f"{WORK}/{target.key}.osv.json"),
                ],
                target=None,
                extra_env={},
            ),
            OSV_ACCEPTED_EXIT_CODES,
        ),
    ]


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        timeout=JOB_TIMEOUT_SECONDS,
    )


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return " | ".join(lines[-3:])


def run_lane(lane: Sequence[Step], runner: Runner) -> list[str]:
    """Run steps in order and stop at the first failing one.

    Returns:
        Error lines, empty when every step succeeded.
    """
    for step in lane:
        try:
            result = runner(step.argv)
        except subprocess.TimeoutExpired as exc:
            return [f"{step.label}: no result within {exc.timeout}s"]
        missing = OSV_MISSING_DB.findall(f"{result.stdout}\n{result.stderr}")
        if missing:
            return [
                f"{step.label}: no OSV database for {', '.join(sorted(set(missing)))}"
            ]
        if result.returncode not in step.accept:
            output = _tail(result.stderr) or _tail(result.stdout)
            return [f"{step.label}: exited {result.returncode}: {output}"]
    return []


def run_lanes(
    lanes: Sequence[Sequence[Step]], runner: Runner, workers: int
) -> list[list[str]]:
    """Run lanes in parallel, at most *workers* at a time.

    Returns:
        The error lines of each lane, in lane order.
    """
    if not lanes:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda lane: run_lane(lane, runner), lanes))


def _flat(errors: Iterable[Sequence[str]]) -> list[str]:
    return [line for lines in errors for line in lines]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def missing_databases(engine: str, databases: Path) -> list[str]:
    """Name every file of a provided database that is not there."""
    return [
        f"{engine}: provided database {databases / engine / marker} is missing"
        for marker in DB_MARKERS[engine]
        if not (databases / engine / marker).exists()
    ]


def prepare_databases(
    config: ScanConfig, images: Mapping[str, str], layout: Layout, runner: Runner
) -> dict[str, list[str]]:
    """Refresh or check each database the scan needs.

    Returns:
        ``{engine: error lines}``; an engine with errors does not scan.
    """
    needed = config.databases()
    if not config.db_update:
        return {
            engine: missing_databases(engine, layout.databases) for engine in needed
        }
    for engine in needed:
        (layout.databases / engine).mkdir(parents=True, exist_ok=True)
    results: dict[str, list[str]] = {}
    pending = list(needed)
    for attempt in range(DB_ATTEMPTS):
        if attempt:
            pause(DB_RETRY_SECONDS)
        lanes = [db_steps(engine, layout, images[engine]) for engine in pending]
        results.update(
            zip(pending, run_lanes(lanes, runner, config.workers), strict=True)
        )
        pending = [engine for engine in pending if results[engine]]
        if not pending:
            break
    return {engine: results[engine] for engine in needed}


def pause(seconds: float) -> None:
    time.sleep(seconds)


def runtime_step(layout: Layout, image: str, target: Target) -> Step:
    """Scan the binary-classified packages of one SBOM with Grype."""
    args = [
        f"sbom:{WORK}/{target.key}.runtime.syft.json",
        "-o",
        "json",
        "--file",
        f"{WORK}/{target.key}.runtime.grype.json",
        "-q",
    ]
    return Step(
        f"grype runtime {target.kind} {target.label}",
        run_argv(
            layout,
            RUNTIME_ENGINE,
            image,
            args,
            target=None,
            extra_env={"GRYPE_DB_AUTO_UPDATE": "false"},
        ),
        SUCCESS,
    )


def scan(
    targets: Sequence[Target],
    config: ScanConfig,
    images: Mapping[str, str],
    layout: Layout,
    runner: Runner,
) -> tuple[list[Finding], list[str]]:
    """Run every engine over every target.

    Returns:
        ``(findings, errors)``; an error is an engine run that did not
        deliver, which fails the scan like a finding.
    """
    databases = prepare_databases(config, images, layout, runner)
    errors = _flat(databases.values())
    usable = {engine for engine, lines in databases.items() if not lines}
    scanners = [engine for engine in config.scanners() if engine in usable]
    runtime = config.runtime_pass() and RUNTIME_ENGINE in usable

    sbom_ready = list(targets)
    if runtime or any(config.reads_sbom(engine) for engine in scanners):
        pending = [
            target
            for target in targets
            if target.kind == "host"
            or not all(path.is_file() for path in sbom_paths(layout, target))
        ]
        results = run_lanes(
            [[sbom_step(layout, images[SBOM_BUILDER], target)] for target in pending],
            runner,
            config.workers,
        )
        errors += _flat(results)
        failed = {
            target.key for target, lines in zip(pending, results, strict=True) if lines
        }
        sbom_ready = [target for target in targets if target.key not in failed]

    lanes: list[list[Step]] = []
    if "trivy" in scanners:
        lanes.append(
            [trivy_step(layout, images["trivy"], target, config) for target in targets]
        )
    if "grype" in scanners:
        lanes.extend(
            [grype_step(layout, images["grype"], target, config)]
            for target in targets
            if not config.reads_sbom("grype") or target in sbom_ready
        )
    for target in sbom_ready if runtime else ():
        reduced = runtime_sbom(_read_json(sbom_paths(layout, target)[0]))
        if reduced is None:
            continue
        (layout.work / f"{target.key}.runtime.syft.json").write_text(
            json.dumps(reduced), encoding="utf-8"
        )
        lanes.append([runtime_step(layout, images[RUNTIME_ENGINE], target)])
    if "osv" in scanners and config.reads_sbom("osv"):
        for target in sbom_ready:
            cdx = sbom_paths(layout, target)[1]
            (layout.work / f"{target.key}.osv.cdx.json").write_text(
                json.dumps(osv_sbom(_read_json(cdx))), encoding="utf-8"
            )
        if sbom_ready:
            lanes.append([osv_sbom_step(layout, images["osv"], sbom_ready, config)])
    elif "osv" in scanners:
        lanes.append(
            [
                step
                for target in targets
                for step in osv_image_steps(layout, images["osv"], target, config)
            ]
        )
    errors += _flat(run_lanes(lanes, runner, config.workers))

    findings: list[Finding] = []
    for target in targets:
        for name, parse in (
            ("trivy", parse_trivy),
            ("grype", parse_grype),
            ("runtime.grype", parse_grype),
        ):
            report = layout.work / f"{target.key}.{name}.json"
            if report.is_file():
                findings += parse(_read_json(report), target.key)
        report = layout.work / f"{target.key}.osv.json"
        if report.is_file():
            findings += parse_osv(_read_json(report), lambda _path, key=target.key: key)
    batched = layout.work / "osv.json"
    if batched.is_file():
        by_file = {
            f"{WORK}/{target.key}.osv.cdx.json": target.key for target in sbom_ready
        }
        findings += parse_osv(_read_json(batched), by_file.__getitem__)
    return findings, errors


def prune_sboms(layout: Layout, targets: Iterable[Target]) -> None:
    """Drop the cached SBOMs of images no container runs any more."""
    keep = {path for target in targets for path in sbom_paths(layout, target)}
    for path in layout.sbom.glob("*.json"):
        if path not in keep:
            path.unlink()


def docker_root() -> str:
    return subprocess.run(
        ["container", "info", "--format", "{{.DockerRootDir}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=EXEC_TIMEOUT_SECONDS,
    ).stdout.strip()


def vulnerability_check(
    containers: Sequence[Container],
    config: ScanConfig,
    images: Mapping[str, str],
    suppressions: Suppressions,
    cache: Path,
    databases: Path,
    excludes: Sequence[str],
    runner: Runner,
) -> tuple[list[str], list[str]]:
    targets: list[Target] = []
    if "container" in config.targets:
        targets += container_targets(containers)
    if "host" in config.targets:
        targets.append(host_target(socket.gethostname()))
    sbom = cache / "sbom"
    sbom.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=cache))
    try:
        layout = Layout(
            runtime=("container", "run"),
            databases=databases,
            sbom=sbom,
            work=work,
            excludes=tuple(
                sorted({*excludes, str(cache), str(databases), docker_root()})
            ),
        )
        findings, errors = scan(targets, config, images, layout, runner)
        prune_sboms(
            layout, [target for target in targets if target.kind == "container"]
        )
    finally:
        shutil.rmtree(work)
    failures, infos = evaluate(
        findings,
        {target.key: target for target in targets},
        config,
        suppressions,
        dt.datetime.now(tz=dt.UTC).date(),
    )
    return errors + failures, infos


def main(argv=None) -> int:
    args = parse_args(argv)
    hardened = json.loads(args.hardened)
    try:
        config = scan_config(json.loads(args.scan))
    except ConfigError as exc:
        print(f"❌ {exc}")
        return 1
    try:
        containers = running_containers()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        print(f"❌ listing the running containers failed: {exc}")
        return 1
    failures, infos = check(containers, hardened, probe_php)
    found, noted = vulnerability_check(
        containers,
        config,
        json.loads(args.images),
        suppressions_from_json(json.loads(args.suppressions)),
        Path(args.cache_dir),
        Path(args.database_dir),
        json.loads(args.host_excludes),
        default_runner,
    )
    for line in infos + noted:
        print(f"ℹ️ {line}")
    for line in failures + found:
        print(f"❌ {line}")
    if failures or found:
        print(f"🚨 {len(failures) + len(found)} runtime finding(s).")
        return 1
    print(
        "✅ PHP is hardened where declared and no engine reports a vulnerability at the threshold."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
