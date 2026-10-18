# Corporate Design Injection for NGINX

## Description

This Ansible role injects the corporate design into every NGINX-served application whose `design` service is enabled.
It derives the design tokens from the single base color in `web-svc-design` through the [design_palette](../../plugins/lookup/design_palette.py) lookup (OKLCH, WCAG 2.2 contrast by construction) and maps them onto Bootstrap and common app variables.

## Overview

The role renders the shared `default.css` and `bootstrap.css` once per deployment onto the CDN, links them with a cache-busting version, and adds the role's own `style.css` and `design.js` when the role ships them.
Light and dark tokens switch with `prefers-color-scheme`; a role mirrors an app-native theme switch through `<html data-design-theme="light|dark">`.

## Purpose

The goal of this role is to provide a **single source of truth for theming** across your infrastructure.  
It makes all applications feel like part of the same ecosystem, visually and functionally.

## Features

- 🎨 **Semantic design tokens** derived from one base color in OKLCH
- ♿ **WCAG 2.2 contrast** guaranteed for text, links, controls and status colors
- 📁 **Unified CSS Base Configuration** deployment for all NGINX applications
- 🌒 **Dark mode** via `prefers-color-scheme` or an app-native switch
- 🧩 **Design script channel** for a role's `design.js.j2`
- 🚫 **No duplication** – tasks run once per deployment
- ⏱️ **Versioning logic** to bust browser cache
- 🎯 **Bootstrap override compatibility**
- 🧩 **Theme support for Keycloak, Nextcloud, Gitea, LAM, Peertube, and more**
