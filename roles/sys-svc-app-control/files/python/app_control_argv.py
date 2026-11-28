from __future__ import annotations


def compose_argv(config, registry, *command):
    """Return the compose wrapper call of an application.

    Args:
        config: the parsed configuration.
        registry: the record its deploy wrote.
        command: the compose subcommand and its arguments.
    """
    return [
        config["compose"],
        "--chdir",
        registry["instance"],
        "--project",
        registry["project"],
        *command,
    ]


def stack_services_argv(registry):
    """Return the call that lists the services of an application's stack.

    Args:
        registry: the record its deploy wrote.
    """
    return ["docker", "stack", "services", "--format", "{{.Name}}", registry["project"]]


def scale_to_zero_argv(services):
    """Return the call that scales every given swarm service to 0 replicas.

    Args:
        services: the service names.
    """
    return [
        "docker",
        "service",
        "scale",
        "--detach=false",
        *(f"{name}=0" for name in services),
    ]


def stack_deploy_argv(registry):
    """Return the call that redeploys an application's rendered stack.

    Args:
        registry: the record its deploy wrote.
    """
    files = [
        arg for path in registry["stack_files"] for arg in ("--compose-file", path)
    ]
    return [
        "docker",
        "stack",
        "deploy",
        *files,
        "--resolve-image",
        "never",
        "--prune",
        "--with-registry-auth",
        registry["project"],
    ]
