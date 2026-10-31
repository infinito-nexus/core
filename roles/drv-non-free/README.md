# Proprietary Drivers

## Description

This Ansible role installs non-free GPU drivers on Arch Linux systems by invoking the `mhwd` utility. It ensures that the appropriate proprietary drivers for your PCI graphics hardware are installed and ready for use.

## Overview

- Uses the `ansible.builtin.shell` module to run `mhwd -a pci nonfree 0300`  
- Automatically detects your PCI graphics adapter and installs the recommended non-free driver  
- Designed to be run once per host to provision proprietary GPU support

## Features

- **Automatic Hardware Detection**  
  Leverages `mhwd`’s built-in auto-detect feature (`0300`) to select the correct driver.

- **Proprietary Driver Installation**  
  Installs the latest non-free GPU driver (e.g., NVIDIA, AMD) provided through Arch’s `mhwd` system.

- **Simple Execution**  
  Single-task role with minimal overhead.

## Further Resources

- [Arch Linux mhwd Package](https://archlinux.org/packages/?q=manjaro)
