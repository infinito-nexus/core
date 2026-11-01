from __future__ import annotations

from ansible.errors import AnsibleFilterError

_FIELDS = {"login": str, "email": str, "admin": bool}


def _validated(accounts) -> list[dict]:
    if not isinstance(accounts, list):
        raise AnsibleFilterError("platform_admin_plan expects the accounts as a list")
    for account in accounts:
        if not isinstance(account, dict) or any(
            not isinstance(account.get(field), kind) for field, kind in _FIELDS.items()
        ):
            raise AnsibleFilterError(
                f"an account needs a string login and email and a boolean admin: {account}"
            )
    return accounts


def platform_admin_plan(
    accounts, login: str, email: str, app: str, case_sensitive_login: bool
) -> str:
    """Decide how the platform administrator reaches an installed app.

    Args:
        accounts: every account of the app as ``{login, email, admin}``.
        login: login the platform administrator has in the app.
        email: email an account created for it gets.
        app: name of the app, for the failure messages.
        case_sensitive_login: whether the app tells logins apart by case.

    Returns:
        ``realign`` when ``login`` is an administrator already, ``create``
        when it is absent and is added next to the existing administrators.

    Raises:
        AnsibleFilterError: ``login`` belongs to a non-administrator, the app
            has no administrator at all, or another account holds ``email``.
    """
    accounts = _validated(accounts)

    def same(other: str) -> bool:
        return (
            other == login
            if case_sensitive_login
            else other.casefold() == login.casefold()
        )

    holder = next((account for account in accounts if same(account["login"])), None)
    if holder is not None:
        if holder["admin"]:
            return "realign"
        raise AnsibleFilterError(
            f"the {app} account '{holder['login']}' is no administrator and is not "
            f"promoted; make it an administrator in {app} or rename it, then redeploy"
        )

    if not any(account["admin"] for account in accounts):
        raise AnsibleFilterError(
            f"{app} has no administrator, so its install is unfinished; finish or "
            f"reset that install instead of adding '{login}' to it"
        )

    email_holders = sorted(
        account["login"]
        for account in accounts
        if account["email"].casefold() == email.casefold()
    )
    if email_holders:
        raise AnsibleFilterError(
            f"the email '{email}' is held by the {app} account "
            f"{', '.join(email_holders)}; change that account's email, then redeploy"
        )

    return "create"


class FilterModule:
    def filters(self):
        return {"platform_admin_plan": platform_admin_plan}
