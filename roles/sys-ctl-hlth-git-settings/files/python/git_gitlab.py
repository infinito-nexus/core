import urllib.parse

from git_core import Api, repository_path

NAME = "gitlab"


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/json",
            "PRIVATE-TOKEN": token,
            "User-Agent": user_agent,
        },
    )


def project(repo):
    return urllib.parse.quote(repo, safe="")


def repository(remote, api_url):
    """Return the ``group/name`` path of a remote on the GitLab host that serves the API, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: the API base URL, e.g. ``https://gitlab.example.org/api/v4``; its host is the git host.
    """
    return repository_path(remote, urllib.parse.urlsplit(api_url).hostname or "")


def commit_verification(api, repo, sha):
    """Return whether GitLab verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``group/name``.
        sha: the commit.
    """
    # Exception: GitLab answers 404 for a commit that carries no signature at all, so a missing signature is a finding, not a failed check.
    signature = api.get(
        f"/projects/{project(repo)}/repository/commits/{sha}/signature",
        missing_ok=True,
    )
    if signature is None:
        return False, "unsigned"
    status = str(signature.get("verification_status") or "unknown")
    return status == "verified", status
