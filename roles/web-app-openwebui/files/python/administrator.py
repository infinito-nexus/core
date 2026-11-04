import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")

EMAIL = os.environ["OPENWEBUI_ADMIN_EMAIL"].lower()
NAME = os.environ["OPENWEBUI_ADMIN_NAME"]
PASSWORD = os.environ["OPENWEBUI_ADMIN_PASSWORD"]


async def converge():
    """Create the administrator or bring an existing account back to its password and role.

    Returns:
        ``CHANGED <what>`` when the database was written, ``OK`` otherwise.
    """
    from open_webui.models.auths import Auths
    from open_webui.models.users import Users
    from open_webui.utils.auth import get_password_hash, verify_password

    user = await Users.get_user_by_email(EMAIL)
    if user is None:
        created = await Auths.insert_new_auth(
            email=EMAIL,
            password=await get_password_hash(PASSWORD),
            name=NAME,
            role="admin",
        )
        if created is None:
            sys.exit("FAILED: the administrator could not be created")
        return "CHANGED created"

    async def matches(hashed):
        return await verify_password(PASSWORD, hashed)

    changes = []
    if await Auths.authenticate_user(EMAIL, matches) is None:
        if not await Auths.update_user_password_by_id(
            user.id, await get_password_hash(PASSWORD)
        ):
            sys.exit(f"FAILED: no credential row for {user.id}")
        changes.append("password")
    if user.role != "admin":
        await Users.update_user_role_by_id(user.id, "admin")
        changes.append("role")
    return f"CHANGED {' '.join(changes)}" if changes else "OK"


if __name__ == "__main__":
    print(asyncio.run(converge()))
