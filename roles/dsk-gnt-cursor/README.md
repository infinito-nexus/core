# Cursor

## Description

[Cursor](https://cursor.com/) is an AI-first code editor. This role installs it on a workstation.

## Overview

Cursor's CLI cannot be pointed at a custom OpenAI-compatible endpoint: it exchanges the key for Cursor session tokens and talks its own protocol afterwards. The editor does carry an "Override OpenAI Base URL" field, but it lives in Cursor's own state database rather than in a file this role could render.

The role therefore installs the editor and leaves the endpoint override to the operator. Nothing here pretends to configure a gateway that the product does not accept from a file.

## Features

- **Installed, not faked:** the editor is provisioned; the endpoint override stays a documented operator step.
- **Pinned on every distribution:** Arch installs the AUR build; Debian and RedHat install the vendor's pinned `.deb` or `.rpm` by checksum.
- **No vendor repository left behind:** both packages register the vendor's APT or DNF repository on install; the role removes it again, so system updates never depend on it and never move Cursor past the pin.
