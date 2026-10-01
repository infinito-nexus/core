# MediaWiki

## Description

Empower your knowledge base with MediaWiki, a versatile and collaborative platform designed to build comprehensive, user-driven documentation. MediaWiki offers a rich extension ecosystem, robust content management capabilities, and customizable configurations to transform your information into a vibrant, living resource.

## Overview

This role deploys MediaWiki using Docker, automating the setup of your wiki instance along with its underlying MariaDB database. It handles generating the essential configuration file (LocalSettings.php) from a seeded template and integrates with an NGINX reverse proxy for secure, efficient web access.

## Features

- **Collaborative Editing:** Enable multiple users to create and update content simultaneously through an intuitive interface.
- **Extensible Architecture:** Leverage a wide range of extensions and customization options to tailor the wiki experience to your needs.
- **Robust Content Management:** Organize, categorize, and retrieve information efficiently with powerful content management tools.
- **Scalable Deployment:** Utilize Docker for a portable and scalable setup that adapts as your community grows.
- **Secure and Reliable:** Benefit from secure access via an NGINX reverse proxy combined with a MariaDB backend for reliable data storage.

## Addons

This role ships its OIDC login stack, its AI editing stack and its object-store backend as unified addons declared in `meta/addons/`. Each is a MediaWiki extension installed from upstream and gated on a service flag. Secrets are rendered through the role's templates and never inlined into an addon declaration.

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| PluggableAuth | extension | enabled when `services.sso.enabled` | none |
| OpenIDConnect | extension | enabled when `services.sso.enabled` | `sso` |
| VisualEditorPlus | extension | enabled when `services.litellm.enabled` | `litellm` |
| AIEditingAssistant | extension | enabled when `services.litellm.enabled` | `litellm` |
| AWS | extension | enabled when `services.seaweedfs.enabled` | `seaweedfs` |

`meta/addons/` is also the download list: `MEDIAWIKI_EXT_ENABLED` keeps only the addons whose `enabled` resolves true, so a deployment without the matching service never pulls that tarball or runs composer for it.

An addon resolves its tarball from `MEDIAWIKI_EXT_URL_PREFIX` plus its own id and the `REL<major>_<minor>` branch matching the pinned image. An addon that declares `config.archive` in `meta/addons/<id>.yml` uses that URL instead; `AWS` does, because Extension:AWS lives at `edwardspec/mediawiki-aws-s3` rather than under `wikimedia/mediawiki-extensions-*`, and the only `REL` branch it carries is `REL1_34`.

`AWS` therefore carries the tag twice: in `version` (what the drift checker compares against the upstream catalog) and in `config.archive` (what the deploy downloads and what `tests/external/roles/test_pinned_addon_archives_available.py` probes). Move both in the same edit.

## AI editing assistant

With `services.litellm.enabled`, `templates/LocalSettings.php.j2` loads `VisualEditor` (bundled in the image), `VisualEditorPlus` and `AIEditingAssistant`, then points the extension's `open-ai` provider at the in-cluster gateway:

- `$wgAIEditingAssistantActiveProvider` is `open-ai`.
- `$wgAIEditingAssistantActiveProviderConnection` is the JSON object `{url, endpoint, model, secret}` built from `MEDIAWIKI_LITELLM_CONNECTION`; `url` is `LITELLM_OPENAI_BASE_LOCAL_URL` and `secret` is this role's own `credentials.litellm_api_key`. The braces are mandatory: a brace-free value is re-wrapped as `{"legacy": ...}` upstream and the provider falls back to the vendor endpoint at `api.openai.com`.
- `$wgHTTPTimeout` is raised inside the same block because core's 25s is below a cold local model's first token.

The wiring block sits behind a `file_exists` guard on `extensions/VisualEditorPlus/vendor/autoload.php`, because `LocalSettings.php` is rendered before the extensions are installed and `VisualEditorPlus` fatals until its composer step has run.

[`tasks/utils/ai_gateway.yml`](tasks/utils/ai_gateway.yml) runs after `update.php`. It includes the shared gateway consumer contract, then reads both globals back out of the running container with `maintenance/run.php getConfiguration --format=json` and asserts the provider, the base URL and the model, so an unconfigured surface cannot reach a green deploy.

## Further Resources

