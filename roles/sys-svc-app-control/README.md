# App control

## Description

App control pauses and resumes the applications an Infinito.Nexus host runs, so an operator can stop a service from [Semaphore](https://semaphoreui.com/) without a shell on the host. A paused application keeps its data and configuration; it only stops running until it is resumed.

## Overview

This role installs the `app-control` command, writes its configuration, renders the paused page, and, on hosts that also deploy `web-app-semaphore`, creates the restricted account the Semaphore runner signs in as. The server stage installs all of this once its roles are deployed and before the E2E run; the last step of every deploy applies the persisted pause state of every application on the host. `sys-svc-compose` registers each compose instance with it, and the vhost hook in `sys-front-inj-all` answers a paused application with HTTP 503 and the paused page.

## Features

- **Persisted state marker:** `<instance>/.app-control-state` holds `started` or `stopped` and is the single source of truth. Without a marker, the application is created in the `status` of its `services.semaphore` entry; a redeploy brings the application up, configures it, and pauses it again when its marker says `stopped`.
- **Pause and resume:** `app-control --config <file> stop|start <application_id>|all` runs `compose down` and `compose up -d` in compose mode, and scales every service of the stack to 0 replicas or redeploys the rendered stack in swarm mode. The application's own `*.infinito.nexus` timer stops and starts with it.
- **Control plane stays up:** `stop` and `start` refuse an application whose `services.semaphore.control` is false, and `all` acts on exactly the applications with `control: true`.
- **Restricted Semaphore account:** the `app-control` user signs in only with the public half of the `app_control_ssh_key` credential of `web-app-semaphore`. A forced command accepts `app-control stop|start <application_id>|all` and nothing else, and sudo lets the account run exactly those two subcommands as root.
- **Paused page:** a self-contained page with a beaver sleeping behind a pause sign, the paused notice, and every contact channel of `service_provider.contact`. One page is rendered per language the `core` catalogs translate; nginx picks it from `Accept-Language` and falls back to English.
- **Guarded restarters:** the soft container repair, the backup hard restart and the RBAC sync timer leave a paused application alone, and the webserver health check accepts its 503.
- **Prompt status:** a successful `stop` or `start` schedules one run of the webserver health sweep unit named by `health_service`, `health_delay_seconds` after the last such action, through the transient timer `app-control-health-refresh`; a later action moves the pending run behind it, so a resumed application answers before it is probed and bursts stay below the unit's start limit. The dashboard's badge follows one poll after that run. A host without the unit, such as a swarm node that runs no sweep, skips it, and a failure to schedule it is reported on stderr and in the exit code.
