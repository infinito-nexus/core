from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from utils.docker.image.pin import pull_reference
from utils.docker.mirror import mirror_image_base
from utils.docker.registry import manifest_digest

if TYPE_CHECKING:
    import argparse

    from utils.docker.image.discovery import ImageRef


def _manifest_exists(ref: str) -> bool:
    """
    Args:
        ref: the image reference to probe.

    Returns:
        True when the registry serves a manifest or index for ``ref``, whatever
        architectures it holds; False when it is missing or unreachable.
    """
    r = subprocess.run(
        ["skopeo", "inspect", "--raw", f"docker://{ref}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


class RegistryProvider(ABC):
    @abstractmethod
    def image_base(self, image: ImageRef) -> str:
        pass

    @abstractmethod
    def mirror(self, image: ImageRef) -> None:
        pass

    @abstractmethod
    def tag_exists(self, image: ImageRef) -> bool:
        pass

    def image_ref(self, image: ImageRef) -> str:
        """Return the mirror reference of ``image``, pinned like its upstream.

        Args:
            image: the upstream image, pinned by tag or by digest.
        """
        return pull_reference(self.image_base(image), image.version)


class GHCRProvider(RegistryProvider):
    def __init__(self, namespace: str, repository: str, prefix: str = "mirror") -> None:
        self.namespace = namespace.lower()
        self.repository = repository.lower()
        self.prefix = prefix.strip("/")

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser) -> None:
        """Register --ghcr-namespace, --ghcr-repository, --ghcr-prefix on *parser*."""
        parser.add_argument("--ghcr-namespace", required=True)
        parser.add_argument("--ghcr-repository", required=True)
        parser.add_argument("--ghcr-prefix", default="mirror")

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> GHCRProvider:
        """Construct a GHCRProvider from parsed CLI args."""
        return cls(args.ghcr_namespace, args.ghcr_repository, args.ghcr_prefix)

    def image_base(self, image: ImageRef) -> str:
        return mirror_image_base(
            image.registry,
            image.name,
            namespace=self.namespace,
            repository=self.repository,
            prefix=self.prefix,
        )

    def tag_exists(self, image: ImageRef) -> bool:
        return _manifest_exists(self.image_ref(image))

    def is_stale(self, image: ImageRef) -> bool:
        """Return True if the mirrored tag no longer matches its upstream tag.

        Args:
            image: the upstream image whose mirror copy is compared.

        Returns:
            ``True`` only when both registries answer with a digest and the
            digests differ, i.e. upstream re-pushed the tag after it was
            mirrored. An unanswered side counts as current, so an upstream
            outage or a tag deleted upstream never forces a copy.
        """
        upstream = manifest_digest(f"{image.registry}/{image.name}", image.version)
        if upstream is None:
            return False
        mirrored = manifest_digest(self.image_base(image), image.version)
        return mirrored is not None and mirrored != upstream

    def _run_copy(self, *, src: str, dest: str, extra: list[str] | None = None) -> None:
        cmd = [
            "skopeo",
            "copy",
            "--all",
            "--retry-times",
            "5",
            "--dest-precompute-digests",
        ]
        if extra:
            cmd += extra
        cmd += [src, f"docker://{dest}"]

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _looks_like_blob_reuse_problem(self, e: subprocess.CalledProcessError) -> bool:
        out = (e.stdout or "") + "\n" + (e.stderr or "")
        s = out.lower()
        return (
            "reuse blob" in s
            or "blob mount" in s
            or "mount blob" in s
            or ("failed to mount" in s and ("403" in s or "401" in s))
            or "denied:" in s
            or "unauthorized" in s
        )

    def mirror(self, image: ImageRef) -> None:
        dest = self.image_ref(image)
        src = f"docker://{image.source}"

        try:
            self._run_copy(src=src, dest=dest)

        except subprocess.CalledProcessError as e:
            output = (e.stdout or "") + (e.stderr or "")
            if output.strip():
                print(output, flush=True)

            if self._looks_like_blob_reuse_problem(e):
                self._run_copy(
                    src=src,
                    dest=dest,
                    extra=[
                        "--dest-compress-format",
                        "gzip",
                        "--dest-compress-level",
                        "1",
                        "--dest-force-compress-format",
                    ],
                )
                return

            raise


class GiteaProvider(RegistryProvider):
    def __init__(self, registry: str, namespace: str, prefix: str = "mirror") -> None:
        self.registry = registry.rstrip("/")
        self.namespace = namespace
        self.prefix = prefix.strip("/")

    def image_base(self, image: ImageRef) -> str:
        return f"{self.registry}/{self.namespace}/{self.prefix}/{image.registry}/{image.name}"

    def tag_exists(self, image: ImageRef) -> bool:
        return _manifest_exists(self.image_ref(image))

    def mirror(self, image: ImageRef) -> None:
        dest = self.image_ref(image)
        src = f"docker://{image.source}"

        cmd = [
            "skopeo",
            "copy",
            "--all",
            "--retry-times",
            "5",
            "--dest-precompute-digests",
            src,
            f"docker://{dest}",
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            output = (e.stdout or "") + (e.stderr or "")
            if output.strip():
                print(output, flush=True)
            raise
