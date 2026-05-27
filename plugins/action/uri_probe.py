#!/usr/bin/env python3
#
# Local action plugin for lightweight URL reachability probes. It reuses the
# centralized retry behavior from uri_retry.py, but with shorter defaults that
# better fit bootstrap and recovery checks.

from __future__ import annotations

from plugins.action.uri_retry import ActionModule as UriRetryActionModule


class ActionModule(UriRetryActionModule):
    DEFAULT_RETRIES = 2
    DEFAULT_DELAY = 2
    DEFAULT_METHOD = "HEAD"
    DEFAULT_TIMEOUT = 5

    def run(self, tmp=None, task_vars=None):
        if self._task.args is None:
            self._task.args = {}

        self._task.args.setdefault("method", self.DEFAULT_METHOD)
        self._task.args.setdefault("timeout", self.DEFAULT_TIMEOUT)

        return super().run(tmp=tmp, task_vars=task_vars)
