"""Synthetic Ansible output in the format the repository's runs write: ANSI
colour, ``callback_result_format = yaml`` result bodies, the ``[ERROR]: Task
failed:`` cause line before the fatal, ``TASK`` banners, retries, an ignored
failure and a traceback a passed task printed. Every value is made up."""

from __future__ import annotations

_RED = "\x1b[0;31m"
_GREEN = "\x1b[0;32m"
_YELLOW = "\x1b[0;33m"
_CYAN = "\x1b[0;36m"
_RESET = "\x1b[0m"
EARLIER = "sys-svc-docker : Wait for the daemon"
CHANGED = "web-app-gitea : Render app.ini"
MARKER = "TASK [web-app-gitea :"


def _paint(colour: str, text: str) -> str:
    return "".join(f"{colour}{line}{_RESET}\n" for line in text.splitlines())


def banner(task: str, stars: int) -> str:
    """Return a ``TASK`` banner padded with ``stars`` stars, as the terminal
    width pads it.

    Args:
        task: the ``<role> : <name>`` task title.
        stars: the number of padding stars.
    """
    return f"\nTASK [{task}] {'*' * stars}\n"


def passed(task: str, noise: int) -> str:
    """Return a passed task whose stdout carries ``noise`` failure-looking
    lines and a traceback the task tolerated.

    Args:
        task: the task title.
        noise: the number of failure-looking lines in its stdout.
    """
    body = "changed: [localhost] =>\n    stdout: |-\n"
    body += "".join(
        f"        level {index}: DEBUG, INFO, WARNING, ERROR, and CRITICAL\n"
        for index in range(noise)
    )
    body += (
        "        Traceback (most recent call last):\n"
        '          File "probe.py", line 3, in <module>\n'
        "        ValueError: tolerated by the probe\n"
    )
    return banner(task, 60) + _paint(_YELLOW, body)


def retries(task: str, count: int) -> str:
    """Return ``count`` ``FAILED - RETRYING`` lines, each with its YAML body.

    Args:
        task: the task title the retry names.
        count: the number of retries.
    """
    return "".join(
        _paint(
            _RED,
            f"FAILED - RETRYING: [localhost]: {task} ({60 - index} retries left).\n"
            f"    attempts: {index + 1}\n    changed: false\n    msg: not ready",
        )
        for index in range(count)
    )


def failure(cause: str, run: int) -> str:
    """Return the end of a failed task: the ``[ERROR]`` cause with its origin,
    the fatal line and its YAML body with the volatile parts of run ``run``.

    Args:
        cause: the module's failure message.
        run: the run number, which varies the clock, delta and temp path.
    """
    body = (
        f"[ERROR]: Task failed: Module failed: {cause}\n"
        "Origin: /opt/src/infinito/roles/web-app-gitea/tasks/main.yml:12:3\n"
        "\n"
        '12 - name: "Render app.ini"\n'
        "     ^ column 3\n"
        "\n"
        "fatal: [localhost]: FAILED! => \n"
        "    changed: false\n"
        f"    delta: '0:00:0{run}.{run}23456'\n"
        f"    invocation: /root/.ansible/tmp/ansible-tmp-17308{run}2345.67-1234-9876/x.py\n"
        f"    msg: {cause}\n"
        f"    start: '2026-11-0{run} 00:41:12.{run}23456'"
    )
    return _paint(_RED, body)


def ignored(task: str, cause: str) -> str:
    """Return a failed task the play ignored.

    Args:
        task: the task title.
        cause: the module's failure message.
    """
    return banner(task, 45) + failure(cause, 1) + _paint(_CYAN, "...ignoring")


def rescued(task: str, cause: str) -> str:
    """Return a failed task its block rescued: the fatal, then the rescue task.

    Args:
        task: the title of the task that failed.
        cause: its failure message.
    """
    return (
        banner(task, 35)
        + failure(cause, 1)
        + banner("svc-db-postgres : Rescue: restore the dump", 35)
        + _paint(_GREEN, "ok: [localhost]")
    )


def recap() -> str:
    """Return the ``PLAY RECAP`` of a play a failed task ended."""
    return (
        "\nPLAY RECAP *********************************************************\n"
        "localhost : ok=12 changed=3 unreachable=0 failed=1 ignored=1\n"
    )


