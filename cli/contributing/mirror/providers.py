from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from .model import ImageRef


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
        return f"ghcr.io/{self.namespace}/{self.repository}/{self.prefix}/{image.registry}/{image.name}"

    def tag_exists(self, image: ImageRef) -> bool:
        """
        Return True if the destination tag already exists in GHCR.

        Uses: skopeo inspect docker://<dest>
        Exit code:
          - 0 => exists
          - !=0 => does not exist OR cannot be accessed (auth/network)
        """
        dest = f"{self.image_base(image)}:{image.version}"
        r = subprocess.run(
            ["skopeo", "inspect", f"docker://{dest}"],
            check=False,
            capture_output=True,
            text=True,
        )
        return r.returncode == 0

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
        dest = f"{self.image_base(image)}:{image.version}"
        src = f"docker://{image.source}"

        try:
            # Fast path
            self._run_copy(src=src, dest=dest)

        except subprocess.CalledProcessError as e:
            # Always print skopeo output for debugging
            output = (e.stdout or "") + (e.stderr or "")
            if output.strip():
                print(output, flush=True)

            # Fallback: force recompress (avoids cross-repo blob reuse)
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
        """
        Return True if the destination tag already exists in the target registry.

        Uses: skopeo inspect docker://<dest>
        Exit code:
          - 0 => exists
          - !=0 => does not exist OR cannot be accessed (auth/network)
        """
        dest = f"{self.image_base(image)}:{image.version}"
        r = subprocess.run(
            ["skopeo", "inspect", f"docker://{dest}"],
            check=False,
            capture_output=True,
            text=True,
        )
        return r.returncode == 0

    def mirror(self, image: ImageRef) -> None:
        dest = f"{self.image_base(image)}:{image.version}"
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
