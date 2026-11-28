# 138 - Onion Mail to External Recipients

## User Story

As an operator of a deployment without TLS (an onion deployment, or any deployment with `tls` off), I want every application to hand outgoing mail to Stalwart with authentication over a network no one outside the deployment can reach, so that mail to external recipients is relayed instead of refused, without opening a mail submission port to the outside.

## Acceptance Criteria

- [ ] Stalwart serves mail submission on port 587 with `AUTH PLAIN` on an internal mail network; today `roles/web-app-stalwart/meta/services.yml` binds only `smtp: 25` and `smtps: 465`, and the onion hidden service forwards only 25 (finding of the lane `funnel/onion-mail-submission`, operator pick 86a631d9cc25a001 option 3 on 2026-11-26).
- [ ] Port 587 is never published and never guarded by a `remote_ip` filter instead (the rejected option O1): it appears under no `ports.public` or `ports.onion` key, the rendered compose file maps no host port to it, and the rendered swarm stack publishes no port for it. A unit test renders both modes and finds no published 587.
- [ ] The internal mail network is a compose bridge network in compose mode and an overlay network with `encrypted: true` in swarm mode, proven by a render test per mode.
- [ ] Stalwart refuses a submission on port 587 that carries no `AUTH`, and accepts one that authenticates as the sending application's mailbox.
- [ ] Every role that sends mail joins the internal mail network when its deployment has `tls` off, and reaches Stalwart by its service name there instead of the host-published port that `plugins/lookup/container_extra_hosts.py` pins today; a lookup test lists the consumer roles and finds each one on that network.
- [ ] On a deployment with `tls` off, `lookup('email')` (`plugins/lookup/email.py`) returns the internal submission endpoint (Stalwart's service name, port 587, authentication on, TLS off), and no longer falls back to the MX on port 25 without authentication; `tests/unit/python/plugins/lookup/test_email.py` pins the new endpoint and has a negative control for the old fallback.
- [ ] A deployment with `tls` on keeps its current submission path on port 465 unchanged, proven by the same lookup test.
- [ ] In an onion CI variant, one application sends a message to an external recipient and Stalwart's log records it as accepted with authentication and queued for relay.
- [ ] The README of `web-app-stalwart` describes the internal mail network, which deployments use it, and why port 587 is never published.
