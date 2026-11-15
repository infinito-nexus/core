# Update 🔄

Repository-side version maintenance: scan role configuration files for declared upstream versions and bump them in lockstep with new releases.

## Scope

Every role-scoped updater (`docker`, `source`, `pip`, `repository`, `opentofu`) and the addon check skip a role whose [lifecycle](../../../docs/contributing/design/role/services/lifecycle.md) is `eol`: no update PR is opened for it and no external test warns about its pins.

## Repository refs

`python -m cli.contributing.update.repository` bumps every `ref:` that sits next to a `repository:` in `roles/*/meta/services.yml` or `roles/*/meta/addons/*.yml`, at any depth, an addon's `config` included:

| `ref:`                 | Moves to                                    | Reads                               |
| ---------------------- | ------------------------------------------- | ----------------------------------- |
| semver, e.g. `v0.8.5`  | the latest tag of the same depth and flavor | `git ls-remote --tags <repository>` |
| full 40-hex commit SHA | the tip of the default branch               | `git ls-remote <repository> HEAD`   |

A branch name and a short SHA stay as they are. `# nocheck: repository-version` on the line above `ref:` freezes a pin. Each repository is queried once per run and lookup, and a failed query leaves its pins untouched. The `update-repository-refs` job of `.github/workflows/cron-update.yml` opens one PR per changed role, and `tests/external/update/repository/` warns about pending bumps.

## OpenTofu provider pins

`python -m cli.contributing.update.opentofu` reads every `versions.tf.json` under `roles/*/files/opentofu/`. Each provider there is pinned to an exact version. The updater asks the OpenTofu registry for the newest release that is no pre-release and sets that version in every file that pins the provider, so all roots of a tag share one version per provider. `--dry-run` lists the bumps and writes nothing.

The lock files then follow the pins. For every root whose pins changed, the updater downloads the OpenTofu that the role's `meta/services.yml` pins (`opentofu_version`, checked against `opentofu_sha256`) and runs `tofu providers lock` once, with one `-platform` per entry of `opentofu_platforms`. It goes through `files/shell/opentofu/build.sh lock`, which stages a root the same way the runner image build does.

`scripts/github/update/opentofu_pins.sh` runs it, and the `update-opentofu-pins` job of `.github/workflows/cron-update.yml` opens one PR per changed role. The runner image build of that PR inits and validates every root offline, so a bump that breaks a root fails there. `tests/external/update/opentofu/` warns about pending bumps.

## Pinned custom roles

`python -m cli.contributing.update.custom_roles` bumps every role [custom_roles.yml](../../../meta/custom_roles.yml) pins: `version` moves to the newest release tag `vX.Y.Z` or `X.Y.Z` of its repository (`git ls-remote --tags`), and `commit` to the commit that tag peels to. A moving tag such as `latest` and a prerelease are never picked, a pin is never moved backwards, and a failed query leaves its pin untouched. The `update-custom-roles` job of `.github/workflows/cron-update.yml` opens the PR; the manifest itself is described in [deploy.md](../../../docs/administration/deploy.md).

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

A `repository` + `ref` pin that declares a source with `key: ref` is bumped
from that source alone, the repository updater skips it.

An `http_regex` source with a `template` fills it with the pattern's named
groups instead of taking the first group, for a tag built from several upstream
values:

```yaml
freeswitch:
  version: "v1.10.12-v3.0.23"
  update:
    type: http_regex
    url: https://raw.githubusercontent.com/bigbluebutton/docker/develop/repos/tags
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
