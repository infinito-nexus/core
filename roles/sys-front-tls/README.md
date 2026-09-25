# sys-front-tls

## Description

Generic TLS orchestrator that can be plugged in front of any web app reverse proxy.

## Overview

Provide a unified interface for certificates and protocol selection, so application roles
can switch TLS mode without touching app logic.

Supported modes (resolved outside or passed in):

- letsencrypt  -> use (and if missing: issue) Let's Encrypt certs
- self_signed  -> generate and store a self-signed certificate (SAN aware)
- off          -> no TLS, HTTP only

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
