# Dashboard

## Description

A lightweight, Docker-powered UI framework that offers Infinito.Nexus users a unified interface to access all their applications in one intuitive dashboard. 🚀

## Overview

Tailored for creative professionals and developers, this role streamlines the process of setting up a portfolio site. It automates tasks such as Docker container configuration, dynamic routing via NGINX, and repository integration, so you can concentrate on perfecting your content and design. Enjoy a responsive layout and easy-to-modify YAML files that let you rapidly update your online presence without deep technical intervention.

## Purpose

The purpose of tthis role is to simplify the deployment and management of a personal or professional portfolio. By focusing on usability and a clean presentation, the role helps you:

- Quickly launch a professional-looking website.
- Customize and update your portfolio content effortlessly.
- Integrate seamlessly with complementary roles for Docker Compose and web server management.
- Reduce manual configuration and maintenance tasks.

## Features

- **Unified Navigation**: Central menu bar with the same nested folders as the folder view.
- **Folder View**: `vars/menu_categories.yml` holds a nested folder tree; an application appears in every folder whose `tags` share one of its galaxy tags, and in the `fallback` folder when no other folder takes it. The view opens at the top level and keeps the open folder in `?folder=` and the search in `?q=`. Switch it off per inventory with `services.dashboard.folders: false`.
- **Search, Favourites and Recently Used**: a search field in the header finds every application by title, description, tags and folder names; pinned and recently opened applications sit at the top level.
- **Access Locks**: a role-gated application (`services.sso.oauth2.allowed_groups`) shows a lock on its tile when the signed-in user holds none of its groups; the lock links to `web-svc-access-request` when that service is deployed, and asks an anonymous visitor to sign in. The tile always stays clickable, the SSO gate decides. Switch the locks off with `services.dashboard.locks.enabled: false`.
- **Health Badges**: every tile shows the state the webserver health sweep wrote to `/status.json` (running, paused by Semaphore, degraded, down, unknown); `services.dashboard.status` sets the poll interval and the age after which an entry counts as unknown, and `services.dashboard.status.enabled: false` switches the badges off.
- **Chips**: `templates/javascript/chips.js.j2` sets the locks and badges through port-ui's chip API (`window.portui.chips`); port-ui only renders them.
- **New Badge**: an application deployed after the host's first-deploy record was created carries a "New" badge for `services.dashboard.new_days` days.
- **Customizable Tiles**: Showcase applications with title, description, and icons, fully configurable via YAML.
- **Responsive Design**: Optimized for desktop, tablet & mobile, built on Bootstrap.
- **Interactive Icons**: Automatic integration of Simple Icons for popular brands and tools.
- **Seamless IFrame Embedding**: Launch apps directly within the UI or open in new tabs.
- **YAML-Driven Configuration**: Define all content & structure easily in `config.yaml`.
- **Fast Access**: Automatic cache management ensures lightning-fast load times.
- **Login methods**: SSO only. The dashboard keeps no accounts of its own, so its one sign-in entry is the Keycloak `Login` link that `oidc.js` renders while `services.sso.enabled` is true; there is no local form, no registration and no break-glass account to protect, so `meta/services.yml` marks the `sso` key `nocheck: login-methods` instead of declaring a `login.method` block.

## Further Resources

- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/J5Qb5EVNRNxnaTkVQZqxDp)

## Persona contract opt-outs

Both authenticated Playwright personas are blocked while `services.sso.enabled` is false. The dashboard's entire Keycloak integration is the browser-side `oidc.js` bundle, and `DASHBOARD_JS_FILES` in `vars/main.yml` ships that file only when SSO is enabled, so with SSO off the page renders neither a Login link nor a logout control.

port-ui is a tile launcher with no admin tier, so the `administrator` persona has no admin-only surface to assert against beyond the same login chain. With SSO enabled both personas run.
