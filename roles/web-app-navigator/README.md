# Presentation

## Description

This **Infinito.Nexus Presentation** is a tool designed for showcasing the Infinito.Nexus platform to various audiences, including **Administrators**, **Developers**, **End-Users**, **Businesses**, and **Investors**. The presentation leverages **Reveal.js** to create an interactive, engaging, and fully containerized experience that can be easily deployed with Docker.

This role automates the process of setting up and running the Infinito.Nexus presentation in a Docker container, ensuring a reproducible and isolated environment for displaying the content.

## Overview

The **Infinito.Nexus Presentation** role automates the setup of an environment using Docker, providing a seamless process for pulling your source repository, building the presentation, and serving the slides through a lightweight HTTP server. It uses **[Reveal.js](https://revealjs.com/)** for building and serving the presentation slides and can be deployed with **Kevin's Package Manager**.

## Features

- **Fully Automated Setup:** The role handles all tasks, including pulling the source repository, building the Docker image, and serving the presentation through a web server.
- **Dockerized Environment:** The entire process is contained within Docker, ensuring consistent builds and easy deployment.
- **Interactive Slides:** The presentation is built with **Reveal.js**, allowing for interactive slides with advanced features like fragments, transitions, and more.
- **Customizable:** Easily configurable to point to your own source code or documentation.

## Further Resources

- [Infinito.Nexus Presentation](https://s.infinito.nexus/code-presentation)
- [Reveal.js](https://revealjs.com/)
- [infinito.nexus](https://infinito.nexus)

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) pins `sso.enabled` and `logout.enabled` to `false`; the navigator is a read-only front-end over the role graph with no accounts and no auth layer. There is nothing for the `biber` or `administrator` persona to log in to, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline reachability assertions run unconditionally.
