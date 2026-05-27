# Moodle

## Description

Ignite the learning experience with [Moodle](https://moodle.org/), a powerful and versatile platform for online education that energizes classrooms and fosters interactive learning. Moodle delivers a comprehensive set of tools for creating, managing, and sharing educational content, supporting collaboration among educators and learners alike.

## Overview

This role deploys Moodle using Docker, automating the setup of both the Moodle application and its underlying MariaDB database. It integrates with an NGINX reverse proxy to ensure secure and efficient web access and uses persistent storage to safeguard your data and configuration.

## Features

- **Comprehensive e-Learning Platform:** Offers an extensive array of features including course management, assessment tools, and collaborative resources.
- **Customizable Interface:** Tailor the look and feel of your learning environment with numerous themes and plugins.
- **Scalable Deployment:** Leverage Docker for a portable and scalable installation that adapts as your user base grows.
- **Robust Data Management:** Secure and reliable storage of both the Moodle application and user data through Docker volumes.
- **Secure Web Access:** Configured to work seamlessly behind an NGINX reverse proxy for enhanced security and performance.
- **Single Sign-On (SSO) / OpenID Connect (OIDC):** Seamless integration with external identity providers for centralized authentication.

## Image source

This role builds its own Moodle image from upstream Moodle source on top of the official `php:8.3-fpm` base.

## Further Resources

- [Moodle Official Website](https://moodle.org/)
- [Moodle Developer Documentation: Docker images](https://moodledev.io/general/app/development/setup/docker-images)
- [moodlehq/moodle-docker](https://github.com/moodlehq/moodle-docker) (extension list reference)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
