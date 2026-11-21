# TODO

- The role sets no upstream DNS servers: Pi-hole v6 dropped the `PIHOLE_DNS_` variable the role used to render from `services.pihole.upstream_dns`, so both were removed as dead keys ([072](../../docs/requirements/072-sso-profile-field-sync-or-lock.md)). Options: render `FTLCONF_dns_upstreams` from `NETWORK_PUBLIC_DNS_RESOLVERS`, which the settings UI then shows read-only, and declare it `enforced` in `meta/forms.yml`.
