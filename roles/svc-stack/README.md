# svc-stack

## Description

Provider of the shared `stack` service. Every application that ships a compose project or serves a vhost declares `stack` in its own `meta/services.yml`, so [sys-service-loader](../sys-service-loader/README.md) resolves the service as required and loads this role once per host in the dependency phase, ahead of the application roles.

## Overview

The role is the single point of truth the stack consumers bind to, as specified in [045 Stack Service](../../docs/requirements/045-stack-service.md). The per-application stack work still runs through the stack includes in each application role until the batch moves into this role.

## Features

- **Service provider:** Owns the `stack` service key; its primary entity is enabled and shared, so the service registry discovers it.
- **Once per host:** Sets its run-once flag on the first load, so later loads in the same play skip it.
