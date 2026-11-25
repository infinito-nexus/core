from __future__ import annotations

import hashlib
import hmac
import itertools
import secrets
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

CODE_SECONDS = 600
ACCESS_SECONDS = 5_184_000
REFRESH_SECONDS = 31_536_000
HASH_ROUNDS = 100_000
FIRST_POST = 7_300_000_000_000_000_001


class StoreError(ValueError):
    pass


@dataclass(frozen=True)
class Account:
    member: str
    name: str
    email: str
    salt: str
    password_hash: str

    @property
    def urn(self) -> str:
        return f"urn:li:person:{self.member}"


@dataclass(frozen=True)
class Grant:
    member: str
    client_id: str
    redirect_uri: str
    scope: str
    expires_at: float


@dataclass(frozen=True)
class Token:
    member: str
    scope: str
    expires_at: float


@dataclass(frozen=True)
class Image:
    urn: str
    owner: str
    upload_id: str
    size: int


@dataclass(frozen=True)
class Post:
    id: str
    author: str
    commentary: str
    visibility: str
    content: dict
    created_at: float


def _digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), HASH_ROUNDS
    ).hex()


class Store:
    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self.now = now
        self._lock = threading.Lock()
        self._accounts: dict[str, Account] = {}
        self._codes: dict[str, Grant] = {}
        self._access: dict[str, Token] = {}
        self._refresh: dict[str, Token] = {}
        self._images: dict[str, Image] = {}
        self._uploads: dict[str, bytes] = {}
        self._posts: dict[str, Post] = {}
        self._post_ids = itertools.count(FIRST_POST)

    def create_account(self, name: str, email: str, password: str) -> Account:
        name, email = name.strip(), email.strip().lower()
        if not name or not email or not password:
            raise StoreError("name, email and password are required")
        with self._lock:
            if email in self._accounts:
                raise StoreError("an account with this email already exists")
            salt = secrets.token_hex(16)
            account = Account(
                member=secrets.token_hex(6),
                name=name,
                email=email,
                salt=salt,
                password_hash=_digest(password, salt),
            )
            self._accounts[email] = account
            return account

    def authenticate(self, email: str, password: str) -> Account | None:
        account = self._accounts.get(email.strip().lower())
        if account is None:
            return None
        if not hmac.compare_digest(
            account.password_hash, _digest(password, account.salt)
        ):
            return None
        return account

    def account(self, member: str) -> Account | None:
        return next(
            (item for item in self._accounts.values() if item.member == member), None
        )

    def accounts(self) -> list[Account]:
        return list(self._accounts.values())

    def issue_code(
        self, member: str, client_id: str, redirect_uri: str, scope: str
    ) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes[code] = Grant(
                member, client_id, redirect_uri, scope, self.now() + CODE_SECONDS
            )
        return code

    def redeem_code(self, code: str, client_id: str, redirect_uri: str) -> Grant:
        with self._lock:
            grant = self._codes.pop(code, None)
        if grant is None or grant.expires_at < self.now():
            raise StoreError("the authorization code is invalid or expired")
        if grant.client_id != client_id or grant.redirect_uri != redirect_uri:
            raise StoreError("the authorization code belongs to another client")
        return grant

    def issue_tokens(self, member: str, scope: str) -> dict:
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        now = self.now()
        with self._lock:
            self._access[access] = Token(member, scope, now + ACCESS_SECONDS)
            self._refresh[refresh] = Token(member, scope, now + REFRESH_SECONDS)
        return {
            "access_token": access,
            "expires_in": ACCESS_SECONDS,
            "refresh_token": refresh,
            "refresh_token_expires_in": REFRESH_SECONDS,
            "scope": scope,
        }

    def refresh(self, refresh_token: str) -> dict:
        token = self._refresh.get(refresh_token)
        now = self.now()
        if token is None or token.expires_at < now:
            raise StoreError("the refresh token is invalid or expired")
        access = secrets.token_urlsafe(48)
        with self._lock:
            self._access[access] = Token(
                token.member, token.scope, now + ACCESS_SECONDS
            )
        return {
            "access_token": access,
            "expires_in": ACCESS_SECONDS,
            "refresh_token": refresh_token,
            "refresh_token_expires_in": int(token.expires_at - now),
            "scope": token.scope,
        }

    def member_for(self, access_token: str) -> Account | None:
        token = self._access.get(access_token)
        if token is None or token.expires_at < self.now():
            return None
        return self.account(token.member)

    def register_image(self, owner: str) -> Image:
        image = Image(
            urn=f"urn:li:image:{secrets.token_hex(8)}",
            owner=owner,
            upload_id=secrets.token_hex(12),
            size=0,
        )
        with self._lock:
            self._images[image.upload_id] = image
        return image

    def store_upload(self, upload_id: str, owner: str, data: bytes) -> Image:
        with self._lock:
            image = self._images.get(upload_id)
            if image is None or image.owner != owner:
                raise StoreError("the upload belongs to no image of this member")
            stored = Image(image.urn, image.owner, image.upload_id, len(data))
            self._images[upload_id] = stored
            self._uploads[image.urn] = data
        return stored

    def uploaded(self, urn: str, owner: str) -> bool:
        return urn in self._uploads and any(
            image.urn == urn and image.owner == owner for image in self._images.values()
        )

    def create_post(
        self, author: str, commentary: str, visibility: str, content: dict
    ) -> Post:
        with self._lock:
            post = Post(
                id=f"urn:li:share:{next(self._post_ids)}",
                author=author,
                commentary=commentary,
                visibility=visibility,
                content=content,
                created_at=self.now(),
            )
            self._posts[post.id] = post
        return post

    def post(self, post_id: str) -> Post | None:
        return self._posts.get(post_id)

    def posts(self) -> list[Post]:
        return list(self._posts.values())
