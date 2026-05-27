from __future__ import annotations

import pwd
from typing import Any

from ansible.plugins.lookup import LookupBase

from plugins.lookup.email import LookupModule as EmailLookup
from plugins.lookup.email import _as_bool
from plugins.lookup.users import LookupModule as UsersLookup


def _instantiate(cls: type, templar: Any) -> Any:
    inst = cls()
    inst._templar = templar
    return inst


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        email_cfg = _instantiate(EmailLookup, self._templar).run(
            [], variables=variables
        )[0]
        if _as_bool(email_cfg.get("external")):
            admin = _instantiate(UsersLookup, self._templar).run(
                ["administrator"], variables=variables
            )[0]
            return [str(admin.get("email", "root"))]
        try:
            pwd.getpwnam("administrator")
        except KeyError:
            return ["root"]
        return ["administrator"]
