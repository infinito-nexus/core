import json
import re

from utils.cache.yaml import load_yaml_str

COMPOSE_LABEL = "com.docker.compose.project"
STACK_LABEL = "com.docker.stack.namespace"
EXEC_DIE = "exec_die"
SHELL_PREFIX = "/bin/sh -c "


def wazuh_healthcheck_actions(compose_text):
    """Return the exec commands Docker reports for the health checks of a compose file.

    Args:
        compose_text: the rendered ``compose.yml`` of an app.

    Returns:
        Sorted unique commands as they appear after ``exec_create: `` and
        ``exec_start: `` in a Docker event: ``CMD`` arguments joined by spaces,
        ``CMD-SHELL`` and a plain string run through ``/bin/sh -c``, ``$$``
        reduced to the ``$`` Docker receives. Disabled checks are left out.
    """
    services = (load_yaml_str(compose_text) or {}).get("services") or {}
    actions = set()
    for service in services.values():
        healthcheck = (service or {}).get("healthcheck") or {}
        test = healthcheck.get("test")
        if healthcheck.get("disable") or not test:
            continue
        if isinstance(test, str):
            command = SHELL_PREFIX + test
        elif test[0] == "CMD":
            command = " ".join(test[1:])
        elif test[0] == "CMD-SHELL":
            command = SHELL_PREFIX + " ".join(test[1:])
        else:
            continue
        actions.add(command.replace("$$", "$"))
    return sorted(actions)


def _xml_text(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wazuh_healthcheck_pattern(actions):
    """Return the PCRE2 pattern for an app's health-check exec events, escaped for XML text.

    Args:
        actions: the app's health-check commands from ``wazuh_healthcheck_actions``.

    Returns:
        A pattern that matches ``exec_die`` and ``exec_create`` or
        ``exec_start`` with exactly one of the commands, nothing else.
    """
    if not actions:
        return f"^{EXEC_DIE}$"
    commands = "|".join(re.escape(action) for action in actions)
    return _xml_text(f"^(?:{EXEC_DIE}|exec_(?:create|start): (?:{commands}))$")


def _event(action, label, project, name):
    return json.dumps(
        {
            "integration": "docker",
            "docker": {
                "Type": "container",
                "Action": action,
                "Actor": {
                    "ID": "0" * 64,
                    "Attributes": {label: project, "image": "probe:1", "name": name},
                },
                "scope": "local",
                "time": 1792739236,
                "timeNano": 1792739236000000000,
            },
        }
    )


def wazuh_docker_samples(entities, healthchecks, level, oom_level, foreign_rule, foreign_level):
    """Return the Docker attribution samples of every opted-in app.

    Args:
        entities: ``WAZUH_RULESET_ENTITIES``, each with ``entity``, ``role`` and ``docker`` rule IDs.
        healthchecks: ``{entity: [command]}`` from ``wazuh_healthcheck_actions``.
        level: the level of the compose and swarm attribution rules.
        oom_level: the level of the OOM rule.
        foreign_rule: the default Docker rule a start event of another project hits.
        foreign_level: that rule's level.

    Returns:
        ``[{role, line, rule, level}]``: start, die, a real exec and exec_die
        for the compose label, an OOM kill for each label, a start for the swarm label, the first
        health-check command (when the app has one), the same command with a
        suffix, and a start of a foreign project that must not be attributed.
    """
    samples = []
    for app in entities:
        entity, ids, role = app["entity"], app["docker"], app["role"]

        def add(action, rule, sample_level, label=COMPOSE_LABEL, project=entity):
            samples.append(
                {
                    "role": role,
                    "line": _event(action, label, project, entity),
                    "rule": rule,
                    "level": sample_level,
                }
            )

        for action in ("start", "die", "exec_start: sh"):
            add(action, ids["compose"], level)
        add("oom", ids["oom"], oom_level)
        add("oom", ids["oom"], oom_level, label=STACK_LABEL)
        add(EXEC_DIE, ids["healthcheck"], 0)
        add("start", ids["swarm"], level, label=STACK_LABEL)
        commands = healthchecks.get(entity, [])
        if commands:
            add(f"exec_start: {commands[0]}", ids["healthcheck"], 0)
            add(f"exec_start: {commands[0]}; id", ids["compose"], level)
        add("start", foreign_rule, foreign_level, project=f"not-{entity}")
    return samples


class FilterModule:
    def filters(self):
        return {
            "wazuh_healthcheck_actions": wazuh_healthcheck_actions,
            "wazuh_healthcheck_pattern": wazuh_healthcheck_pattern,
            "wazuh_docker_samples": wazuh_docker_samples,
        }
