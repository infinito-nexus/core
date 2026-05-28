# Manage Low-Hardware Resources

Use this guide when you work on a machine with limited CPU, RAM, or disk.

## Goal Hardware

A practical long-term target is:

- 64 GB RAM
- a swapfile about the same size as RAM
- an external SSD with more than 500 GB if your computer does not have sufficient storage space
- enough room for Docker images, volumes, build cache, and local repositories

If disk space is tight, you SHOULD move Docker data, caches, and your working directory to the SSD.

On Linux, you MAY move Docker to a different data path:

```json
{
  "data-root": "/mnt/ssd/docker"
}
```

Then restart Docker:

```bash
sudo systemctl restart docker
```

The mount MUST be available before Docker starts. Otherwise the daemon may fall back to the system drive or fail to start cleanly.

On macOS and Windows, you MUST use Docker Desktop settings instead of `daemon.json`.

A same-size swapfile helps absorb memory spikes on Linux. On Windows and macOS, you SHOULD keep enough free disk space available for virtual memory and local caches.

## Load Only What You Need

For a broad stack like the Community Hub, you SHOULD start only the services you actually need. If you are working on Discourse, you do not need Mastodon, Pixelfed, PeerTube, or Friendica in the same session.

You MAY pass `disable=<csv>` to `make compose-deploy` to disable services automatically across all applications without editing any file:

```bash
make compose-deploy mode=reinstall apps=web-app-discourse disable=matomo
```

This sets `enabled: false` and `shared: false` for every listed service in the generated inventory. See [variables.md](variables.md) for details.

| Service | Optional | What it provides | Effect of disabling | Safe to disable when |
|---|---|---|---|---|
| `matomo` | 🟢 | Analytics tracking | No usage statistics collected. Usually no functional impact. | You are not testing analytics integration |
| `oidc` | 🟠 | Single sign-on via Keycloak | App falls back to local login | You are not testing SSO/OIDC flows |
| `ldap` | 🟠 | Central user directory via OpenLDAP | App uses its own local user store | You are not testing LDAP/user sync |
| `css` | 🟠 | Custom theming/branding stylesheet | App uses its default upstream theme | You are not testing visual customization |
| `logout` | 🟠 | Shared logout endpoint across apps | Single sign-out does not propagate | You are not testing cross-app logout |
| `dashboard` | 🟠 | Central navigation hub | App is not reachable via the dashboard | You access the app directly by URL |
| `redis` | 🔴 | In-memory cache and session store | Caching and queuing are disabled | The app does not require sessions or queues (rarely safe) |
| `database` | 🔴 | Shared relational database (MariaDB/Postgres) | App cannot persist data | **Never disable.** Required by almost every app. |

**Legend:**

- 🟢 Safe to disable. Usually no functional impact.
- 🟠 Optional. Can be disabled, but reduces functionality.
- 🔴 Required. MUST NOT be disabled.

This is a development profile, not a production target.

When running Playwright tests, you SHOULD only disable `matomo`. All other services (🟠) are REQUIRED for full end-to-end scenario coverage. Disabling them will cause Playwright tests that depend on SSO, LDAP, theming, or logout flows to fail or produce incomplete results.

## Test Smarter

On small machines, you SHOULD limit validation to the role you are touching.

For Discourse, start with:

```bash
make compose-deploy mode=reinstall apps=web-app-discourse disable=matomo
```

If the local inventory and stack already exist, you SHOULD reuse them:

```bash
make compose-deploy mode=update apps=web-app-discourse disable=matomo
```

You SHOULD use `make compose-deploy` (full discovery) only when you need broad coverage and have enough time and resources.

## Measure Before You Delete

You SHOULD check what is actually consuming space before cleaning up:

```bash
make diagnose-disk-usage
```

That makes it easier to see whether the real issue is Docker, journald, a package cache, or project state.

## Cleanup

Run the full cleanup pass to free disk and memory:

```bash
make system-purge
```

On WSL2 or Windows, you MUST pass the additional flag to also configure and run the Windows Disk Cleanup profile.
Windows manages its own system caches independently from Linux and Docker:

```bash
make system-purge PURGE_WINDOWS_CLEANMGR_SETUP=true
```

### Further Information

- [Purge guide](../../../scripts/system/purge/README.md): Canonical entry points for cleanup.
- [Local purge guide](../../../scripts/tests/deploy/local/purge/README.md): Local deploy cleanup helpers.
- [Local reset guide](../../../scripts/tests/deploy/local/reset/README.md): Local state reset helpers.
- [Makefile commands](../tools/make.md): All available make targets.

## Discussion

Discuss this topic in the related [forum article](https://s.infinito.nexus/minpcdev).
