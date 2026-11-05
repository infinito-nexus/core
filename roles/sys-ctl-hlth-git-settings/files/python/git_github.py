from git_core import Api, repository_path

NAME = "github"
API_VERSION = "2022-11-28"
GIT_HOST = "github.com"


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
            "X-GitHub-Api-Version": API_VERSION,
        },
    )


def repository(remote, api_url):
    """Return ``owner/name`` of a github.com remote, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: unused; GitHub's git host is fixed.
    """
    return repository_path(remote, GIT_HOST)


def commit_verification(api, repo, sha):
    """Return whether GitHub verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
    """
    verification = (api.get(f"/repos/{repo}/commits/{sha}") or {}).get(
        "commit", {}
    ).get("verification") or {}
    return verification.get("verified") is True, verification.get(
        "reason", "no verification data"
    )
