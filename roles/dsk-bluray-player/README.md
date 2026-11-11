# Blue-ray Disc

## Description

This Ansible role installs and configures all the software required for Blu-ray playback on Arch Linux–based systems. It ensures that VLC and the necessary libraries for Blu-ray disc decryption and playback (`libaacs`, `libbluray`) are present, and provides hooks for optional AUR packages.

## Overview

- Uses the `community.general.pacman` module to install:
  - `vlc` (media player with Blu-ray support)  
  - `libaacs` (AACS decryption library)  
  - `libbluray` (Blu-ray playback support library)  
- Contains commented-out tasks for optional AUR packages (`aacskeys`, `libbdplus`) you can enable as needed.
- Designed for idempotent execution on Arch Linux and derivatives.

## Features

- **VLC Installation**  
  Installs `vlc` for general media and Blu-ray playback.

- **AACS & BD+ Support**  
  Installs `libaacs` and `libbluray` to handle Blu-ray disc encryption and playback.

- **Optional AUR Packages**  
  Drop-in tasks for `aacskeys` and `libbdplus` via AUR (commented out by default).

- **Idempotent Role**  
  Safe to run multiple times without unintended side effects.

- **Arch Linux–Optimized**  
  Leverages Pacman for fast and reliable package management.

## Further Resources

- [Arch Linux Wiki: Blu-ray Playback](https://wiki.archlinux.org/title/Blu-ray#Using_aacskeys)  
- [Play Blu-ray with VLC Guide](https://videobyte.de/play-blu-ray-with-vlc)  
- [FV Online DB – Blu-ray Tools](http://fvonline-db.bplaced.net/)  
