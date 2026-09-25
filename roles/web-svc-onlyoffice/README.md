# OnlyOffice

## Description

This Ansible role deploys the ONLYOFFICE Document Server in Docker to provide real-time, in-browser editing for documents, spreadsheets, and presentations.
It automates the setup of the Document Server container, NGINX reverse proxy configuration, network isolation via Docker networks, and environment variable management for secure integration with Nextcloud or other WOPI-compatible platforms.

## Overview

* **Dockerized ONLYOFFICE Document Server:** Uses the official `onlyoffice/documentserver` image.
* **NGINX Reverse Proxy:** Configures a public-facing proxy with TLS termination for `/` and internal API calls.
* **Docker Network Management:** Creates an isolated `/28` subnet for ONLYOFFICE and connects containers securely.
* **Environment Configuration:** Generates a `.env` file containing domain, credentials, and JWT configuration for secure document editing.

## Features

* Automatic creation of a dedicated Docker network for ONLYOFFICE.
* Proxy configuration template for NGINX with long timeouts.
* Customizable domain names and ports via Ansible variables.
* Support for SSL/TLS termination at the proxy level.
* Optional JWT signing for secure communication between Nextcloud and Document Server.
* Integration hooks to restart NGINX and recreate Docker Compose stacks on changes.

## Further Resources

* [Official ONLYOFFICE Document Server Documentation](https://helpcenter.onlyoffice.com/docs/)
* [Nextcloud → ONLYOFFICE Integration App](https://apps.nextcloud.com/apps/onlyoffice)
* [ONLYOFFICE Document Server on Docker Hub](https://hub.docker.com/r/onlyoffice/documentserver)
