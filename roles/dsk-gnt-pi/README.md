# Pi Coding Agent

## Description

[Pi](https://github.com/earendil-works/pi) is a minimal terminal coding agent with a lazy-loading skill system. This role installs it on a workstation and registers the platform's model gateway as its provider.

## Overview

Pi reads its providers from `~/.pi/agent/models.json`. The role renders that file with one provider of type `openai-completions` pointing at the gateway's `/v1` base, the workstation's key, and the model aliases the operator listed.

As with every workstation agent here, the key is operator-supplied: the gateway mints it from the server inventory, and the workstation inventory carries it.

## Features

- **Gateway-backed:** one provider entry, no vendor credentials on the machine.
- **Explicit model list:** the aliases come from the inventory, so the agent offers exactly what the gateway serves.
- **No configuration without a key:** the file is written only once URL, key and model list are set.
- **User-owned:** the file belongs to the workstation user and is readable only by them.
