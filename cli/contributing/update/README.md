# Update 🔄

Repository-side version maintenance: scan role configuration files for declared upstream versions and bump them in lockstep with new releases.

## Scope

Every role-scoped updater (`docker`, `source`, `pip`, `repository`) and the addon check skip a role whose [lifecycle](../../../docs/contributing/design/role/services/lifecycle.md) is `eol`: no update PR is opened for it and no external test warns about its pins.

## Docker images

`python -m cli.contributing.update.docker` bumps the semver `version:` of every `image` in `roles/*/meta/services.yml`; with `--compose` it bumps the tag of every `image:` literal in the compose files instead, under the same version policy (same depth and flavor, release groups held per file, `# nocheck: docker-version` above `image:` freezes a pin).

A compose file is recognized by its content, not its name: a tracked `.yml` or `.yaml` file whose top level holds a `services` mapping with at least one `image` string. An `image:` that interpolates a variable, carries no tag or is pinned by digest is left alone. Three kinds of file never reach the compose updater:

- Jinja templates (`*.j2`): role templates render `image:` from the `meta/services.yml` pins the role updater owns.
- Fixtures under `tests/`: their pins are test input, not a deployment.
- Files named like a Dependabot `docker-compose` manifest (`compose.yml`, `compose.yaml`, `docker-compose.yml`, `docker-compose.yaml`): Dependabot already bumps them, so a second updater would open a second PR for the same pin.

`roles/*/meta/services.yml` holds no top-level `services` mapping, so no pin is updated by both updaters. The `update-compose-image-versions` job of `.github/workflows/cron-update.yml` opens one PR for all compose files on its own `update/compose-image-versions-` branch, and `scripts/github/update/open/pr.sh` skips it while an open PR on that prefix carries the same change.

## Repository refs

`python -m cli.contributing.update.repository` bumps every `ref:` that sits next to a `repository:` in `roles/*/meta/services.yml` or `roles/*/meta/addons/*.yml`, at any depth, an addon's `config` included:

| `ref:`                 | Moves to                                    | Reads                                        |
| ---------------------- | ------------------------------------------- | -------------------------------------------- |
| semver, e.g. `v0.8.5`  | the latest tag of the same depth and flavor | `git ls-remote --tags <repository>`          |
| full 40-hex commit SHA | the newest release tag that contains it     | `git ls-remote --tags`, treeless `git fetch` |
| same, no such release  | the tip of the default branch               | `git ls-remote <repository> HEAD`            |

A branch name and a short SHA stay as they are. `# nocheck: repository-version` on the line above `ref:` freezes a pin. Each repository is queried once per run and lookup, and a failed query leaves its pins untouched. The `update-repository-refs` job of `.github/workflows/cron-update.yml` opens one PR per changed role, and `tests/external/update/repository/` warns about pending bumps and fails on a commit SHA that a release tag already contains. A pin newer than the newest release keeps following the tip, so no pin moves back to an older release.

Every update PR carries the label `⬆️ update` and one of `🔴 major`, `🟡 minor` or `🟢 patch`: the highest step among its changed versions, read by [level.py](../../../utils/update/level.py). A change that is no number step (a commit SHA, a SHA moving to a tag) counts as `🔴 major`.

## Declared version sources

A pin the Docker updater (`image` + `version`) and the repository updater
(`repository` + `ref`) do not reach names its upstream next to itself:

```yaml
stalwart:
  webui_version: "v1.0.5"
  update:
    key: webui_version
    type: git_tags
    repository: https://github.com/stalwartlabs/webui.git
```

`key` names the pinned key and defaults to `version`; an entity with several
pins declares a list of such blocks. An `image` + `version` pin that declares a
source for `version` is bumped from that source alone, the Docker updater skips
it. Types:

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

A pin whose asset is fetched by digest names its companion checksum beside the
type (`checksum_key`, `checksum_url`), see
[checksum.py](../../../utils/update/checksum.py).

A `repository` + `ref` pin that declares a source with `key: ref` is bumped
from that source alone, the repository updater skips it. A bump to a name the
repository lists as neither branch nor tag
(`git ls-remote <repository> refs/heads/<ref> refs/tags/<ref>`), or one that
lookup cannot confirm, is withheld and reported on stderr.

An `http_regex` source with a `template` fills it with the pattern's named
groups instead of taking the first group, for a tag built from several upstream
values:

```yaml
freeswitch:
  version: "v1.10.12-v3.0.23"
  update:
    type: http_regex
    url: https://raw.githubusercontent.com/bigbluebutton/docker/main/repos/tags
    pattern: 'repos/bigbluebutton (?P<bbb>v[0-9.]+)\nrepos/freeswitch (?P<freeswitch>v[0-9.]+)'
    template: "{freeswitch}-{bbb}"
```

A templated pin moves when the assembled value changes, its suffix included, and never to an older version.

`url` takes a list when the values live in several documents. Their bodies are
searched as one text, in the listed order. Every document is fetched once per
run, so all pins that read it resolve against the same snapshot.

The pinned value is a semver such as `v1.0.5`, `26.04.4.2.1` or `2.4.0p32`. A
moving tag behind an `update:` block, or as the `version` of a monitored addon,
fails `tests/lint/ansible/services/test_version_keys.py`.

An addon pins its version at the root of `meta/addons/<id>.yml` and declares
the same fields in its `update:` block, beside `monitored`, `catalog` and
`upstream_id`:

```yaml
version: "9.15.7"
update:
  type: http_regex
  url: https://maven.xwiki.org/releases/org/xwiki/contrib/ldap/ldap-authenticator/maven-metadata.xml
  pattern: '<version>([0-9][0-9.]*)</version>'
```

A monitored addon of the `github-releases` catalog omits `type`. Its
`upstream_id` is the `owner/repository` whose tags are its versions:

```yaml
version: "v10.2.1"
update:
  monitored: true
  catalog: github-releases
  upstream_id: ONLYOFFICE/onlyoffice-nextcloud
```

An addon's `config.archive` stays a literal URL that carries the pinned version:

```yaml
config:
  archive: "https://github.com/ONLYOFFICE/onlyoffice-nextcloud/releases/download/v10.2.1/onlyoffice.tar.gz"
```

The updater rewrites both lines together. A URL that does not carry the pin
fails `tests/lint/ansible/services/test_version_keys.py`.

Run `python -m cli.contributing.update.source --dry-run` to list pending bumps;
the `update-version-sources` job of `.github/workflows/cron-update.yml` opens
the PRs, and `tests/external/update/source/` warns about them.

## App credentials

`python -m cli.contributing.update.apps --repo infinito-nexus/core --updater-slug infinito-nexus-updater --translate-slug infinito-nexus-translator --downloads ~/Downloads`
walks the operator through the browser steps and stores the results with `gh`.
It names each menu entry to click, waits for Enter after every browser step and
offers the `.pem` that appeared in `--downloads` during that step:
it creates the `updater` environment restricted to `main` when it is missing,
stores a freshly generated updater key there, waits until the older keys are
deleted, prefills the form for the separate translation App and stores its
key as a repository secret. Keys go to `gh` on stdin and are never printed;
`--skip-updater` resumes after the updater step. See
[secrets.md](../../../docs/contributing/tools/github/actions/secrets.md).
