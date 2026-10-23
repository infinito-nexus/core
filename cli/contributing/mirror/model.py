"""Local name for the image reference the mirror commands pass around.

No ``__all__``: declaring the re-exported name makes autodoc document the
class here as well as where it is defined, and sphinx then finds two targets
for every ``ImageRef`` annotation.
"""

from __future__ import annotations

from utils.docker.image.discovery import ImageRef  # noqa: F401
