# Mastodon

## Description

Dive into a decentralized social experience with Mastodon, a vibrant platform that redefines online communication with its federated, community-driven approach. With a rich set of features focused on privacy, scalability, and customization, Mastodon empowers users to create, share, and interact in an open social network.

## Overview

This role deploys Mastodon using Docker, streamlining the installation and configuration of a full-featured social networking platform. Mastodon is built to support federation across multiple instances, offering robust content moderation, real-time updates, and flexible API integrations. Its advanced architecture includes separate services for the web frontend, streaming API, and background job processing, ensuring high performance and scalability for large communities.

## Features

- **Decentralized Network:** Connect with users across multiple instances in a federated social media ecosystem.
- **Real-Time Streaming:** Enjoy dynamic updates and real-time content delivery through dedicated streaming services.
- **Robust Content Moderation:** Utilize powerful moderation tools to manage community interactions and maintain safe spaces.
- **Scalable Architecture:** Benefit from a multi-service, Docker-based setup that supports high user loads and seamless background processing.
- **Flexible Authentication:** Integrated support for OpenID Connect (OIDC) simplifies user login and enhances security.
- **Customizable User Experience:** Configure themes, timeline settings, and notification options to tailor the social experience to your community.

## Further Resources

- [Mastodon Official Website](https://joinmastodon.org/)
- [Mastodon Documentation](https://docs.joinmastodon.org/)
- [Mastodon Configuration Guide](https://gist.github.com/TrillCyborg/84939cd4013ace9960031b803a0590c4)
- [Scaling a Mastodon Server](https://www.digitalocean.com/community/tutorials/how-to-scale-your-mastodon-server)
- [Mastodon GitHub Issues](https://github.com/mastodon/mastodon/issues/7958)

## Persona contract opt-outs

[`tasks/05_administrator.yml`](./tasks/05_administrator.yml) creates the account with `tootctl accounts create` and never sets or captures a password, so `ADMIN_PASSWORD` — the Keycloak secret — cannot drive Mastodon's native `/auth/sign_in`; `biber` has no Mastodon account at all, since the OIDC sign-in ([`templates/env.j2`](./templates/env.j2)) is the only path that would create one. In the `services.sso.enabled: false` matrix variants that path is removed, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The SeaweedFS companion scenario ([`files/playwright/test-seaweedfs.js`](./files/playwright/test-seaweedfs.js)) drives the same admin journey and skips on the same flag.
