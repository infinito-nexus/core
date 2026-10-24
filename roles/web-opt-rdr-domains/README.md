# Redirector

## Description

This Ansible role configures NGINX to perform 301 redirects from one domain to another. It handles SSL certificate retrieval for the source domains and sets up the NGINX configuration to redirect to the specified target domains.

## Overview

This role configures Nginx to perform 301 redirects based on a list of source→target domain mappings. Each source is served on every network sibling, and each sibling redirects to the target's sibling in the same network.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
- **Well-known passthrough:** every source domain serves the files of its own subdirectory `<domain>/` of the shared well-known directory (`lookup('nginx', 'directories.data.well_known')`) under `/.well-known/`; any other request, a missing well-known file included, gets the 301.
