# Pull Requests

- You MUST choose the matching Pull Request template before you write a PR description.
- You MUST follow the template selection guidance in [CONTRIBUTING.md](../../../CONTRIBUTING.md).
- You MUST use the templates from `.github/PULL_REQUEST_TEMPLATE`.
- You MUST treat the selected template as the SPOT for PR structure, author input, and review context.
- PRs MUST target the canonical repository that <https://s.infinito.nexus/code> redirects to, unless the operator explicitly names a different target. Before creating the PR, the agent MUST resolve the redirect (e.g. `curl -sSIL https://s.infinito.nexus/code | grep -i '^location:'`) to obtain the canonical repository URL, then compare it against `git remote get-url origin`. If the two do not point to the same repository (host + owner + repo, ignoring `.git` suffix and `https://` vs. `git@` scheme), stop and ask the operator before creating the PR.
