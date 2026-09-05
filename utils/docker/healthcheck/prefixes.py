"""Prefixes: shell that runs before a probe without judging the container.

A prefix does something on the way past -- sending a smoke mail is the only
one so far -- and deliberately cannot decide liveness. That separation is what
lets a probe stay the single verdict.
"""

from __future__ import annotations

from typing import Any

MAIL_MARKER = "/tmp/email_sent"  # noqa: S108  container-internal path, not a host tmpfile


def mail_branch(context: dict[str, Any]) -> str:
    """The one-shot smoke mail the msmtp prefix puts in front of a probe.

    Args:
        context: the probe context; needs ``email_enabled`` to do anything, plus
            ``domain`` and ``blackhole`` for the message.

    Returns:
        The shell prefix, or an empty string when email is disabled.

    Two joins carry the whole design and neither is accidental. The branch ends
    in ``; `` so a relay that refuses the message cannot decide liveness -- that
    verdict belongs to the probe this prefixes, and coupling them once left live
    web apps marked dead until the swarm converge gate gave up (ebdadd91b). The
    ``&&`` before ``touch`` stays, so a refused mail leaves no marker and the
    next probe retries instead of the smoke test becoming one-shot.
    """
    if not context.get("email_enabled"):
        return ""
    domain = context.get("domain", "")
    blackhole = context.get("blackhole", "")
    # Exception: --domain is the EHLO identity. msmtp defaults it to "localhost",
    # which a strict relay refuses (Stalwart: 550 Invalid EHLO domain), and images
    # that generate their own /etc/msmtprc leave no other place to set it.
    ehlo = f"--domain={domain} " if domain else ""
    return (
        f"if [ ! -f {MAIL_MARKER} ]; then "
        f"echo 'Subject: testmessage from {domain}\\n\\nSUCCESSFULL' "
        f"| msmtp {ehlo}-t {blackhole} && touch {MAIL_MARKER}; fi; "
    )


class MsmtpPrefix:
    """Sends one test mail before the liveness probe it is composed with.

    Not a probe: it never judges the container. Its timings are floors the
    composition may raise the probe's to, because the first run has a relay
    handshake in front of it.
    """

    name = "msmtp"
    timeout = "20s"
    retries = 5
    start_period = "120s"

    @staticmethod
    def render(context: dict[str, Any]) -> str:
        return mail_branch(context)


PREFIXES: dict[str, type[MsmtpPrefix]] = {MsmtpPrefix.name: MsmtpPrefix}
