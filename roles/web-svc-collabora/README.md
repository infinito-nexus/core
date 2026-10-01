# Collabora

## Description

This Ansible role deploys Collabora Online (CODE) in Docker to enable real-time, in-browser document editing for Nextcloud. It automates the setup of the Collabora CODE container, NGINX reverse proxy configuration, network isolation via Docker networks, and environment variable management.

## Overview

* **Dockerized Collabora CODE:** Uses the official `collabora/code` image.
* **NGINX Reverse Proxy:** Configures a public-facing proxy with TLS termination and WebSocket support for `/cool/` paths.
* **Docker Network Management:** Creates an isolated `/28` subnet for Collabora and connects containers securely.
* **Environment Configuration:** Generates a `.env` file with domain, credentials, and extra parameters for Collabora's WOPI server.

## Features

* Automatic creation of a dedicated Docker network for Collabora.
* Proxy configuration template for NGINX with long timeouts and WebSocket upgrades.
* Customizable domain names and ports via Ansible variables.
* Support for SSL termination at the proxy level.
* Integration hooks to restart NGINX and recreate Docker Compose stacks on changes.

## Further Resources

* [Official Collabora CODE website](https://www.collaboraonline.com/code/)
