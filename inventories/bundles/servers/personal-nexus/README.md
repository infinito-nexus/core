# Personal Nexus

## Purpose

A personal digital sovereignty stack for individuals controlling their own data.

## Target Audience

Privacy-conscious users, developers, journalists, and independent professionals.

## Included Components

This bundle activates the following Infinito.Nexus roles:

- web-app-nextcloud
- web-app-keycloak
- web-app-matrix
- web-svc-libretranslate
- svc-prx-openresty

## Architecture Overview

All services are deployed behind a reverse proxy and share a unified authentication layer where applicable.
The inventory defines a single default host named 'server' and activates roles declaratively via group names.
