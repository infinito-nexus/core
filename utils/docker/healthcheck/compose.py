"""Turns a service's ``healthcheck`` declaration into a rendered compose block.

A declaration names exactly one probe and any number of prefixes, either as one
string or as a list. This module owns that grammar: the aliases, the validation
and the timing arithmetic that decides what a composed probe inherits.
"""

from __future__ import annotations

from typing import Any

from utils.cache.yaml import dump_yaml_str
from utils.docker.healthcheck.prefixes import PREFIXES, MsmtpPrefix
from utils.docker.healthcheck.probes import PROBES, Custom, Probe

ALIASES: dict[str, list[str]] = {"msmtp_curl": ["msmtp", "curl"]}

_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0}


def known_flavors() -> str:
    return ", ".join(sorted({*PROBES, *PREFIXES, *ALIASES}))


def resolve_flavors(flavors: str | list[str]) -> list[str]:
    """Expand what a service declared into a flat list of names.

    Args:
        flavors: one name, or the list form ``[msmtp, connect]``.

    Returns:
        The names in declaration order, aliases substituted.
    """
    names = [flavors] if isinstance(flavors, str) else list(flavors)
    expanded: list[str] = []
    for name in names:
        expanded.extend(ALIASES.get(name, [name]))
    return [name for name in expanded if name]


def timing_rank(value: Any) -> float:
    """Order timings so the longest wins, whatever unit it is spelled in.

    Args:
        value: a docker duration such as ``20s`` or ``15m``, or a bare count.
    """
    text = str(value)
    if text.isdigit():
        return float(text)
    return float(text[:-1]) * _UNITS.get(text[-1:], 1.0) if text[:-1].isdigit() else 0.0


def _split(names: list[str]) -> tuple[str, list[type[MsmtpPrefix]]]:
    """Sort declared names into the one probe and its prefixes.

    Raises:
        KeyError: a name is neither a probe nor a prefix.
        ValueError: the declaration carries no probe, or more than one.
    """
    unknown = [name for name in names if name not in PROBES and name not in PREFIXES]
    if unknown:
        raise KeyError(unknown[0])
    probe_names = [name for name in names if name in PROBES]
    if len(probe_names) != 1:
        raise ValueError(
            f"healthcheck flavors {names} must name exactly one probe, "
            f"got {probe_names or 'none'}"
        )
    return probe_names[0], [PREFIXES[name] for name in names if name in PREFIXES]


def compose(flavors: str | list[str], **context: Any) -> Probe:
    """Build the probe a declaration asks for, prefixes applied.

    Args:
        flavors: one name, or a list of prefixes plus exactly one probe.
        context: port, path, hostname, samples and any extras a part needs.

    Returns:
        The probe; with prefixes it is wrapped so ``test`` renders CMD-SHELL.

    A prefix cannot judge the container, so the probe keeps the verdict and the
    prefix only ever RAISES a timing -- the composed start period is the longest
    of the two, never the prefix's alone. Lowering it once would have cut a
    fifteen minute start window down to two.
    """
    names = resolve_flavors(flavors)
    probe_name, prefixes = _split(names)
    probe = PROBES[probe_name](**context)
    if not prefixes:
        return probe

    rendered = "".join(prefix.render(context) for prefix in prefixes)
    inner = probe.shell()

    class Composed(type(probe)):  # type: ignore[misc, valid-type]
        def test(self) -> list[str]:
            return ["CMD-SHELL", f"{rendered}{inner} || exit 1"]

    for attribute in ("timeout", "retries", "start_period"):
        candidates = [getattr(probe, attribute)] + [
            getattr(prefix, attribute) for prefix in prefixes
        ]
        setattr(Composed, attribute, max(candidates, key=timing_rank))
    return Composed(**context)


def build(flavor: str | list[str], overrides: dict[str, Any], **context: Any) -> str:
    """Render a service's healthcheck block as YAML, starting at column zero.

    Args:
        flavor: a name, a list of prefixes plus one probe, or empty for an
            explicit ``test`` argv.
        overrides: the service's healthcheck entry from services.yml.
        context: port, path, hostname, samples and any flavor specific extras.

    Raises:
        KeyError: a name is unknown.
    """
    probe = compose(flavor, **context) if flavor else Custom(**context)
    return dump_yaml_str({"healthcheck": probe.block(overrides)}, width=10**6).rstrip(
        "\n"
    )
