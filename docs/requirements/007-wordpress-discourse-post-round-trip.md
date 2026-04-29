# 007 - WordPress to Discourse post round-trip

## User Story

As an operator who deploys WordPress with the shared Discourse service
enabled, I want the WordPress Playwright spec to prove that a post
published in WordPress actually reaches Discourse as a topic, so that
a regression in the wp-discourse plugin configuration, the API key
rotation logic, or the Discourse rake task is caught by CI before it
hits production.

## Context

The deploy-level wiring between WordPress and Discourse already exists:

- [tasks/plugins/wp-discourse.yml](../../roles/web-app-wordpress/tasks/plugins/wp-discourse.yml)
  installs and configures the `wp-discourse` plugin, generates a
  dedicated API key on the Discourse side via the Discourse Rake task,
  and applies every setting declared in
  [vars/discourse.yml](../../roles/web-app-wordpress/vars/discourse.yml).
- The plugin is activated only when `lookup('service',
  'discourse').required | bool` is `true`, which is the project's
  established idiom for "shared AND needed on this host".
- [tasks/plugins/README.md](../../roles/web-app-wordpress/tasks/plugins/README.md)
  already documents the wp-discourse plugin as the integration point.

What is missing is runtime verification. No Playwright scenario today
publishes a post in WordPress and asserts the corresponding Discourse
topic, so a breakage in the publish-to-Discourse path, the API key
re-provisioning, or the category-mapping defaults can ship silently.

## Acceptance Criteria

### Scope

- [x] A new scenario MUST be added to
  [roles/web-app-wordpress/files/playwright.spec.js](../../roles/web-app-wordpress/files/playwright.spec.js)
  that publishes a WordPress post via the WP admin UI and asserts
  that the corresponding Discourse topic exists.
- [x] The scenario MUST be gated on the `discourse` shared service
  being enabled-and-shared, using the `isServiceEnabled("discourse")`
  / `requireService("discourse", ...)` helper contract from
  [006-playwright-service-gated-tests.md](006-playwright-service-gated-tests.md).
  When Discourse is not enabled on the current deploy, the scenario
  MUST report as `skipped: DISCOURSE_SERVICE_ENABLED=false`, not as
  failed.
- [x] The scenario MUST follow the idempotency contract from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md):
  whatever the test creates in WordPress and Discourse, the test MUST
  remove again before it finishes. A completed run against a
  production-like environment MUST leave zero test-created posts and
  zero test-created topics behind.

### Test body

- [x] The scenario MUST generate a unique post title per run (e.g.
  `infinito-playwright-discourse-roundtrip-<ISO-8601-timestamp>-<short-uuid>`)
  so that concurrent or repeated runs cannot collide and so the
  assertion locators remain unambiguous across Discourse categories.
- [x] Authoring the post MUST use an OIDC-authenticated session of a
  user who holds a WordPress role with `publish_posts` capability
  (typically the administrator persona the existing spec already uses
  for baseline tests). The scenario MUST exercise the WP admin
  post-editor UI end to end: new post, set a content body, flip the
  wp-discourse sidebar toggle to publish to Discourse, then publish.
  It MUST NOT short-circuit via the WP REST API, because the goal is
  to catch regressions that affect editors in their real workflow.