- [MediaWiki Official Website](https://www.mediawiki.org/)
- [MediaWiki Documentation](https://www.mediawiki.org/wiki/Manual:Configuration_settings)

## Swarm + NFS pilot

Volume layout under `DEPLOYMENT_MODE: swarm` with `storage.backend: nfs`:

- **`images/`** opts into NFS (`nfs: true` in the `compose_volumes`
  call from `templates/compose.yml.j2`). The volume is shared across
  all swarm nodes so the MediaWiki application service can be
  rescheduled freely.
- **`extensions/`** stays local. Extensions are rebuilt from the
  role-managed git source on every install — no shared state needs
  to survive a node move.
- **MariaDB data** stays local on the manager node via
  [svc-db-mariadb](../svc-db-mariadb/) pinning. NFS for the DB data
  directory is intentionally out of scope for v1 (locking / `fsync`
  semantics). See 023's Future Extensions.

CI gate: [.github/workflows/call-test-deploy.yml](../../.github/workflows/call-test-deploy.yml)
provisions a 3-node DinD swarm, deploys this role as a stack, drains
the worker running the application service, and asserts that wiki
content survives the reschedule.

## Object storage

With `services.seaweedfs.enabled`, `templates/LocalSettings.php.j2` loads `AWS` and points it at the SeaweedFS S3 gateway:

- `$wgAWSCredentials`, `$wgAWSRegion` and `$wgAWSBucketName` come from `lookup('objstore', application_id, …)`, so the wiki signs with its own per-consumer identity from the engine's `s3.json`.
- `$wgFileBackends['s3']['endpoint']` is the in-cluster `http://…:8333` URL and `$wgFileBackends['s3']['use_path_style_endpoint']` is true. SeaweedFS serves buckets under a path, not a subdomain, so virtual-host addressing resolves nowhere. `$wgAWSUseHTTPS` is false for the same endpoint.
- `$wgAWSBucketDomain` is the public `objstore.public_url` (scheme, the provider's canonical API domain and the bucket path). The extension appends the zone root directory to it and prefixes `https://` only when the value carries no scheme, so a path-style value renders `…/<bucket>/thumb` correctly. `services.seaweedfs.public: true` grants the anonymous `Read` on that bucket the browser needs to fetch those URLs.
- `$wgEnableUploads` follows the same flag. Extension:AWS only replaces `$wgLocalFileRepo`; it opens no upload surface of its own, so without the object store the wiki keeps its uploads switched off rather than filling the local `images` volume.
- `AWS_REQUEST_CHECKSUM_CALCULATION` and `AWS_RESPONSE_CHECKSUM_VALIDATION` are set to `WHEN_REQUIRED` through `putenv`, the workaround the extension's README prescribes for S3-compatible providers: `aws/aws-sdk-php` is resolved as `^3.67` at install time, and from v3.337.0 the SDK sends checksum trailers by default.

The block sits behind a `file_exists` guard on `extensions/AWS/vendor/autoload.php`, because `LocalSettings.php` is rendered before the extensions are installed and the S3 backend `require`s that autoloader. `tasks/02_extensions.yml` asserts `Aws\S3\S3Client` resolves inside the container afterwards, so an unfinished composer step cannot reach a green deploy.

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`. The wiki's bureaucrat and sysop is a local account created by `maintenance/run.php createAndPromote` in `tasks/04_admin.yml` with `MEDIAWIKI_ADMINISTRATOR_PASSWORD` — the role-local `credentials.administrator_password`, not the Keycloak secret the persona helper carries in `ADMIN_PASSWORD`. `$wgPluggableAuth_EnableLocalLogin` is false, so no native form accepts that password anyway, and `$wgOpenIDConnect_UseEmailNameAsUserName` lands the Keycloak identity on a separate, e-mail-named wiki account that holds no sysop rights. The path back is a deploy step that promotes the OIDC-provisioned administrator account to sysop.

Biber is blocked by `$wgPluggableAuth_EnableAutoLogin`, which this role sets to true in `vars/main.yml`: every anonymous request is bounced straight back into the identity provider, so the verified unauthenticated landing after in-app logout that the persona contract demands can never be observed here. The path back to the generic personas is either auto-login off, or a deploy step that promotes the OIDC-provisioned administrator account to sysop.

The SeaweedFS scenario (`files/playwright/test-seaweedfs.js`) is not the biber persona journey and does not read `PERSONA_BIBER_BLOCKED`: it only needs a session that may upload, so it follows the auto-login bounce with biber's Keycloak credentials and gates on `services.sso.enabled` and `services.seaweedfs.enabled`. PluggableAuth auto-creates the wiki account on that sign-in, and it lands in the `user` group, which carries MediaWiki's default `upload` right.
