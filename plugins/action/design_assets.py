from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from plugins.action.stack_host_copy import ActionModule as StackHostCopyAction
from utils.design.branding import is_disabled
from utils.design.logo import render_assets

_REQUIRED = ("logo", "title", "domain", "fill", "stroke", "slots", "dest")


class ActionModule(StackHostCopyAction):
    """
    Render the branding assets of one role on the controller and copy them to
    the stack host.

    Args (task):
      logo    absolute logo path
      title   title text, or false
      domain  role domain
      fill    text color
      stroke  text outline color
      slots   {name: {width, height, text_only}}
      dest    destination directory on the stack host
    """

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = dict(self._task.args)
        missing = [key for key in _REQUIRED if key not in args]
        if missing:
            return {
                "failed": True,
                "msg": f"design_assets: missing {', '.join(missing)}",
            }

        workdir = Path(tempfile.mkdtemp(prefix="design-assets-"))
        try:
            title = False if is_disabled(args["title"]) else str(args["title"])
            assets = render_assets(
                args["logo"],
                title,
                args["domain"],
                args["fill"],
                args["stroke"],
                args["slots"],
            )
            for name, content in assets.items():
                (workdir / name).write_bytes(content)
            self._task.args = {
                "src": f"{workdir}/",
                "dest": f"{str(args['dest']).rstrip('/')}/",
            }
            return super().run(tmp=tmp, task_vars=task_vars)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
