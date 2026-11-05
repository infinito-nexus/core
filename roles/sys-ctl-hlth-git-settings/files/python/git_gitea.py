import urllib.parse

from git_core import Api, repository_path

NAME = "gitea"


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/json",
            "Authorization": f"token {token}",
            "User-Agent": user_agent,
        },
    )


def repository(remote, api_url):
    """Return ``owner/name`` of a remote on the Gitea host that serves the API, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: the API base URL, e.g. ``https://git.example.org/api/v1``; its host is the git host.
    """
    return repository_path(remote, urllib.parse.urlsplit(api_url).hostname or "")


def commit_verification(api, repo, sha):
    """Return whether Gitea verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
    """
    verification = (api.get(f"/repos/{repo}/git/commits/{sha}") or {}).get(
        "commit", {}
    ).get("verification") or {}
    return verification.get("verified") is True, verification.get(
        "reason", "no verification data"
    ) or "no verification data"
