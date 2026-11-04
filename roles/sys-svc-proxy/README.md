# NGINX Docker Reverse Proxy

## Description

This Ansible role deploys **NGINX** as a high-performance [reverse proxy](https://en.wikipedia.org/wiki/Reverse_proxy) in front of Docker-hosted services.  
It provides automatic TLS integration, WebSocket support, and a flexible templating system for per-application configuration.

## Overview

Optimised for Arch Linux, the role installs NGINX, prepares opinionated configuration snippets and exposes a simple interface for other roles to drop in new virtual-hosts.  
It plays well with **Let’s Encrypt**, **OAuth2 Proxy**, and your existing Docker stack.

## Purpose

The goal of this role is to deliver a **hassle-free, production-ready reverse proxy** for self-hosted containers, suitable for homelabs and small-scale production workloads.

## Features

- **Automatic TLS & HSTS**: integrates with the *sys-svc-webserver-https* role for certificate management.  
- **Flexible vHost templates**: *basic* and *ws_generic* flavours cover standard HTTP and WebSocket applications.  
- **Security headers**: CSP from each role's `meta/csp.yml`, plus the per-role headers described in [Security Headers](#security-headers).  
- **WebSocket & HTTP/2 aware**: upgrades, keep-alive tuning, and gzip already configured.  
- **OAuth2 gating**: drop-in support when *web-app-keycloak's SSO-proxy sidecar* is present.  
- **Modular includes**: headers, locations, and global snippets are factored for easy extension.

## Security Headers

`WEBSERVER_SECURITY_HEADERS` in [04_webserver.yml](../../group_vars/all/04_webserver.yml) holds the platform values. A role overrides any key under `security_headers` in its `meta/server.yml`; an inventory overrides it at `applications.<role>.server.security_headers`.

```yaml
# roles/<role>/meta/server.yml
security_headers:
  nosniff: true
  referrer_policy: strict-origin-when-cross-origin
  permissions_policy: 'camera=(self "https://meet.example.org"), microphone=(self)'
  hsts:
    include_subdomains: true
    preload: true
```

| Key | Header | Where it is rendered |
|---|---|---|
| `nosniff` | `X-Content-Type-Options: nosniff` | every response of a location that includes [content_security_policy.conf.j2](templates/headers/content_security_policy.conf.j2) |
| `referrer_policy` | `Referrer-Policy` | the same locations, only when the upstream sends none |
| `permissions_policy` | `Permissions-Policy` | HTML documents of the same locations |
| `hsts.*` | `Strict-Transport-Security` | the server block of every TLS vhost, via [nginx_ssl_header.j2](../sys-front-tls/templates/nginx_ssl_header.j2); an onion vhost has no TLS and gets none |

The `security_headers` filter rejects unknown keys, wrong types, unknown `Referrer-Policy` tokens, and `preload` without `include_subdomains` or below a one-year `max_age`.
