# OpenResty

This role deploys an OpenResty container via Docker Compose, validates its configuration, and restarts it on changes.

## Description

- Runs an OpenResty container in host network mode  
- Mounts NGINX configuration and Let’s Encrypt directories  
- Validates the OpenResty (NGINX) configuration before any restart  
- Restarts the container only if the configuration is valid  

## Overview

1. Loads the base Docker Compose setup  
2. Adds the OpenResty service  
3. Defines handlers to validate and restart the container  
4. Triggers a restart on configuration changes  

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Further Reading

- [OpenResty Docker Hub](https://hub.docker.com/r/openresty/openresty)  
- [OpenResty Official Documentation](https://openresty.org/)  
- [Ansible Docker Compose Role on Galaxy](https://galaxy.ansible.com/)  
