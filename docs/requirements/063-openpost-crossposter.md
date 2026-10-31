# 063 - OpenPost Crossposter for Automated Fediverse Crossposting

## User Story

As an Infinito.Nexus PR manager, I want new posts on our organisation's Mastodon, Pixelfed and PeerTube accounts to be detected and distributed automatically through the OpenPost desk to the selected Fediverse and commercial networks, with optional review, duplicate prevention, retries and attribution, so that one post reaches every audience without duplicated work.

## Background

This requirement implements the crossposting half of the OpenProject user story "sovereign social media publishing and crossposting" (story criterion AC5 and the crossposting part of AC8).
It builds on [062-web-app-openpost.md](062-web-app-openpost.md), which delivers the OpenPost desk, the egress relay to the deployment's Fediverse instances, the connected Fediverse targets and the provider simulator for X, Facebook, Instagram and YouTube.
OpenPost's session cookies only accept same-origin requests, so programmatic access uses Bearer API tokens (observed in the 062 egress proof on 2026-10-21).

No evaluated product forwards Fediverse posts unattended.
OpenPost's built-in workflows refuse to schedule unless a human approves the exact revision in the same run, and its native imports never dispatch automation ([runtime.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/services/workflows/runtime.go)).
Postiz turns feeds into drafts without media, and Ferryman is a closed SaaS.
The crossposter therefore lives in the role as a sidecar that detects posts, applies routing, prevents duplicates and drives OpenPost through its API.

### Upstream facts established by research

