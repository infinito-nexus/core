# Education Suite

## Purpose

A complete digital learning environment for schools, academies, and universities.

## Target Audience

Educational institutions seeking an integrated platform for learning management, collaboration, and virtual classrooms.

## Included Components

This bundle activates the following Infinito.Nexus roles:

- web-app-moodle
- web-app-nextcloud
- web-app-bigbluebutton
- web-svc-onlyoffice
- web-app-openwebui
- web-app-email
- web-app-keycloak

## Architecture Overview

All services are deployed behind a reverse proxy and share a unified authentication layer where applicable.
The inventory defines a single default host named 'server' and activates roles declaratively via group names.
