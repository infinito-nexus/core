# Stalwart

## Description

Runs [Stalwart](https://stalw.art/) — a secure, all-in-one mail and
collaboration server — as the platform's email provider. A single hardened
service speaks **SMTP, Submission, IMAP, POP3, JMAP, ManageSieve, CalDAV,
CardDAV and WebDAV**, with a **built-in spam filter**, **DKIM/DMARC** signing
and a **WebAdmin + REST management API**.

This role replaces the end-of-life [`web-app-mailu`](../web-app-mailu/) role.
Applications send mail through the same provider-agnostic abstraction
(`lookup('email')` / [`sys-svc-mail`](../sys-svc-mail/)) — no consumer changes
are needed beyond the provider repoint.

## Overview

Compared with Mailu's multi-container stack, Stalwart collapses the mail server
into one binary. This role runs:

| Container | Purpose |
|-----------|---------|
| `stalwart` | SMTP/IMAP/JMAP/POP3/Sieve/DAV + built-in spam filter + WebAdmin/REST API |
| `webmail` (Roundcube) | Browser webmail (parity with Mailu) |
| `clamav` | Attachment antivirus, called as an SMTP DATA-stage milter |
| `postgres` *(shared)* | Account / mail / metadata store |

Dynamic state (domains, accounts, passwords, DKIM, certificates) is administered
at runtime via the JMAP management API; `config.json` only bootstraps the data
store. Spam filtering is built into Stalwart; **antivirus** is provided by the
`clamav` container (registered via `x:MtaMilter`, `services.clamav.enabled` —
set it to `false` to run spam-only). Infected mail is rejected at DATA.

```mermaid
flowchart LR
    subgraph edge["Front proxy (TLS)"]
        MAIL_VHOST["mail.<domain> (WebAdmin)"]
        WEBMAIL_VHOST["webmail.<domain> (Roundcube)"]
    end

    subgraph stack["web-app-stalwart compose stack"]
        STALWART["stalwart<br/>SMTP/IMAP/JMAP/POP3/Sieve/DAV<br/>+ WebAdmin + REST API"]
        WEBMAIL["webmail (Roundcube)"]
        CLAMAV["clamav (DATA-stage milter)"]
        PG[("postgres<br/>(shared platform DB)")]
    end

    KC["Keycloak<br/>OIDC directory + SSO"]
    APPS["Platform apps<br/>(no-reply bot via msmtp)"]
    WORLD(("Internet<br/>ports 25/465/587/143/993/..."))

    MAIL_VHOST --> STALWART
    WEBMAIL_VHOST --> WEBMAIL
    WEBMAIL -- "IMAP 993 / SMTP 465<br/>XOAUTH2 (stalwart-webmail client)" --> STALWART
    STALWART -- "milter" --> CLAMAV
    STALWART --- PG
    STALWART -- "OIDC directory<br/>(token validation)" --> KC
    MAIL_VHOST -. "SPA login: PKCE<br/>(stalwart-webui client)" .-> KC
    WEBMAIL_VHOST -. "OAuth login" .-> KC
    APPS -- "SMTPS :465, AUTH<br/>(bot credential from the token store)" --> STALWART
    WORLD <-- "public mail ports<br/>(only when active MAIL_PROVIDER)" --> STALWART
```

## SSO (Keycloak / OpenID Connect)

When `web-app-keycloak` is present the role joins the shared Keycloak client and
delegates **interactive** authentication to Keycloak:

- **WebAdmin + IMAP/SMTP/JMAP** authenticate against an **OIDC directory**
  (`tasks/06_oidc.yml`): Stalwart validates Keycloak-issued tokens and resolves
  the `preferred_username` claim to the account `<preferred_username>@<mail domain>`
  (a claim that already holds an `@` is taken as is), creating it on first login.
- **Roundcube** logs users in over OAuth2 and talks to Stalwart with **XOAUTH2**
  (`templates/roundcube-oauth.inc.php.j2`).
- The OIDC directory skips the audience check and gives Keycloak tokens without
  Stalwart scopes access to mail, contacts, calendars and files
  (`STALWART_OIDC_TOKEN_VALIDATION`). Tokens of the `stalwart-webui` client get
  full access, because the WebUI Application names it as its `oauthClientId`.

**Design constraint (validated against the live JMAP schema):** Stalwart's
authentication directory is *Internal XOR one external directory* — there is no
chaining or fallback. Enabling SSO therefore **disables the account password**
for every account, including the machine `no-reply` account. App passwords are
checked before the directory and keep working, so with SSO enabled the role:

1. Creates one app password per bot account as the recovery admin, which
   addresses each bot account through its JMAP `accountId`
   (`tasks/04_manage_user/app_password.yml`), and
2. Stores it in the token store, where
   [`plugins/lookup/email.py`](../../plugins/lookup/email.py) reads the SMTP
   password of the `no-reply` client.

A bot gets a new app password when its entry named
`STALWART_BOT_APP_PASSWORD_DESCRIPTION` is deleted in Stalwart or its token is
removed from the token store. The app password it replaces is renamed to
`STALWART_BOT_APP_PASSWORD_RETIRED_DESCRIPTION` and stays valid until the
service-loader post-load flush drops it
(`tasks/04_manage_user/app_password_drop.yml`), or until right after the new
one is stored when the role runs outside the service loader. A deploy that
stops before the flush leaves it to the next deploy. Relaying stays limited to
authenticated sessions in both modes (`STALWART_RELAY_RULE`).

With SSO disabled the role uses the Internal directory and the bot's derived
account password.

## WebUI sign-in

The WebUI Application always names `stalwart-webui` (`STALWART_WEBUI_OAUTH_CLIENT_ID`) as its `oauthClientId`, with and without SSO.
Where the WebUI sends a login depends on the account:

| Account | Authorization server | Client `stalwart-webui` |
|---|---|---|
| Account in a domain bound to the Keycloak OIDC directory | Keycloak | Keycloak client from `templates/keycloak/clients.json.j2` |
| Recovery admin (`STALWART_ADMIN_USER`), and every account while SSO is off | Stalwart | OAuth client the role registers in Stalwart (`tasks/02_webadmin.yml`) |

The role registers that Stalwart client over JMAP (`templates/jmap/oauth_client/`) as a public first-party client, with one redirect URI `<origin>/<prefix>/oauth/callback` and one post-logout URI `<origin>/<prefix>/login` per origin and URL prefix of the WebUI Application.
The origins are the role's canonical WebUI URL (`STALWART_WEBUI_BASE_URL`) in every network the node serves it on (`lookup('network_urls')`), so a Tor deployment registers its `http://` onion origin next to the clearnet one.
Every deploy compares the registered client with that target and updates it when they differ.
An origin that is no network sibling of the canonical WebUI URL MUST be added in [`templates/jmap/oauth_client/webui.json.j2`](templates/jmap/oauth_client/webui.json.j2), because a URI added in Stalwart alone is removed by the next deploy.
Stalwart's login page asks for consent for the client after the password form, so a native WebUI login shows an **Allow** step.

## Calendar & Contacts (CalDAV / CardDAV / WebDAV)

Stalwart serves DAV natively on the mail HTTP listener — no extra container
(Mailu used a separate Radicale service). Clients auto-discover via
`https://mail.<domain>/.well-known/{caldav,carddav}`, which redirect to
`https://mail.<domain>/dav/cal` and `/dav/card`. Authenticate with the mailbox
account (or the Keycloak SSO token when SSO is enabled).

## Design Decisions

- **Client ports are implicit-TLS only (465/993/995).** Stalwart's default
  configuration binds no STARTTLS listeners, so the role neither publishes
  587/143/110 nor advertises them via SRV records.
- **The WebUI (WebAdmin) bundle is staged by the controller.** Stalwart fetches
  it from GitHub on first boot, which fails behind restricted egress; the
  controller downloads it into a host-level cache (matrix rounds purge the
  instance dir, and per-round downloads hit GitHub rate limits) and bind-mounts
  it read-only. The `update:` block next to `webui_version` in
  `meta/services.yml` names the upstream tags, so the version-source updater
  bumps the bundle on its own, within the `v2.` line that server 1.x serves.
- **The embedded PostgreSQL pins the plain `postgres` image** — the platform's
  postgis default defeats baudolo's substring database detection and would
  degrade backups to torn live-file snapshots. `backup.project_hard_restart`
  brings the whole project back through one coherent restart after baudolo's
  per-volume stop/start cycles.
- **ClamAV runs fail-open with short milter timeouts** so mail keeps flowing
  while clamd warms its signature database instead of blocking the DATA stage.
- **DMARC aggregate reports go to the mailbox of
  `services.stalwart.dmarc.rua_user`** (the `platform_administrator` user unless the
  inventory names another user key). The `_dmarc` record publishes
  `rua=mailto:<username>@<mail domain>`, and a deploy whose report user carries
  no `mailbox` account fails before any record is written.
- **`config.json` is bootstrap-only** (data store selection); all other
  configuration lives in the database and is provisioned over JMAP
  (`templates/jmap/*.json.j2`).
- **Only authenticated sessions relay, with or without SSO.** Under SSO a bot
  authenticates with an app password.
- **Accounts, app passwords and forwards are provisioned in batches.** Each
  phase (create, password update, app password list, mint, retire, drop,
  forward script list, read, upload, activate) is one JMAP request for all
  accounts. A phase on the bots' app passwords or the forward scripts carries
  one method call per account, addressed through its `accountId` by the
  recovery admin, at most `STALWART_JMAP_MAX_METHOD_CALLS` (Stalwart's default
  `maxMethodCalls`) per request, and a refusal names the account it hit.
- **Address bans expire after `services.stalwart.ban_period_seconds`** (one
  hour by default). Without a period Stalwart keeps a ban forever, and the
  reverse proxy, the published ports, Tor and the swarm ingress hand many
  clients one address.
- **The role network's gateway is never banned** (`STALWART_ALLOWED_IPS`,
  an `x:AllowedIp` entry): every container that reaches the published ports
  through the host arrives from that address.