| Topic | Finding | Source |
|---|---|---|
| Mastodon detection | `GET /api/v1/accounts/:id/statuses` accepts a `min_id` cursor plus `exclude_replies`, `exclude_reblogs`, `only_media` and `tagged`; cursor paging is limited to 300 requests per 15 minutes. | [Mastodon accounts API](https://docs.joinmastodon.org/methods/accounts/), [rack_attack.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/config/initializers/rack_attack.rb) |
| Mastodon loop signal | A status fetched with the owner's token exposes the `application` that posted it. | [status_serializer.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/app/serializers/rest/status_serializer.rb) |
| Mastodon push | Admin webhooks fire only for local posts, have no delete event and are dropped after 16 retries. | [webhook.rb](https://github.com/mastodon/mastodon/blob/main/app/models/webhook.rb) |
| Pixelfed detection | The Mastodon-compatible API requires a token even for public posts and ignores `exclude_reblogs`; the Atom feed is opt-in, photo-only, limited to 10 posts and cached for 4 hours. | [ApiV1Controller.php](https://github.com/pixelfed/pixelfed/blob/v0.15.1/app/Http/Controllers/Api/ApiV1Controller.php), [ProfileController.php](https://github.com/pixelfed/pixelfed/blob/v0.15.1/app/Http/Controllers/ProfileController.php) |
| PeerTube detection | Video lists paginate by offset only; sorting by `-publishedAt` and deduplicating on `uuid` works; no webhook or plugin hook fires when a video becomes published. | [PeerTube OpenAPI](https://github.com/Chocobozzz/PeerTube/blob/v8.3.1/support/doc/api/openapi.yaml) |
| PeerTube media | Default installs keep only HLS files; one MP4 comes from a combined HLS file or the `generate` endpoint; downloads are throttled to 2 MB/s per IP by default. | [default.yaml](https://github.com/Chocobozzz/PeerTube/blob/v8.3.1/config/default.yaml) |
| Idempotency | Mastodon and Pixelfed honour `Idempotency-Key` for one hour, PeerTube has none, and OpenPost answers a reused key with different input with HTTP 409. | [post_status_service.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/app/services/post_status_service.rb), [OpenPost API reliability](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/docs/content/docs/automate/api/reliability.mdx) |
| OpenPost publish API | `POST /api/v1/publications` takes the workspace, title, source text, target accounts or a social set, renditions, media, metadata and an optional `scheduled_at`; `publish-now`, `events` and media upload sessions complete the flow. | [openapi.json](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/web/openapi.json) |
| Length rules | Mastodon counts graphemes of content warning plus text with 23 per URL; X weights emoji and CJK characters double; Threads allows 500 characters; Instagram allows 2,200 characters and 30 hashtags. | [status_length_validator.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/app/validators/status_length_validator.rb), [X counting](https://docs.x.com/fundamentals/counting-characters) |
| Media rules | Pixelfed rejects text-only posts; Mastodon caps video at 99 MB; Instagram accepts JPEG only. | [ApiV1Controller.php](https://github.com/pixelfed/pixelfed/blob/v0.15.1/app/Http/Controllers/Api/ApiV1Controller.php), [media_attachment.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/app/models/media_attachment.rb), [062 platform constraints](062-web-app-openpost.md#platform-constraints) |
| Test tokens | Mastodon disables the password grant and `tootctl` mints no tokens; PeerTube offers a password grant; Pixelfed issues personal access tokens. | [doorkeeper.rb](https://github.com/mastodon/mastodon/blob/v4.7.3/config/initializers/doorkeeper.rb), [tootctl](https://docs.joinmastodon.org/admin/tootctl/) |
| X cost | A post costs $0.015, a post containing a URL costs $0.20. | [X pricing](https://docs.x.com/x-api/getting-started/pricing) |

### In-repo analogues

- `web-app-openpost` from [062](062-web-app-openpost.md) provides the desk, the API, the provider simulator and the local Fediverse targets.
- [`web-app-bluesky`](../../roles/web-app-bluesky/) builds its sidecar from `files/login-broker/Dockerfile`.
- `roles/web-app-n8n/files/python/provision/` is tested from `tests/unit/python/roles/web-app-n8n/files/provision/`, the pattern for role-local Python tests.

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Reason |
|---|---|---|
| 1 | The crossposter is a Python sidecar entity `crossposter` in `web-app-openpost`, built from `files/crossposter/Dockerfile`. | Operator decision over n8n workflows and OpenPost's approval-gated workflows. |
| 2 | Every publication goes through the OpenPost API; the crossposter never calls a target platform directly. | One place for tokens, delivery state and provider adapters. |
| 3 | Detection uses authenticated REST polling with persisted cursors. | The only method that is complete on Mastodon, Pixelfed and PeerTube. |
| 4 | Crossposting state lives in a `crossposter` schema of the role's Postgres database, unique per source post and target account. | Durable duplicate prevention independent of platform idempotency windows. |
| 5 | Routes are declared in the inventory with a `review` mode (OpenPost draft) and an `auto` mode (immediate publishing). | Configurable routing with optional manual approval. |
| 6 | CI covers Mastodon, Pixelfed and PeerTube as sources against local instances, Fediverse targets end to end, and commercial targets through the 062 provider simulator. | Operator decision on automated testing. |
| 7 | New routes start in `review` mode. | Routes are cleared for unattended publishing one by one. |
| 8 | Activating a route forwards no existing posts; its cursor starts at the newest item. | Prevents flooding targets with the account history. |
| 9 | The opt-out hashtag is `nocrosspost`. | Authors can keep a single post local. |
| 10 | The X attribution template omits the source link. | A post with a URL costs about 13 times more on X. |
| 11 | One active instance, enforced by a Postgres advisory lock. | Two pollers would race for the same cursors. |
| 12 | Dead-lettered items are reported by email through the platform mail service. | Failures reach the PR team without another dashboard. |
| 13 | The end-to-end journey reaches commercial networks through a stateful fake provider owned by the role, piloted on LinkedIn; real provider sandboxes are not used in CI. | Meta has paused programmatic test users, LinkedIn test profiles are created by hand only, X and YouTube offer no sandbox, and CI runs must stay offline, deterministic and free of real accounts. |
| 14 | The fake is a role-local Python sidecar entity `provider`, enabled with the simulator; the simulator keeps answering for every network the fake does not serve yet. | Networks move to the fake one at a time without losing coverage. |

## Target Schema

### Files

```
roles/web-app-openpost/files/crossposter/
├── Dockerfile
└── crossposter/
    ├── __init__.py
    ├── __main__.py
    ├── adapt.py
    ├── config.py
    ├── notify.py
    ├── openpost.py
    ├── retry.py
    ├── store.py
    └── sources/
        ├── __init__.py
        ├── mastodon.py
        ├── peertube.py
        └── pixelfed.py
roles/web-app-openpost/files/provider/
├── Dockerfile
└── provider/
    ├── __init__.py
    ├── __main__.py
    ├── linkedin.py
    └── store.py
tests/unit/python/roles/web-app-openpost/files/crossposter/
tests/unit/python/roles/web-app-openpost/files/provider/
```

### Route shape (proposed)

```yaml
crossposter:
  enabled: false
  poll_interval_seconds: 60
  opt_out_tag: nocrosspost
  retry:
    max_attempts: 8
    base_seconds: 30
    cap_seconds: 3600
  notify:
    recipients: []
  routes:
    - name: press-mastodon
      source:
        platform: mastodon
        base_url: "https://microblog.{{ DOMAIN_PRIMARY }}"
        account: press
        token: "{{ vault_crosspost_press_mastodon_token }}"
      filters:
        visibility: [public]
        exclude_replies: true
        exclude_reblogs: true
        tags: []
        media: any
      targets:
        social_set: Commercial
      mode: review
      attribution:
        default: "{text}\n\n{source_url}"
        x: "{text}"
```

## Acceptance Criteria

### Packaging and lifecycle

- [ ] The `crossposter` entity is built from `files/crossposter/Dockerfile` on a Python base image pinned in `meta/services.yml` and passed as an `ARG` without default, and it runs as a non-root user.
- [ ] Its container healthcheck works on the slim base image without extra binaries.
- [ ] The entity is enabled only when at least one route is configured, and the role deploys green with and without it in compose and swarm.
- [ ] A second crossposter instance neither polls nor publishes while the first holds the Postgres advisory lock.
- [ ] The crossposter authenticates to OpenPost with a Bearer API token that the deploy provisions non-interactively for the organisation workspace, and it reaches OpenPost directly on the role network, not through the egress relay.
- [ ] The crossposter's own requests to Mastodon, Pixelfed and PeerTube resolve the sibling vhosts the same way as the relay does, so detection works in compose, swarm and mesh deployments.

### Configuration

- [ ] Routes are read from `services.crossposter.routes`, and an invalid route (unknown platform, missing token, unknown target) fails the deploy with a message naming the route and the field.
- [ ] Source tokens come from the vault-encrypted inventory and reach the container as files, never as environment variables.

### Detection

- [ ] New public statuses of a configured Mastodon account are detected through `GET /api/v1/accounts/:id/statuses` with a persisted `min_id` cursor, excluding replies and boosts.
- [ ] New posts of a configured Pixelfed account are detected through its API with a token.
- [ ] New videos of a configured PeerTube channel are detected by sorting on `-publishedAt`, and only videos in the published state with public privacy are forwarded.
- [ ] At the configured interval, polling stays within each platform's documented rate limits.
- [ ] Activating a route on an account with existing posts forwards none of them.
- [ ] Posts created while the crossposter was stopped are forwarded exactly once after it restarts.

### Routing and approval

- [ ] Each route maps one source account to OpenPost target accounts or a social set and filters by visibility, hashtag and media.
- [ ] A post carrying the opt-out hashtag is never forwarded.
- [ ] In `review` mode the crossposter creates an unscheduled OpenPost draft that an editor can adjust and schedule in the desk, and in `auto` mode it publishes immediately.
- [ ] A post with a content warning, or with mentions that cannot be mapped to a target network, becomes a draft even on an `auto` route.

### Duplicate and loop prevention

- [ ] The `crossposter` schema holds one row per source post URI and target account under a unique constraint, and every OpenPost request carries an `Idempotency-Key` derived from that pair.
- [ ] Replaying source items through a restart, a cursor reset or overlapping polls creates no second publication, verified against OpenPost and the target instances.
- [ ] A status that OpenPost itself published to Mastodon is never forwarded again, so one Mastodon account can be source and target without loops.

### Adaptation and attribution

- [ ] Text is shortened to each target's limit with that network's counting rules without breaking words, links or hashtags.
- [ ] Fediverse mentions are rewritten to plain names or profile links for commercial targets.
- [ ] Alt text travels with images to every target that supports it.
- [ ] Images for Instagram are converted to JPEG, Pixelfed targets receive only posts with media, PeerTube videos reach YouTube as one MP4 fetched over the internal network, and PeerTube videos above 99 MB reach Mastodon targets as links.
- [ ] Each route renders an attribution template per target network with the source post URL, and the default X template omits the link.

### Retries and error reporting

- [ ] Transient failures (network errors, HTTP 429 and 5xx) from sources and from OpenPost are retried with capped exponential backoff and jitter that honours `Retry-After` and rate-limit reset headers.
- [ ] After the configured maximum attempts, an item enters a dead-letter state and an email naming the source post, the target and the last error reaches the configured recipients through `lookup('email', application_id)`.
- [ ] Delivery failures that OpenPost reports for a crossposted publication are stored in the mapping row and included in the notification.
- [ ] A documented command inside the container lists every crossposted item with its state (pending, drafted, published, failed, dead-lettered).

### Tests

- [ ] Unit tests under `tests/unit/python/roles/web-app-openpost/files/crossposter/` cover length counting, adaptation, routing filters, the idempotency key, backoff timing and the state machine with fixtures recorded from Mastodon, Pixelfed and PeerTube responses.
- [ ] The CLI test posts as a test user on the local Mastodon, Pixelfed and PeerTube instances and asserts within a bounded time exactly one OpenPost publication per route, one delivered post on the local Fediverse target, and the expected simulator requests for X, Facebook, Instagram and YouTube.
- [ ] The CLI test asserts review mode (draft without delivery), the opt-out hashtag, loop prevention, restart without duplicates, and no forwarding of existing posts on route activation.
- [ ] The CLI test lets the simulator answer 503 before succeeding and asserts one delivery, then forces a permanent failure and asserts the dead-letter state and the notification in the test mailbox.
- [ ] The Playwright spec shows the administrator persona finding a crossposted draft in the desk, editing it and scheduling it.
- [ ] `make test` and `make roundtrip apps="web-app-openpost"` are green.

### Fake provider and end-to-end journey

- [ ] The `provider` entity is built from `files/provider/Dockerfile` on the Python base image pinned in `meta/services.yml`, runs as a non-root user, has a healthcheck that works on the slim image, and is enabled exactly when the simulator is.
- [ ] It answers for `www.linkedin.com` and `api.linkedin.com` on the role network with a certificate OpenPost trusts, and the simulator no longer serves LinkedIn.
- [ ] A person can create an account on the fake's sign-up page, and the account exists only in the fake's state.
- [ ] `GET /oauth/v2/authorization` shows sign-in and consent for OpenPost's client and redirects to the registered callback with a single-use code bound to the client id and redirect URI; `POST /oauth/v2/accessToken` exchanges codes and refresh tokens; `GET /v2/userinfo` describes the signed-in account.
- [ ] `POST /rest/images?action=initializeUpload` and its upload URL store images, `POST /rest/posts` stores a post authored by the token's member and answers its id in `x-restli-id`, and `GET /rest/posts/{id}` returns that post; requests with an unknown token are refused.
- [ ] The Playwright browser reaches the fake's pages under the real LinkedIn host names by routing them to the fake's published plain-HTTP port; tor rounds skip the journey.
- [ ] The Playwright spec walks the journey as the administrator: it signs up a new account on the fake, connects it to OpenPost through the fake's consent page, adds it to the review social set, posts on the local Mastodon, finds the crossposter's draft in the desk, edits it and publishes it, then opens the post through the URL OpenPost recorded, finds the edited text, and finds that post exactly once in the fake's delivery list.
- [ ] The CLI test connects LinkedIn through the fake's code flow instead of calling OpenPost's callback with a fixed code.
- [x] Unit tests under `tests/unit/python/roles/web-app-openpost/files/provider/` cover sign-up, the code and refresh flows, token checks, and storing and reading posts and images.

### Documentation

- [ ] `Administration.md` documents the route schema with examples, the review and auto modes, the opt-out hashtag, the attribution templates and their X cost impact, token creation per source platform, and the handling of dead-lettered items.
- [ ] `README.md` lists automated crossposting under Features and shows the crossposter in the Cosmos diagram.
- [ ] This requirement is cross-linked from the implementing pull request and from the OpenProject work item.

## Out of Scope

- Propagating edits and deletions from source posts to targets.
- Push-based detection through Mastodon webhooks, streaming or an ActivityPub follower actor.
- Bluesky as a crossposting target, because federation through `web-app-bridgy-fed` already reaches it.
- TikTok publishing, because TikTok's terms exclude in-house upload tools.
- Serving X, Facebook, Instagram and YouTube from the fake provider; they follow the LinkedIn pilot in later work.

## Validation Apps

```bash
INFINITO_PLAYWRIGHT_KEEP=true make compose-deploy mode=reinstall apps=web-app-openpost full_cycle=true
make roundtrip apps="web-app-openpost"
```

Smoke: post as a test user on the local Mastodon instance, find the draft in the OpenPost desk, schedule it, and see it on the local Fediverse target and in the simulator journal.

## Prerequisites

Every Acceptance Criterion of [062](062-web-app-openpost.md) MUST be checked off before this requirement starts.
The agent MUST read [AGENTS.md](../../AGENTS.md), then [Compose Loop](../agents/action/iteration/compose.md), [Unit Tests](../contributing/actions/testing/unit.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously and write the failing unit tests for the state machine, the idempotency key and the backoff before the code.
Verify against the running OpenPost before claiming a criterion: how an unscheduled publication appears as a draft, how media upload sessions attach files, how long OpenPost keeps idempotency keys, and how a workspace API token is created without a browser.
Verify on the deployed Mastodon, Pixelfed and PeerTube versions that the behaviour cited above from newer upstream releases still holds.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make test` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## See Also

- Publishing desk: [062-web-app-openpost.md](062-web-app-openpost.md)
- Requirement format: [requirements.md](../contributing/requirements.md)
- How agents process requirements: [requirements.md](../agents/action/requirements.md)
