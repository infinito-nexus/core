# Virtual Box

## Description

```bash
 sudo pacman -S virtualbox "$(pacman -Qsq "^linux" | grep "^linux[0-9]*[-rt]*$" | awk '{print $1"-virtualbox-host-modules"}' ORS=' ')" &&
 sudo vboxreload &&
 pamac build virtualbox-ext-oracle &&
 sudo gpasswd -a "$USER" vboxusers || exit 1
 echo "Keep in mind to install the guest additions in the virtualized system. See https://wiki.manjaro.org/index.php?title=VirtualBox" # nocheck: url; wiki.manjaro.org returns 404 transiently, the page is reachable interactively
```

## Overview

This role installs and configures VirtualBox and its kernel modules on Pacman-based systems, including extension packs and user group setup.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
