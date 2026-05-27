# Mirror Cleanup: Deleting Private GHCR Packages 🗑️

The `cli.contributing.mirror.cleanup` module deletes GHCR container packages filtered by
prefix and visibility. Use it to remove stale private mirror packages that
were pushed before the repository switched to `GITHUB_TOKEN`-based
authentication (which now makes packages public automatically).

## Prerequisites 📋

You MUST have a **classic Personal Access Token (PAT)** with the
`delete:packages` scope. The `gh auth token` and `GITHUB_TOKEN` issued by
GitHub Actions do NOT include this scope and will fail with HTTP 403.

### Create a classic PAT 🔑

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens).
2. Click **Generate new token → Generate new token (classic)**.
3. Enable the `delete:packages` scope.
4. Copy the generated token.

Export it before running the script:

```bash
export GITHUB_TOKEN=<your-pat>
```

## Usage 💻

```bash
python -m cli.contributing.mirror.cleanup \
    --ghcr-namespace <user|org> \
    --ghcr-prefix    <repo>/mirror \
    --visibility     private \
    --dry-run
```

Remove `--dry-run` to actually delete.

### Arguments ⚙️

| Argument | Default | Description |
|---|---|---|
| `--ghcr-namespace` | required | GitHub username or org that owns the packages |
| `--ghcr-prefix` | `mirror` | Only delete packages whose name starts with `<prefix>/` |
| `--visibility` | `private` | Delete packages with this visibility (`private`, `public`, `internal`) |
| `--dry-run` | off | List matching packages without deleting them |

## Example: Delete all private mirror packages for infinito-nexus-core 🧹

```bash
# Preview (requires a classic PAT with delete:packages)
GITHUB_TOKEN=<your-pat> python -m cli.contributing.mirror.cleanup \
    --ghcr-namespace kevinveenbirkenbach \
    --ghcr-prefix    infinito-nexus-core/mirror \
    --visibility     private \
    --dry-run

# Delete
GITHUB_TOKEN=<your-pat> python -m cli.contributing.mirror.cleanup \
    --ghcr-namespace kevinveenbirkenbach \
    --ghcr-prefix    infinito-nexus-core/mirror \
    --visibility     private
```

## How It Works ⚙️

1. Resolves whether the namespace is a GitHub org or personal account.
2. Lists all container packages with the requested visibility via the
   GitHub Packages REST API (`GET /user/packages` or `GET /orgs/{org}/packages`).
3. Filters by prefix.
4. Deletes each matching package via `DELETE /user/packages/container/{name}`
   (or the org equivalent).

Pagination is handled automatically. The script exits non-zero if any
deletion fails.
