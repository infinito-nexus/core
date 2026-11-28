import base64
import hashlib
import hmac
import unicodedata

from ansible.errors import AnsibleFilterError

SALT_BYTES = 16
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def map_animator_password_hash(password, salt_key, username):
    """Hash a password the way the render server's passwd.mjs stores it.

    Node's crypto.scrypt defaults (N=16384, r=8, p=1) over the NFC form of the
    password, both parts base64url without padding. The salt is an HMAC of the
    username, so a rerun renders the same file and an unchanged password never
    restarts the server.

    Args:
        password: the user's plain password.
        salt_key: the role's secret HMAC key (secrets.credentials.users_salt_key).
        username: the account name the line is written for.

    Returns:
        ``scrypt:<salt>:<hash>``, the stored form after ``<name>:`` in users.txt.
    """
    if not password or not salt_key or not username:
        raise AnsibleFilterError(
            "map_animator_password_hash needs a password, a salt key and a username"
        )
    salt = hmac.new(
        str(salt_key).encode(), str(username).encode(), hashlib.sha256
    ).digest()[:SALT_BYTES]
    digest = hashlib.scrypt(
        unicodedata.normalize("NFC", str(password)).encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt:{_b64url(salt)}:{_b64url(digest)}"


def map_animator_users_file(directory_users, salt_key):
    """Render the render server's users.txt.

    Bots are left out, and so are accounts with a host login, whose password is
    the become password of the server and must not reach a third-party login
    form.

    Args:
        directory_users: ``lookup('users_non_reserved', pinned_only=true)``,
            key -> user dict.
        salt_key: the role's secret HMAC key (secrets.credentials.users_salt_key).

    Returns:
        One ``<name>:scrypt:<salt>:<hash>`` line per user, sorted by name.
    """
    lines = []
    for user in directory_users.values():
        if "bot" in (user.get("roles") or []) or "host" in (user.get("accounts") or []):
            continue
        username = user["username"]
        lines.append(
            f"{username}:{map_animator_password_hash(user['password'], salt_key, username)}"
        )
    return "".join(f"{line}\n" for line in sorted(lines))


class FilterModule:
    def filters(self):
        return {"map_animator_users_file": map_animator_users_file}
