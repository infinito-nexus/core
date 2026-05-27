#!/usr/bin/env python3
#
# Local action plugin that extends ansible's get_url action plugin with
# centralized retry defaults while preserving full get_url compatibility.

from __future__ import annotations

import time

from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    # Default policy when no task keywords are provided.
    DEFAULT_RETRIES = 12
    DEFAULT_DELAY = 5

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}

        # Respect explicit Ansible until/retry logic to avoid nested loops.
        if self._task_keyword_is_set("until"):
            return self._execute_get_url(tmp=tmp, task_vars=task_vars)

        if self._task.async_val:
            return self._execute_get_url(tmp=tmp, task_vars=task_vars)

        retries = self._task_keyword_int("retries", self.DEFAULT_RETRIES)
        delay = self._task_keyword_int("delay", self.DEFAULT_DELAY)

        attempts_total = max(1, retries + 1)
        last_result = None
        for attempt in range(1, attempts_total + 1):
            last_result = self._execute_get_url(tmp=tmp, task_vars=task_vars)
            if not last_result.get("failed", False):
                last_result["attempts"] = attempt
                return last_result

            if attempt < attempts_total:
                time.sleep(delay)

        last_result["attempts"] = attempts_total
        return last_result

    def _execute_get_url(self, tmp, task_vars):
        return self._execute_module(
            module_name="ansible.builtin.get_url",
            module_args=dict(self._task.args),
            task_vars=task_vars,
            tmp=tmp,
        )

    def _task_keyword_is_set(self, key):
        ds = self._task.get_ds()
        return isinstance(ds, dict) and key in ds

    def _task_keyword_int(self, key, fallback):
        # `retries` can be present on the parsed task object even if it is not
        # visible in get_ds(); prefer the task attribute for reliable override.
        if key == "retries":
            retries_value = getattr(self._task, "retries", None)
            if retries_value is None:
                return fallback
            return self._as_int(retries_value, fallback)

        if not self._task_keyword_is_set(key):
            return fallback

        return self._as_int(getattr(self._task, key, None), fallback)

    @staticmethod
    def _as_int(value, fallback):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
