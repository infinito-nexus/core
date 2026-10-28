from __future__ import annotations

import re


def _strip_comments(content):
    out = []
    in_string = in_block = False
    index = 0
    while index < len(content):
        char = content[index]
        if in_block:
            if content.startswith("*/", index):
                in_block = False
                index += 1
            elif char == "\n":
                out.append(char)
        elif in_string:
            out.append(char)
            if char == "\\" and index + 1 < len(content):
                out.append(content[index + 1])
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif content.startswith("/*", index):
            in_block = True
            index += 1
        elif char == "#" or content.startswith("//", index):
            while index + 1 < len(content) and content[index + 1] != "\n":
                index += 1
        else:
            out.append(char)
        index += 1
    return "".join(out)


def _without_blanks(line):
    out = []
    in_string = False
    for index, char in enumerate(line):
        if char == '"' and (index == 0 or line[index - 1] != "\\"):
            in_string = not in_string
        if in_string or not char.isspace():
            out.append(char)
    return "".join(out).rstrip(";")


def _key(setting):
    for index, char in enumerate(setting):
        if char in "=:":
            return setting[:index]
        if char == '"':
            return ""
    return ""


def janus_settings(content, overrides):
    """Return the settings a Janus ``.jcfg`` file declares, one per line.

    Args:
        content: text of a Janus libconfig file.
        overrides: setting names to leave out, the ones a deployment sets on
            top of the stock file; empty to keep every setting.

    Returns:
        Every line that holds more than comments and blanks, with the comments,
        a trailing ``;`` and the whitespace outside quoted strings removed, in
        file order.
    """
    dropped = {str(name) for name in overrides}
    settings = []
    for raw in _strip_comments(str(content)).splitlines():
        setting = _without_blanks(raw)
        if setting and _key(setting) not in dropped:
            settings.append(setting)
    return settings


def janus_config_drift(template, stock, overrides, launcher, target):
    """Return why a rendered Janus config may not replace an image's own.

    Args:
        template: the rendered config that is mounted over ``target``.
        stock: the image's own file at ``target``.
        overrides: setting names the template adds to the stock settings.
        launcher: the image's process manager config that starts Janus.
        target: the path the template is mounted at.

    Returns:
        One message per problem; empty when Janus reads ``target`` and the
        template without ``overrides`` declares exactly the stock settings.
    """
    problems = []
    started_with = re.compile(rf"--config={re.escape(str(target))}( |$)", re.MULTILINE)
    if not started_with.search(str(launcher)):
        problems.append(f"Janus is not started with --config={target}")
    expected = janus_settings(stock, [])
    rendered = janus_settings(template, overrides)
    if expected != rendered:
        first = next(
            (
                f"{index}: image {theirs!r}, template {ours!r}"
                for index, (theirs, ours) in enumerate(
                    zip(expected, rendered, strict=False)
                )
                if theirs != ours
            ),
            f"{len(expected)} settings in the image, {len(rendered)} in the template",
        )
        problems.append(f"the stock settings differ at setting {first}")
    return problems


class FilterModule:
    def filters(self):
        return {
            "janus_config_drift": janus_config_drift,
        }
