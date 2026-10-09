# Tor SMTP Gateway (svc-net-tor-smtp)

## Description

A small SMTP relay that carries `.onion` recipients over Tor. The active mail
provider (Stalwart) cannot open a SOCKS connection of its own, and a `.onion`
address cannot be reached any other way, so the provider hands every `.onion`
recipient to this gateway as an ordinary SMTP relay target and the gateway dials
`<recipient-domain>:25` through Tor's SOCKS5 listener.

## Overview

```
Stalwart  ──(relay route: rcpt ends_with .onion)──▶  tor-smtp:1525
tor-smtp  ──(SOCKS5, remote DNS)──▶  Tor  ──▶  <recipient>.onion:25
```

Clearnet mail is untouched — it stays on the provider's normal MX delivery. The
gateway only ever accepts `.onion` recipients; it is not an open relay.

## Features

- **Onion-only relay:** accepts a recipient only when its domain ends with
  `.onion`; every clearnet recipient is refused with `550`.
- **Remote resolution:** dials through Tor's SOCKS5 with `proxy_rdns`, so the
  `.onion` name is resolved by Tor and never looked up locally.
- **One hop per domain:** recipients sharing a `.onion` domain are delivered in a
  single SMTP transaction.
- **Clearnet untouched:** normal SMTP reputation, DKIM and SPF delivery never
  pass through Tor.

## Design Decisions

- **A dedicated role, not Stalwart config.** Stalwart has no outbound SOCKS
  support ([stalwartlabs/stalwart#644](https://github.com/stalwartlabs/stalwart/issues/644)),
  so the Tor hop lives in a separate service that only the `.onion` route uses.
- **`proxy_rdns` is on.** A `.onion` has no DNS entry, so Tor must resolve it —
  the name is never resolved locally.
- **Co-located with `svc-net-tor`.** It dials that role's SOCKS listener, so it
  is manager-pinned like the Tor daemon.
