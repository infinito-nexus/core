# Swapfile

## Description

This role automates the creation of a swapfile on the target system by cloning a swapfile creation script from a Git repository and executing it with the specified swapfile size.

## Overview

The role performs the following tasks:

- Clones the swapfile creation script from the Git repository.
- Executes the script with the provided swapfile size to create a swapfile.
- Helps ensure that the system has adequate swap space for improved performance and stability.

## Purpose

The primary purpose of this role is to automate the process of swapfile creation, ensuring that the system has sufficient swap space to handle memory-intensive tasks and maintain overall performance.

## Features

- **Script Cloning:** Retrieves the latest swapfile creation script from a Git repository.
- **Swapfile Creation:** Executes the script to create a swapfile of a specified size.
- **Performance Enhancement:** Ensures adequate swap space for optimal system performance.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
