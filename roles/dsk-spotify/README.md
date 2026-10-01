# Spotify

## Description

This Ansible role installs the [Spotify](https://www.spotify.com/) desktop client on Arch Linux systems using the [AUR (Arch User Repository)](https://aur.archlinux.org/packages/spotify/).

## Overview

Spotify is a digital music streaming service that gives you access to millions of songs and podcasts. The role calls `package_install` with the `spotify` id; [`meta/packages.yml`](meta/packages.yml) declares it as an AUR package on Arch Linux and as a deliberate no-op on the Debian and RedHat families, which do not archive the proprietary client.

## Purpose

To automate the installation of Spotify on Arch-based systems.

## Features

- 🎧 Installs the official [Spotify AUR package](https://aur.archlinux.org/packages/spotify)
- 🛠 Resolves the package through the registry id `spotify` in [`meta/packages.yml`](meta/packages.yml)

## Requirements

- An Arch Linux based system; `package_install` sets up the unprivileged AUR build environment itself.
