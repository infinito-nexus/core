# Cursor

## Description

[Cursor](https://cursor.com/) is an AI-first code editor. This role installs it on a workstation.

## Overview

Cursor's CLI cannot be pointed at a custom OpenAI-compatible endpoint: it exchanges the key for Cursor session tokens and talks its own protocol afterwards. The editor does carry an "Override OpenAI Base URL" field, but it lives in Cursor's own state database rather than in a file this role could render.

The role therefore installs the editor and leaves the endpoint override to the operator. Nothing here pretends to configure a gateway that the product does not accept from a file.

## Features

- **Installed, not faked:** the editor is provisioned; the endpoint override stays a documented operator step.
- **Arch today:** the vendor ships neither a Debian nor an RPM repository, so only the Arch build is wired up.
