# Update 🔄

Repository-side version maintenance: scan role configuration files for declared upstream versions and bump them in lockstep with new releases.

## Scope

Every role-scoped updater (`docker`, `source`, `pip`, `repository`) and the addon check skip a role whose [lifecycle](../../../docs/contributing/design/role/services/lifecycle.md) is `eol`: no update PR is opened for it and no external test warns about its pins.

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