- [x] The wp-discourse plugin persists the publish-intent as a
  WordPress post-meta field named `publish_to_discourse` (managed by
  the plugin's `Discourse_Publish` class). The scenario MUST drive
  the sidebar UI that sets this meta, not write the meta directly,
  because writing it directly would bypass exactly the plugin code
  path the test is meant to exercise. If a future wp-discourse
  release renames this meta key, the scenario MUST be updated in
  lockstep, but it MUST continue to go through the UI toggle.
- [x] Assertion in Discourse MUST use the Discourse HTTP API (the same
  API key channel the wp-discourse plugin uses), not UI scraping of
  the Discourse front end. The scenario MUST poll the Discourse
  search endpoint for the generated title with an explicit timeout
  (at least 60 seconds, configurable via env), because wp-discourse's
  publish path is asynchronous.
- [x] The assertion MUST verify at minimum:
  - A topic with the generated title exists in Discourse.
  - The topic's first post body contains a substring of the WP post
    content that the test wrote, proving the content round-tripped
    and not just the title.
  - The topic's author is the `publish-username` configured in
    [vars/discourse.yml](../../roles/web-app-wordpress/vars/discourse.yml)
    (currently `system`).

### Configuration prerequisites

- [x] If `auto-publish` on the wp-discourse side is not currently
  enabled by default (it is commented out in
  [vars/discourse.yml](../../roles/web-app-wordpress/vars/discourse.yml)),
  the requirement MUST decide and document one of the two paths:
  - **Path A**: leave `auto-publish` disabled globally and make the
    Playwright scenario flip the per-post "Publish to Discourse"
    toggle in the WP admin sidebar before clicking "Publish". This
    matches real-editor behaviour.
  - **Path B**: set `auto-publish: true` in the role defaults so
    every new post goes to Discourse automatically.
  Path A MUST be the default unless the role maintainer explicitly
  opts into B for the whole deployment. The requirement MUST add a
  comment in
  [vars/discourse.yml](../../roles/web-app-wordpress/vars/discourse.yml)
  pointing future maintainers at this decision so the behaviour is
  not silently flipped.
- [x] The Playwright env template
  [roles/web-app-wordpress/templates/playwright.env.j2](../../roles/web-app-wordpress/templates/playwright.env.j2)
  MUST render the Discourse base URL and an API key that the scenario
  can use to query Discourse AND to delete the Discourse topic
  during teardown. The API key therefore MUST have **write scope**
  on topics, not read-only; a read-only key would block the
  teardown `DELETE /t/<id>.json` call and leave orphan topics behind.
  The API key MUST NOT be reused from the wp-discourse integration
  key if a plain-text export is unsafe; in that case a dedicated
  test-scoped API key MUST be provisioned with the minimum
  privileges required by the scenario (topic read AND topic delete)
  and its value injected through the standard dotenv pipeline.
- [x] `DISCOURSE_SERVICE_ENABLED` MUST be emitted into the env by the
  same mechanism as every other gate from
  [006-playwright-service-gated-tests.md](006-playwright-service-gated-tests.md)
  (derived from `applications[web-app-wordpress].compose.services.discourse.enabled`
  minus `SERVICES_DISABLED`).

### Teardown

- [x] Teardown MUST run in a `finally` block so it fires even when the
  body assertion throws, matching the pattern the RBAC scenarios
  from
  [004-generic-rbac-ldap-auto-provisioning.md](004-generic-rbac-ldap-auto-provisioning.md)
  already establish for Playwright teardown.
- [x] Teardown MUST cover **every** state the scenario can leave the
  system in, including partial states caused by a crash between
  steps. Specifically it MUST:
  - Search WordPress for any post whose title exactly matches the
    unique generated title and whose status is one of `publish`,
    `draft`, `pending`, `private`, or `future`. Each match MUST be
    moved to Trash and then permanently deleted. This catches the
    case where the scenario created the post but crashed before
    (or during) the publish click, leaving a draft behind.
  - Search Discourse via the API for any topic whose title matches
    the generated title and issue a `DELETE /t/<id>.json` against
    each match.
  - Tolerate zero matches on either side as a valid teardown
    outcome (e.g. the scenario crashed before the post was created
    at all). A teardown MUST NOT fail the test on "nothing to
    clean up".
- [x] Teardown failures MUST be logged to the Playwright reporter
  (via `console.warn` in the `finally` block, the same pattern the
  RBAC scenarios use for their Keycloak cleanup) but MUST NOT mask
  the original body failure. The test result MUST reflect the body
  outcome; a teardown hiccup MUST surface as a secondary warning.

### Verification

- [x] A fresh `make deploy-fresh-purged-apps APPS=web-app-wordpress
  FULL_CYCLE=true` with Discourse enabled MUST produce a green
  run including this scenario.
- [x] A `make deploy-fresh-purged-apps APPS=web-app-wordpress
  FULL_CYCLE=true SERVICES_DISABLED=discourse` MUST produce a
  green run with the scenario reported as `skipped` rather than
  failing, proving the gate from
  [006-playwright-service-gated-tests.md](006-playwright-service-gated-tests.md)
  works as declared in practice.
- [x] The scenario MUST pass the same idempotency check as the rest
  of the suite: running the Playwright spec twice in a row (via
  [rerun-spec.sh](../../scripts/tests/e2e/rerun-spec.sh)) MUST both
  times return green and MUST leave zero persisted test posts in
  WordPress and zero persisted test topics in Discourse.

### Documentation

- [x] [roles/web-app-wordpress/README.md](../../roles/web-app-wordpress/README.md)
  MUST gain an entry under its Playwright section that names
  `discourse` as a gated shared-service dependency, in line with the
  enumeration rule from
  [006-playwright-service-gated-tests.md](006-playwright-service-gated-tests.md).
- [x] The plugin-specific doc
  [roles/web-app-wordpress/tasks/plugins/README.md](../../roles/web-app-wordpress/tasks/plugins/README.md)
  MUST link to this requirement so a future maintainer touching
  wp-discourse sees the round-trip contract that the Playwright
  scenario enforces.
