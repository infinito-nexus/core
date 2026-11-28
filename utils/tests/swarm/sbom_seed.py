"""Build the SBOM of every image in the swarm lab registry once, into the SBOM seed.

At the end of each deploy pass every lab node scans the images it runs, and
Syft exports each of them from the node's own daemon first. The nodes share one
runner disk, so those exports take turns behind one lock, and an image that
runs on several nodes is exported once per node. The lab registry already holds
every image the nodes pull. Reading each image from there once, while the
deploy still runs, leaves the nodes an SBOM to take instead: ``seed_sbom`` of
the ``sys-ctl-hlth-runtime`` script reads the seed beside the databases and
takes an SBOM only when its recorded layers are the node image's own. The
seeder never fails a drill: a read that fails or does not fit the runner only
leaves that image to the node's own Syft run.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.security.deploy import HOST_PATH_ENV
from utils.security.engine import SBOM_BUILDER
from utils.security.pipeline import engine_image, pipeline, user_runtime
from utils.tests.swarm import seed_reports

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

REGISTRY_ROLE = "svc-registry-docker"
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
ARCHITECTURES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}
CATALOG_PAGE = 1000
HTTP_TIMEOUT_S = 30
SCAN_TIMEOUT_S = 1800
POLL_S = 60
JOIN_S = 30
FREE_FLOOR_BYTES = 20 * 1024**3
MEMORY_FLOOR_BYTES = 5 * 1024**3 // 2
REPORT_FLOOR_BYTES = 4 * 1024**3
CPUS = "1"
MEMORY_LIMIT = "2g"
GO_MEMORY_LIMIT = "1800MiB"
CONTAINER_PREFIX = "infinito-sbom-seed"
SYFT_OUTPUT = "sbom.syft.json"
CYCLONEDX_OUTPUT = "sbom.cdx.json"
FETCH_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    OSError,
    ValueError,
    KeyError,
    TypeError,
)


@dataclass(frozen=True)
class Entry:
    """One image of the lab registry.

    Args:
        repository: the repository in the registry.
        digest: the digest of its manifest for the lab architecture.
        layers: its ordered layer digests, the config's ``rootfs.diff_ids``.
        size: the compressed size of its layers in bytes.
    """

    repository: str
    digest: str
    layers: tuple[str, ...]
    size: int


def registry_port() -> int:
    """Return the port the lab registry listens on."""
    services = load_yaml_any(
        str(PROJECT_ROOT / "roles" / REGISTRY_ROLE / ROLE_FILE_META_SERVICES)
    )
    return int(services["docker"]["ports"]["local"]["registry"])


def http_json(url: str, accept: str) -> tuple[dict, str]:
    """
    Args:
        url: an endpoint of the lab registry.
        accept: the ``Accept`` header.

    Returns:
        ``(document, Docker-Content-Digest header)`` of the GET.
    """
    request = urllib.request.Request(url, headers={"Accept": accept})  # noqa: S310 - plain HTTP to the lab registry, which serves no TLS
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:  # noqa: S310 - plain HTTP to the lab registry, which serves no TLS
        return (
            json.loads(response.read()),
            response.headers.get("Docker-Content-Digest", ""),
        )


def manifest_for(
    base: str,
    repository: str,
    reference: str,
    architecture: str,
    fetch: Callable[[str, str], tuple[dict, str]],
) -> tuple[str, dict] | None:
    """
    Args:
        base: the registry URL.
        repository: the repository.
        reference: a tag or digest in it.
        architecture: the lab architecture.
        fetch: :func:`http_json` or a test double.

    Returns:
        ``(digest, manifest)`` of the image for the lab architecture, ``None``
        when an index lists none for it or the registry names no digest.
    """
    document, digest = fetch(
        f"{base}/v2/{repository}/manifests/{reference}",
        ", ".join(INDEX_TYPES + MANIFEST_TYPES),
    )
    if "manifests" not in document:
        return (digest, document) if digest.startswith("sha256:") else None
    for listed in document["manifests"]:
        target = listed.get("platform") or {}
        if target.get("os") == "linux" and target.get("architecture") == architecture:
            return manifest_for(base, repository, listed["digest"], architecture, fetch)
    return None


def registry_entries(
    base: str, architecture: str, fetch: Callable[[str, str], tuple[dict, str]]
) -> list[Entry]:
    """List every image of the registry once per layer list.

    Args:
        base: the registry URL.
        architecture: the lab architecture.
        fetch: :func:`http_json` or a test double.

    Returns:
        One :class:`Entry` per distinct layer list; a registry that does not
        answer yet yields none, a repository that fails is left out.
    """
    try:
        catalog, _ = fetch(f"{base}/v2/_catalog?n={CATALOG_PAGE}", "application/json")
    except FETCH_ERRORS:
        return []
    entries: dict[tuple[str, ...], Entry] = {}
    for repository in catalog.get("repositories") or []:
        try:
            listing, _ = fetch(f"{base}/v2/{repository}/tags/list", "application/json")
            for tag in listing.get("tags") or []:
                resolved = manifest_for(base, repository, tag, architecture, fetch)
                if resolved is None:
                    continue
                digest, manifest = resolved
                config, _ = fetch(
                    f"{base}/v2/{repository}/blobs/{manifest['config']['digest']}",
                    "*/*",
                )
                layers = tuple((config.get("rootfs") or {}).get("diff_ids") or ())
                if layers:
                    entries.setdefault(
                        layers,
                        Entry(
                            repository,
                            digest,
                            layers,
                            sum(int(layer["size"]) for layer in manifest["layers"]),
                        ),
                    )
        except FETCH_ERRORS:
            continue
    return list(entries.values())


def seed_paths(seed: Path, layers: Sequence[str]) -> tuple[Path, Path]:
    """Return the Syft and CycloneDX file of one layer list in the seed."""
    key = pipeline().layer_key(layers)
    return seed / f"{key}.syft.json", seed / f"{key}.cdx.json"


def available_memory() -> int:
    """Return ``MemAvailable`` of the runner in bytes, ``0`` when unreadable."""
    with contextlib.suppress(OSError, ValueError, IndexError):
        text = Path("/proc/meminfo").read_text(
            encoding="utf-8"
        )  # nocheck: cache-read - a live kernel counter
        for line in text.splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    return 0


def has_room(seed: Path, entry: Entry) -> bool:
    """Whether the runner can stage *entry* without crowding the lab."""
    return (
        shutil.disk_usage(seed).free >= FREE_FLOOR_BYTES + 2 * entry.size
        and available_memory() >= MEMORY_FLOOR_BYTES
    )


def syft_command(
    entry: Entry, host: str, work: Path, image: str, name: str
) -> list[str]:
    """
    Args:
        entry: the image to read.
        host: ``<address>:<port>`` of the lab registry.
        work: the scratch directory, mounted at the same path.
        image: the pinned Syft image.
        name: the container name, so a stop can kill it.

    Returns:
        The ``docker run`` of one Syft read of *entry* from the registry.
    """
    return [
        *user_runtime(),
        "--rm",
        "--name",
        name,
        "--network",
        "host",
        "--cpus",
        CPUS,
        "--memory",
        MEMORY_LIMIT,
        "--memory-swap",
        MEMORY_LIMIT,
        "-e",
        "SYFT_CHECK_FOR_APP_UPDATE=false",
        "-e",
        "SYFT_REGISTRY_INSECURE_USE_HTTP=true",
        "-e",
        f"GOMEMLIMIT={GO_MEMORY_LIMIT}",
        "-e",
        f"HOME={work}",
        "-e",
        f"TMPDIR={work}",
        "-v",
        f"{work}:{work}",
        image,
        "scan",
        f"registry:{host}/{entry.repository}@{entry.digest}",
        "-o",
        f"syft-json={work}/{SYFT_OUTPUT}",
        "-o",
        f"cyclonedx-json={work}/{CYCLONEDX_OUTPUT}",
        "-q",
    ]


def seed_entry(
    entry: Entry,
    seed: Path,
    run: Callable[[Path], subprocess.CompletedProcess],
) -> bool:
    """Read one image with Syft and move its SBOM into the seed.

    The SBOM is kept only when the layers Syft recorded are the entry's, the
    check every node repeats against its own image.

    Args:
        entry: the image.
        seed: the seed directory.
        run: runs the Syft read into the scratch directory it is given.

    Returns:
        ``True`` when both seed files of *entry* are in place.
    """
    work = Path(tempfile.mkdtemp(prefix=".work-", dir=seed))
    try:
        if run(work).returncode != 0:
            return False
        text = (work / SYFT_OUTPUT).read_text(
            encoding="utf-8"
        )  # nocheck: cache-read - Syft just wrote it
        document = json.loads(text)
        recorded = tuple(
            layer["digest"] for layer in document["source"]["metadata"]["layers"]
        )
        if recorded != entry.layers:
            return False
        syft_json, cyclonedx = seed_paths(seed, entry.layers)
        (work / CYCLONEDX_OUTPUT).replace(cyclonedx)
        (work / SYFT_OUTPUT).replace(syft_json)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return False
    else:
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def seed_pass(
    entries: Iterable[Entry],
    seed: Path,
    seed_one: Callable[[Entry], bool],
    room: Callable[[Entry], bool],
    emit: Callable[[str], None],
    told: set[tuple[str, ...]],
    stopped: Callable[[], bool],
) -> int:
    """Seed every entry that is not in the seed yet and fits the runner.

    Args:
        entries: the registry images.
        seed: the seed directory.
        seed_one: :func:`seed_entry` bound to its runner.
        room: :func:`has_room` bound to the seed.
        emit: sink for the log lines.
        told: layer lists already reported as waiting, so each waits once in
            the log; updated in place.
        stopped: ends the pass before the next entry once it returns ``True``.

    Returns:
        How many entries were seeded.
    """
    seeded = 0
    for entry in entries:
        if stopped():
            break
        if all(path.is_file() for path in seed_paths(seed, entry.layers)):
            continue
        if not room(entry):
            if entry.layers not in told:
                told.add(entry.layers)
                emit(
                    f"=== swarm-matrix: sbom seed: {entry.repository} waits for "
                    "free disk and memory ==="
                )
            continue
        started = time.monotonic()
        built = seed_one(entry)
        emit(
            f"=== swarm-matrix: sbom seed: {entry.repository}@{entry.digest[:19]} "
            f"{'built' if built else 'FAILED'} in {time.monotonic() - started:.0f}s ==="
        )
        seeded += built
    return seeded


def _bounded(argv: Sequence[str], name: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=SCAN_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)
        raise


def _idle() -> None:
    return None


def start_seeder(manager: str, root: Path) -> Callable[[], None]:
    """Seed the SBOMs of the lab registry in the background.

    Args:
        manager: the address the lab registry listens on.
        root: the host directory the nodes read the databases from; the seed
            is its ``SBOM_SEED`` subdirectory.

    Returns:
        A callable that stops the seeder and kills a Syft read still going;
        a seeder that cannot start returns one that does nothing.
    """
    architecture = ARCHITECTURES.get(platform.machine())
    try:
        seed = root / pipeline().SBOM_SEED
        seed.mkdir(parents=True, exist_ok=True)
        host = f"{manager}:{registry_port()}"
        image = engine_image(SBOM_BUILDER)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(f"=== swarm-matrix: sbom seed unavailable: {exc} ===", flush=True)
        return _idle
    if architecture is None:
        print(
            f"=== swarm-matrix: sbom seed unavailable on {platform.machine()} ===",
            flush=True,
        )
        return _idle
    base = f"http://{host}"
    name = f"{CONTAINER_PREFIX}-{os.getpid()}"
    stop = threading.Event()
    told: set[tuple[str, ...]] = set()

    def _loop() -> None:
        names, engines = seed_reports.prepare()
        while not stop.is_set():
            entries = registry_entries(base, architecture, http_json)
            seed_pass(
                entries,
                seed,
                lambda entry: seed_entry(
                    entry,
                    seed,
                    lambda work: _bounded(
                        syft_command(entry, host, work, image, name), name
                    ),
                ),
                lambda entry: has_room(seed, entry),
                lambda text: print(text, flush=True),
                told,
                stop.is_set,
            )
            if names and not stop.is_set() and available_memory() >= REPORT_FLOOR_BYTES:
                seed_reports.seed_round(entries, seed, root, names, engines)
            stop.wait(POLL_S)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()

    def _stop() -> None:
        stop.set()
        with contextlib.suppress(OSError):
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
        thread.join(timeout=JOIN_S)

    return _stop


def seeding(
    drill: Callable[[list[str] | None], int],
) -> Callable[[list[str] | None], int]:
    """Wrap a drill entry point so the seeder reads the lab registry while it runs.

    Args:
        drill: the entry point, called with the command line.

    Returns:
        The entry point that starts the seeder against the manager in
        ``MGR_IP`` and the databases in ``INFINITO_VULNERABILITY_DB_HOST_PATH``,
        and stops it when the drill returns or raises.
    """

    def _run(argv: list[str] | None) -> int:
        stop = start_seeder(os.environ["MGR_IP"], Path(os.environ[HOST_PATH_ENV]))
        try:
            return drill(argv)
        finally:
            stop()

    return _run
