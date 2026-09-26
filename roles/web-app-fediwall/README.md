# Fediwall

## Description

**Fediwall** is a self-hosted *media wall* for the Fediverse: it follows hashtags or accounts on Mastodon-compatible servers and shows the most recent public posts in a screen-filling, self-updating masonry grid.

## Overview

Fediwall is a static, single-page web application with no backend, no database, and no user accounts. Configuration lives in a `wall-config.json` next to `index.html` and can be overridden per-visitor through URL parameters.

This role bakes the upstream release artefact into a small `nginx:alpine` image and supports **multiple walls per deployment**: every entry under [`meta/services.yml.fediwall.walls`](meta/services.yml) materializes as its own path under `https://fediwall.<DOMAIN_PRIMARY>/<slug>/` with its own baked-in `wall-config.json`. The root `/` shows a link list of all configured walls.

A wall's `config.servers` may be left empty to auto-fill with the active Mastodon-API-compatible Fediverse siblings (`web-app-mastodon`, `web-app-pixelfed`, `web-app-friendica`) that are present in the current host's `group_names`. Every other field of `wall-config.json` is read verbatim from the wall's `config` block.

## Features

- **Follow hashtags, accounts, or trends** across multiple Mastodon-compatible servers.
- **Visually pleasing**, screen-filling masonry grid that scales from tablets to LED walls.
- **Dark mode** and customizable theme.
- **Privacy-friendly**: no server-side state, no tracking, all logic runs in the browser.
- **Live customization**: viewers can override every setting through URL parameters and bookmark or share their personalized wall.
- **Multi-wall**: declare multiple purpose-built walls (per event, hashtag, account set, …) under one deployment.

## Further Resources

- [Fediwall GitHub Repository](https://github.com/defnull/fediwall)
- [Public demo: fediwall.social](https://fediwall.social/)

## Persona contract opt-outs

Both authenticated Playwright personas are blocked. Fediwall is a read-only public wall: `meta/services.yml` pins `sso.enabled: false` and `logout.enabled: false`, and the container is a plain nginx image serving the pre-built upstream tarball. There is no account model, no login form and no logout control.

Wall content is baked at deploy time from `services.fediwall.walls`, so administration happens in Ansible rather than in an in-app admin panel. The persona-facing coverage this role does carry lives in the cross-fediverse scenarios that post on a Mastodon or Friendica sibling and assert the post appears on the wall.
