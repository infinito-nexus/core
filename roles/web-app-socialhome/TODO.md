# Todo

## Never deployed

`lifecycle: alpha` puts this role into the CI deploy matrix before it has ever run against a real
host, deliberately: the first CI round is its first execution. Everything below the first live
`make compose-deploy apps=web-app-socialhome` is design-by-source-reading.

Open items that only a live run can settle:

- `index.html` ships an inline pre-paint theme bootstrap, and the rendered header is
  `script-src-elem 'self' https://cdn.…` with no hash, so it is blocked and the first paint
  flashes the wrong theme. Pinning `csp.hashes.script-src-elem` fixes it but has to be re-pinned
  on every image bump; the flash is the cheaper trade until the theme matters.
- `meta/csp.yml` whitelists `blob:` on `script-src` for the audio worklet the DM composer builds
  with `URL.createObjectURL`; worklet modules load under `script-src`, not `worker-src`. The
  bundle registers no service worker and constructs no `Worker`. Whether the Preact bundle also
  needs `unsafe-inline` for style attributes is unknown until a browser reports violations.
- The published image is multi-arch, but only `linux/amd64` has been exercised.
- `Dockerfile.sh` exposes 8124 for aiolibdatachannel signalling beside 8099. Nothing listens on
  it at rest, so only 8099 is published; whether it binds lazily during a call is untested.

## Blocked personas

`PERSONA_ADMINISTRATOR_BLOCKED=true`
: Social Home 2026.6.16 imports `logout` from `client/src/store/auth.ts` in exactly one place —
  `client/src/main.tsx` wires it as the 401 handler via `setUnauthorizedHandler(logout)`. No
  component renders a logout control, so `personas/utils/logout.js` has nothing to click and the
  admin journey cannot complete. The alternative — injecting a `[data-injected-logout]` button via
  `templates/javascript.js.j2` — was rejected: the model
  (`roles/web-app-prometheus/templates/javascript.js.j2`) points the button at
  `OIDC.CLIENT.LOGOUT_URL`, which only exists for OIDC-gated roles, and this role deliberately runs
  without SSO. Path back: upstream ships a logout control (or an in-app logout endpoint we can
  target), then drop the flag and keep the `adminInteraction` already wired in the spec.

`PERSONA_BIBER_BLOCKED=true`
: The app authenticates against its own `platform_users` table. There is no OIDC client and no
  auto-provisioning, so the biber account never exists inside Social Home. Path back: upstream
  grows an OIDC/trusted-header auth path.

## Open from the design pass

- Title override: `SH_INSTANCE_NAME` reaches the home name only on the first boot, because `ensure_instance_identity` (upstream `socialhome/identity_bootstrap.py`) writes `display_name` once and `GET /api/instance/config` prefers that row; an inventory title set later changes the env but not the shown name. Options: `PATCH /api/admin/instance {display_name}` guarded by a marker like the household theme task, or accept first-boot only.
- Shared sign-in budget: `POST /api/auth/token` allows 5 attempts per 15 minutes per `request.remote`, and the app ignores `X-Forwarded-For`, so every browser behind the front proxy and the deploy's own token request share one bucket (measured: all logins in `/api/admin/auth-audit` come from `192.168.75.1`). Options: let the proxy reach the app with the client address (PROXY protocol or upstream trusted-proxy support), or ask upstream to honour a trusted forwarded header.
- `tasks/01_setup.yml` comment is stale: at 2026.10.8 the headless seed marks setup complete itself (upstream `platform/standalone/adapter.py`), so the task always answers 409 (measured: `ok`, never `changed`). Options: drop the task or rewrite the comment.
- `meta/csp.yml` keeps `script-src-elem unsafe-inline` for an inline theme script the 2026.10.8 shell no longer has (it loads `assets/theme-boot.js`; measured: the served `/feed` carries no inline script of its own). Options: drop the flag after checking `hlth-csp`; the injected design script then needs its CSP hash, which `sys-front-inj-design` adds.

## Deferred wiring

- `SH_MAX_STORAGE_BYTES` is pinned to 4 GiB in `vars/main.yml` so the app's media cap stays inside
  `services.socialhome.min_storage` (5 GB). Raising one without the other lets the volume outgrow
  its declared budget.
- `SH_APPS_CATALOG_URL` is emptied so the container never fetches the app catalog from github.com.
  Set it to a self-hosted catalog when one exists.
- `SH_CORS_ALLOWED_ORIGINS` is unset — the SPA is same-origin. Needed only if a third-party client
  should talk to the API.
- The GFS / global-server side of upstream (`Dockerfile.gfs`) is not deployed. Only the household
  instance (`Dockerfile.sh`) is.