- **HTTP clients are rate-limited and banned by their own address.** The
  vhost sets `proxy_forwarded_client_address`, so OpenResty sends
  `Forwarded: for=$remote_addr` on every location and replaces any
  client-supplied value, and Stalwart reads it (`STALWART_HTTP_SETTINGS`:
  `clientIpSource: forwarded` with one trusted hop, `forwardedHops: 1`).
- **Bans and failed logins also go to the container output**
  (`STALWART_BAN_TRACER`, `tasks/tracing.yml`), next to the daily log file in
  the data volume.

## Features

- All-in-one mail server (SMTP/IMAP/JMAP/POP3/ManageSieve)
- CalDAV / CardDAV / WebDAV collaboration
- Built-in spam filtering
- ClamAV antivirus as an SMTP DATA-stage milter (`services.clamav.enabled: false` for spam-only)
- DKIM signing with automatic key management; SPF / DMARC published in DNS
- OpenID Connect SSO via Keycloak
- Roundcube webmail
- PostgreSQL backing store

## Migration from Mailu

The provider cutover is an inventory change; mailbox data moves with it when the migration switch is on.

> **Compose only.** The import reads the legacy maildir volume on the stack host and submits over the host-published IMAPS port, neither of which holds under swarm. Migrate in compose mode, then move the stack to swarm.

