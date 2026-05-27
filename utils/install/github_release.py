"""GitHub-release asset helpers (latest-tag resolver + downloader)."""

from __future__ import annotations

from urllib.request import urlopen

from utils.install.primitives import download_file


def resolve_latest_tag(latest_url: str, *, timeout: float = 30.0) -> str:
    # GitHub redirects /releases/latest -> /releases/tag/v<version>;
    # final-URL last segment minus a leading 'v' is the version.
    with urlopen(latest_url, timeout=timeout) as response:  # noqa: S310 - trusted github URL
        final_url = response.geturl()

    final_url = final_url.rstrip("/")
    if not final_url:
        raise RuntimeError("Failed to resolve latest release URL.")
    if final_url == latest_url:
        raise RuntimeError("Latest release URL did not resolve to a versioned tag.")

    tag = final_url.rsplit("/", 1)[-1]
    tag = tag.removeprefix("v")
    if not tag or tag in (final_url, "latest"):
        raise RuntimeError(f"Failed to determine version from {final_url}.")
    return tag


def download_release_asset(url: str, output: str) -> None:
    download_file(url, output)


__all__ = ["download_release_asset", "resolve_latest_tag"]
