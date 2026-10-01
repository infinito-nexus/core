# Update 🔄

Repository-side version maintenance: scan role configuration files for declared upstream versions and bump them in lockstep with new releases.

## Declared version sources

A pin the Docker updater (`image` + `version`) and the repository updater
(`repository` + `ref`) do not reach names its upstream next to itself:

```yaml
lmstudio:
  app_version: 0.0.25-1
  update:
    key: app_version
    type: http_regex
    url: https://lmstudio.ai/install.sh
    pattern: 'APP_VERSION="([0-9][0-9.-]*)"'
```

`key` names the pinned key and defaults to `version`; an entity with several
pins declares a list of such blocks. Types:

| `type`          | Fields                | Reads                                  |
| --------------- | --------------------- | -------------------------------------- |
| `git_tags`      | `repository`          | `git ls-remote --tags`                  |
| `registry_tags` | `image`               | the registry's v2 tag list             |
| `npm`           | `package`             | the npm registry                       |
| `http_regex`    | `url`, `pattern`      | the first capture group of each match  |
| `script`        | `path`                | a role-local script printing versions  |

`match` keeps only the versions carrying that prefix (and filters server-side
on Docker Hub), `strip: true` removes it again so a pin without the upstream's
`v` stays without it.

Run `python -m cli.contributing.update.source --dry-run` to list pending bumps;
the `update-version-sources` job of `.github/workflows/cron-update.yml` opens
the PRs, and `tests/external/update/source/` warns about them.