def rescued_recap() -> str:
    """Return the ``PLAY RECAP`` of a play whose only failure was rescued."""
    return (
        "\nPLAY RECAP *********************************************************\n"
        "localhost : ok=12 changed=3 unreachable=0 failed=0 rescued=1 ignored=0\n"
    )


def act(log: str) -> str:
    """Return ``log`` as act prints it, every line behind its job prefix.

    Args:
        log: the run's log.
    """
    return "".join(
        f"[call-test/deploy (debian)]   | {line}\n" for line in log.splitlines()
    )


def deploy_playwright(title: str) -> str:
    """Return a deploy whose Playwright task failed on the case ``title``: the
    report printed inside an escaped YAML ``msg`` folded over several lines,
    with a passed case, a failing first attempt and its retry, then the gate
    task's fatal.

    Args:
        title: the title of the failing case.
    """
    folded = (
        '    msg: "rc: 1\\n\\nstdout:\\n\\nRunning 3 tests using 1 worker\\n\\n'
        "  \\u2713  1 [chromium] \\\n"
        "        \\ › playwright.spec.js:10:9 › setup (2.5s)\\n"
        "  ✘  2 [chromium] › playwright.spec.js:50:9\\\n"
        f"        \\ › {title} (10.4s)\\n"
        f"  ✘  3 [chromium] › playwright.spec.js:50:9 › {title} (retry\\\n"
        '        \\ #1) (10.8s)\\n"'
    )
    return (
        passed(EARLIER, 2)
        + banner("test-e2e-playwright : Print Playwright output (on failure)", 30)
        + _paint(_GREEN, "ok: [localhost] =>\n" + folded)
        + banner("test-e2e-playwright : Fail if there were Playwright failures", 30)
        + _paint(
            _RED,
            "[ERROR]: Task failed: Action failed: Playwright failed for roles: "
            "['web-app-gitea']\nfatal: [localhost]: FAILED! => \n"
            "    msg: Playwright failed for roles: ['web-app-gitea']",
        )
        + recap()
        + exit_line()
    )


def always_run(cause: str) -> str:
    """Return a deploy whose task failed with ``cause`` and whose ``always:``
    task ran after the fatal, so a banner follows it.

    Args:
        cause: the failure message.
    """
    return (
        passed(EARLIER, 2)
        + banner(CHANGED, 30)
        + failure(cause, 1)
        + banner("web-app-gitea : Always: remove the staging directory", 30)
        + _paint(_GREEN, "ok: [localhost]")
        + recap()
        + exit_line()
    )


def green_run() -> str:
    """Return a deploy that ended green with the deploy's closing line."""
    return (
        passed(EARLIER, 1)
        + banner(CHANGED, 30)
        + _paint(_GREEN, "ok: [localhost]")
        + rescued_recap()
        + "\n✅ Script ended at: 2026-11-06T10:00:00+00:00\n"
    )


def exit_line() -> str:
    """Return the deploy wrapper's exit line of a failed playbook run."""
    return f"{_RED}[ERROR] ansible-playbook exited with status 2{_RESET}\n"


def red_run(task: str, cause: str, run: int, noise: int) -> str:
    """Return a whole red deploy: passed tasks with ``noise`` noise lines, an
    ignored failure, ``run`` retries, the failure of ``task`` and the recap.

    Args:
        task: the title of the task the run fails in.
        cause: its failure message.
        run: the run number, which varies the retries and volatile parts.
        noise: the number of noise lines the passed task printed.
    """
    return (
        passed(EARLIER, noise)
        + ignored("svc-db-postgres : Probe the old socket", "socket missing")
        + banner(task, 40 + run)
        + retries(task, run)
        + failure(cause, run)
        + recap()
        + exit_line()
    )


def hung_run(task: str, tail: str, noise: int) -> str:
    """Return a deploy cut off while ``task`` ran: passed tasks with ``noise``
    noise lines, then the banner of ``task`` and the line ``tail``.

    Args:
        task: the title of the task the run hangs in.
        tail: the last line the run wrote.
        noise: the number of noise lines the passed task printed.
    """
    return passed(EARLIER, noise) + banner(task, 50) + _paint(_GREEN, tail)
