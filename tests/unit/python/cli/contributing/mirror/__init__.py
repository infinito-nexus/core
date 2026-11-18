from utils.docker.image.discovery import ImageRef

NODE_DIGEST = "sha256:feb76650b7195319268c59cb2d419c732d6c499b13bf5296f16ab59eb1f0a4f3"
NODE = ImageRef(
    role="web-app-example",
    service="node",
    name="node",
    version=NODE_DIGEST,
    source=f"docker.io/library/node@{NODE_DIGEST}",
    registry="docker.io",
)
NODE_MIRROR = f"ghcr.io/acme/myrepo/mirror/docker.io/node@{NODE_DIGEST}"
DIGEST_REFERENCE = r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$"

__all__ = ["DIGEST_REFERENCE", "NODE", "NODE_DIGEST", "NODE_MIRROR"]
