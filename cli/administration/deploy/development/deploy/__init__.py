"""SPOT for the ``deploy`` subcommand of the development stack helper.

Internal layout (one module per responsibility):

* :mod:`.run`   — :func:`_run_deploy`, one deploy pass inside the container
* :mod:`.drill` — :func:`_maybe_recover_drill`, backup/recover verification
* :mod:`.purge` — :func:`_purge_app_entities`, inter-round entity cleanup
* :mod:`.cli`   — :func:`add_parser` + :func:`handler`, arg parsing and the
  round/pass orchestration loop

Tests patch collaborators on the submodule that uses them
(e.g. ``deploy.cli._run_deploy``), not on this package.
"""

from __future__ import annotations

from .cli import add_parser, handler

__all__ = ["add_parser", "handler"]