1. Keep `web-app-mailu` in the host's groups and add `web-app-stalwart` — both MUST be present so Mailu re-renders as a legacy instance (`legacy-mail.<domain>`, no public mail ports) and releases `mail.<domain>` to Stalwart.
2. Remove `MAIL_PROVIDER` from the inventory (Stalwart is the default).
3. Declare the [aliases](#aliases-and-forwards) the Mailu instance had, and a `mailbox_map` entry for every Mailu mailbox that belongs in another Stalwart account (see below).
4. Set `applications["web-app-stalwart"].services.stalwart.migration.import_mailu: true` and run the full deploy. The role reads every `<address>/` directory in Mailu's Dovecot Maildir volume, whether or not the address is an inventory user, and per mailbox:
   - skips it and reports the address when Stalwart does not serve its domain; no domain is created,
   - creates the Stalwart account when it is missing, named after the local part in the mailbox's domain, which is the account the OIDC directory resolves for that `preferred_username` once SSO is on,
   - appends its messages over IMAPS in parallel sessions, `migration.workers` of them or by default one fewer than the host's vCPUs, at most 8, logged in as the recovery administrator acting for the account (`<address>%<admin>`), so no per-mailbox password is needed and the import works with or without `services.sso.enabled`; a session Stalwart refuses only lowers the parallelism,
   - keeps folders, flags, Dovecot keywords and internal dates; Mailu's `Sent`, `Trash`, `Junk`/`Spam` and `Drafts` land in the folders Stalwart marks with the matching special use,
   - imports the active Sieve script and activates it.

   A host without Mailu's maildir volume gets a note that there is nothing to import. Otherwise the deploy starts the import as the transient unit `stalwart-mailu-import` and moves on; a deploy that finds the unit still running leaves it alone. Follow it with `journalctl -fu stalwart-mailu-import`: it logs `[PROGRESS]` every 1000 messages of a folder, one `[MAILBOX] <mailbox> -> <account>: found=<n> imported=<n> skipped=<n> failed=<n> sieve=<state>` line per mailbox, one line per folder below it, `[SKIP]` for every mailbox outside the served domains, a closing `[SUMMARY]` and `[DONE] rc=<n>`. When the unit stops, it removes the staged credentials. An import that ends with `[DONE] rc=0` leaves the marker `.mailu-import.done` in the Stalwart instance directory, and no later deploy starts the import again while it exists; delete the marker to import again. A failed import leaves no marker, so the next deploy repeats it, and the repeat imports nothing twice: a message is skipped when its Message-ID, or without one its Date/From/To/Subject, is already in the target folder, and a Sieve script with unchanged content is left alone. Turn the switch off once Mailu is retired.
5. Non-Cloudflare DNS: publish the new DKIM TXT record reported by the deploy; MX and A records keep their hostname.

A `mailbox_map` entry merges a Mailu mailbox into another account instead of creating its own:

```yaml
applications:
  web-app-stalwart:
    services:
      stalwart:
        migration:
          import_mailu: true
          mailbox_map:
            - source: alice@example.org
              target: alice.smith@example.org
```

The source's folders merge into the target's folders under the same Message-ID dedup, and its active Sieve script is imported as `<source local part>-<script name>` and activated after the target's own. Declare the source address as an alias of the target so its mail keeps arriving. A target outside the served domains fails the import before anything is written, and a mailbox whose address is an alias but not mapped is reported as failed.

Not migrated: CalDAV/CardDAV data, Mailu's own forward and autoreply settings (declare forwards in the inventory) and Mailu's fetchmail jobs. Stalwart v0.16 has no fetcher for external IMAP or POP3 accounts; replace such a job with forwarding at the external provider.

The cutover is covered end to end by [`files/test/test.sh`](files/test/test.sh), which runs as this role's CLI test whenever `web-app-mailu` is co-deployed in compose. The whole scenario runs inside the deployed host and needs nothing from the environment around it: it stores mail in both directions in the legacy Mailu, seeds a mailbox that is no inventory user (with a subfolder, flags, a fixed internal date and an active Sieve script), a mailbox in a domain Stalwart does not serve and, in matrix **variant 1**, a mapped mailbox, runs [`files/python/migrate_from_mailu.py`](files/python/migrate_from_mailu.py) with the argv a real cutover uses, and asserts over IMAP and JMAP that everything arrived where it belongs, that the Sieve script files new mail, that the foreign domain was not created and that a second run imports nothing. No redeploy is involved; the cutover is a docker-level data move.

## Aliases and Forwards

Aliases and per-account forwards are declared under `services.stalwart` and provisioned on every deploy, in compose and in swarm:

```yaml
applications:
  web-app-stalwart:
    services:
      stalwart:
        aliases:
          - address: "@example.org"
            destinations: [alice.smith@example.org]
          - address: team@example.org
            destinations: [alice.smith@example.org, bob@example.net]
        forwards:
          - address: carol@example.org
            destinations: [carol@example.net]
```

- The address `@<domain>` is that domain's catch-all. It takes exactly one destination, which becomes the domain's catch-all address.
- Every other alias becomes a Stalwart mailing list described as `Infinito.Nexus alias`. The role creates, updates and removes only lists with that description; lists created in WebAdmin stay untouched, and declaring an address such a list already holds fails the deploy.
- Destinations may lie outside the served domains; Stalwart relays those copies.
- Alias domains must be served by Stalwart.
- A forward keeps the message in the account and sends a copy to every destination. The role writes the Sieve script `infinito-forward` (`redirect :copy`) into the account and activates it; a user script that was active is chained through `include`, so personal filters keep working. Removing a forward from the inventory leaves the script in place; delete `infinito-forward` in the account's filter settings to stop it. The role raises the user-script limits `maxRedirects` and `maxOutMessages` to the widest forward.

[`files/test/test.sh`](files/test/test.sh) sends through every declared alias, catch-all and forward and waits until each destination inside the mail domain holds its copy. An alias destination outside it counts once Stalwart queued the copy or the bounce naming it and the subject reaches the sender, which proves Stalwart expanded the alias and attempted the delivery. A forward destination outside it counts once the account's active Sieve script redirects a copy to it, because Stalwart sends no bounce for a message a Sieve script generated. Matrix **variant 1** declares one of each.

### Alias domains

A legacy domain that only receives mail is declared under `services.stalwart.alias_domains`; `<local>@<source>` is then delivered to `<local>@<target>`:

```yaml
applications:
  web-app-stalwart:
    services:
      stalwart:
        alias_domains:
          - source: legacy.example
            target: example.org
```

- The deploy sets the `rewrite` expression of Stalwart's RCPT stage to one `matches()` rule per alias domain and reads it back.
- With Cloudflare as `DNS_PROVIDER`, the deploy points the MX record of every source at the mail hostname.
- The source is not served by Stalwart and gets no DKIM key; it receives mail but sends none.
- Removing every alias domain leaves the last rewrite in Stalwart; set the RCPT stage's rewrite back to `false` in WebAdmin.

## Upgrading from 0.16

Stalwart 1.x refuses to open a 0.16 store and has no in-place upgrade. Every deploy checks the store in the role's database before it starts Stalwart, whatever state the running server is in, and stops when the store predates 1.0 ([`tasks/store_guard.yml`](tasks/store_guard.yml)). A store from before 1.0 keeps a `bigint` column `v` in table `u`, a 1.x store a `bytea` one, and a database without that column holds no store yet.

A deploy that has brought Stalwart 1.x up on the store and finished its provisioning writes the marker `store.layout`, holding the store layout version `1`, into the role's instance directory on the stack host (`STALWART_STORE_MARKER_FILE`, written last in [`tasks/manager_ops.yml`](tasks/manager_ops.yml)).
A failed deploy writes no marker.
A deploy that finds the marker passes without reading the store.
A deploy without the marker reads the store:

| Database | No store yet | Store to read |
|---|---|---|
| Shared PostgreSQL | the `postgres` superuser finds no database `stalwart` in the catalog | read as the role's database user |
| Dedicated PostgreSQL | the volume `stalwart_database` does not exist | read inside the dedicated database container; when that container is not running, the deploy stops and names the database service to start |

Migrate the store with [`stalwart-migrate`](https://github.com/stalwartlabs/stalwart-migrate) into a new database and swap it in under the role's database name. That name is fixed to `stalwart` ([`plugins/lookup/database.py`](../../plugins/lookup/database.py) derives it from the entity name), so the migration targets a second database that later takes over the name.

A deploy whose store guard finds a 0.16 store migrates it on its own ([`tasks/store_guard/migrate.yml`](tasks/store_guard/migrate.yml)): it stages `migrate-v016/migrate.sh` in the role's instance directory (`STALWART_MIGRATE_SCRIPT`, a copy of [`files/shell/migrate_v016.sh`](files/shell/migrate_v016.sh)), the values it reads in `migrate.env` ([`templates/migrate.env.j2`](templates/migrate.env.j2)) and the target configuration, runs the phases below from `upgrade` to `final`, reads the store layout again and deploys Stalwart 1.x on the migrated store. Mail is down from the stop in `final` until the deploy starts 1.x. A failing phase stops the deploy with the 0.16 store and server back in place. The phases also run by hand, as root:

| Phase | Steps below |
|---|---|
| `upgrade` | 1: pulls the floating tag of the source series the `stalwart_migrate` image names in its `--help` banner (`v0.16`, the last 0.16 release) and recreates Stalwart on it when the running image differs (compose: `compose -f compose.upgrade.yml up -d`, swarm: `service update --image`) |
| `check` | 1: the running Stalwart must be that exact image and the role's `version` must belong to the banner's target series; plus the guard's own conditions: 0.16 store, no swap yet, no marker |
| `backup` | 2, the database dump only |
| `target` | 3 |
| `prepare` | 5, interactive on a terminal; without one it accepts the recommended answer of every question `stalwart-migrate` marks as not answered in `migrate-v016/state/answers.toml` |
| `sync` | 5, repeatable while 0.16 serves |
| `final` | 6 and 7 |
| `status` | the progress `stalwart-migrate status` reports |
| `all` | `upgrade` to `final` in order |

Then deploy again (step 8). The steps by hand:

1. Make sure the server runs Stalwart `v0.16.27`; `stalwart-migrate` reads no other release. Upgrade an older 0.16 server with the previous revision of this role first.
2. Back up the database `stalwart` (for example `pg_dump -Fc -d stalwart -f stalwart-v016.dump`) and the role's volumes.
3. As a PostgreSQL superuser, create the empty target database, owned by the role's database user:

   ```sql
   CREATE DATABASE stalwart_v1 OWNER stalwart;
   ```

4. Copy the rendered `config.json` (`STALWART_CONFIG_FILE`, `etc/config.json` in the role's volumes directory) into a new directory and set its `"database"` to `"stalwart_v1"`. This file is the `--target`.
5. Answer the conversion questions and copy the data while 0.16 keeps serving. Run the tool on the network the `stalwart` container reaches its database on (`docker inspect stalwart`), so the hosts in both files resolve:

   ```sh
   docker run --rm -it --network <stalwart-network> \
     -v <volumes-dir>/etc:/etc/stalwart:ro \
     -v <target-dir>:/etc/stalwart-v1 \
     -v <state-dir>:/var/lib/stalwart-migrate \
     stalwartlabs/stalwart-migrate:1.0.0 prepare \
       --source /etc/stalwart/config.json \
       --state /var/lib/stalwart-migrate
   ```

   Then run the same container with `run --source /etc/stalwart/config.json --target /etc/stalwart-v1/config.json --state /var/lib/stalwart-migrate`. `run` copies only what changed since the previous run and may be repeated.
6. Stop the Stalwart server (`docker stop stalwart` in compose, `docker service scale <stack>_stalwart=0` in swarm) and run the same container with `run --final` and the same options. It verifies the copy and writes `final-report.txt` into the state directory.
7. Swap the databases, as a PostgreSQL superuser connected to the `postgres` database:

   ```sql
   ALTER DATABASE stalwart RENAME TO stalwart_v016;
   ALTER DATABASE stalwart_v1 RENAME TO stalwart;
   ```

8. Deploy this role. The store guard finds the migrated 1.x store under the role's database name and lets Stalwart 1.x start on it.
9. Keep `stalwart_v016`, the dump and the state directory until 1.x is verified. `stalwart-migrate rollback` reads the state directory to copy the 1.x store back into a new 0.16 store.

### Restore and redeploy

The marker lives outside the stack and its volumes, so it survives `docker stack rm`, `docker compose down`, a crashed database and the stop and start cycle of `backup.project_hard_restart`.
A host that carries the marker therefore redeploys while its dedicated database is down, as in the restore of [`svc-bkp-nfs-2-local`](../svc-bkp-nfs-2-local/README.md) (`docker stack rm`, restore, redeploy).
A dedicated store on a host without the marker, such as a 0.16 host or a host whose instance directory was lost, needs its database running before the deploy: start the database service of the stack the host last deployed, then deploy.
Before a host that carries the marker goes back to a 0.16 store, through `stalwart-migrate rollback` or a backup taken under 0.16, delete the marker, so the next deploy reads the store.

## Verifying a production server

Deploying against a publicly reachable mail server additionally asserts that server's live **hard facts** — the records and listeners either match the deployed configuration or they do not. There is no mail-flow scenario here; that is what the suites above are for.

Set `INFINITO_MAIL_PRODUCTION_HOST` to the server's public FQDN (in CI, a GitHub repository variable of the same name; empty disables the whole check). Optionally set `INFINITO_MAIL_PRODUCTION_RESOLVER` to the address of a public resolver so the records are read from the outside view instead of `/etc/resolv.conf`, which matters on a host whose own resolver answers from a split-horizon zone.

[`files/python/production_facts.py`](files/python/production_facts.py) then checks, read-only:

| Fact | Assertion |
|---|---|
| A / AAAA | the mail host resolves |
| MX | the zone's only MX is the mail host (the role publishes it `solo`) |
| SPF | exactly one `v=spf1` record, authorising `mx` or `a:<mailhost>` |
| DMARC | `_dmarc` publishes a `v=DMARC1` record with a policy whose `rua` names the deployed aggregate report mailbox |
| DKIM | the selector this deploy read back publishes a non-empty `v=DKIM1` key |
| SRV | `_submissions`/465, `_imaps`/993, `_pop3s`/995 point at the mail host |
| PTR | rDNS does not contradict the mail host (absent → warning; rDNS is provisioned for Hetzner only) |
| SMTP | port 25 greets with `220` carrying the FQDN, proving the `rejectNonFqdn` identity |

The same variable points [`sys-ctl-mtn-cert-deploy`](../sys-ctl-mtn-cert-deploy/)'s remote check at `:465` and `:993`, so the live TLS chain and its remaining validity are verified alongside. A misconfigured production server therefore fails the deploy instead of surfacing as an outage.

## Further Resources

- [Stalwart documentation](https://stalw.art/docs)
- [`sys-svc-mail`](../sys-svc-mail/) — how applications send mail
- [`plugins/lookup/email.py`](../../plugins/lookup/email.py) — the email abstraction
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/FzjQ2ZyfFbvctv2YaPTgLK)

> **Note:** Stalwart's JMAP object schema is version-sensitive. Pin
> `services.stalwart.version`; the provisioning payloads in `tasks/` were
> validated against that release's `GET /api/schema`.
