from __future__ import annotations

import datetime as dt
import html
import os
import re
import secrets
import smtplib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from export_task import (
    KEYCLOAK_ENV,
    LOGIN_ENV,
    MAIL_ENV,
    OWNERS_PATH,
    PLATFORM_MOUNT,
    S3_ENV,
    UUID,
    ExportRefusedError,
    ExportTask,
    bao_client,
    membership_path,
    now_ms,
    presign,
    recent_join,
    task_opener,
)

from utils.openbao_client import OpenBaoError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from export_task import Opener

    from utils.openbao_client import OpenBaoClient

RECIPIENT = re.compile(r"age1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{58}")
RECIPIENT_ATTRIBUTE = "export_recipient"
LINK_SECONDS = 900
REQUIRED_ENV = (
    "WORKSPACE",
    "EXPORT_FOR",
    "SEMAPHORE_TASK_ID",
    *LOGIN_ENV,
    *KEYCLOAK_ENV,
    *S3_ENV,
    *MAIL_ENV,
    "EXPORT_OWNER_MIN_AGE_DAYS",
)


def recipient_of(user: Mapping[str, Any]) -> str:
    """
    Args:
        user: the Keycloak user representation of ``EXPORT_FOR``.

    Returns:
        The one age recipient the user registered in ``export_recipient``.
    """
    values = (user.get("attributes") or {}).get(RECIPIENT_ATTRIBUTE) or []
    if len(values) != 1 or not RECIPIENT.fullmatch(str(values[0])):
        raise ExportRefusedError("the owner holds no age recipient")
    return str(values[0])


def age_refusal(
    events: list[Mapping[str, Any]], path: str, now: int, min_age_days: int
) -> str | None:
    """
    Args:
        events: see ``recent_join``.
        path: see ``membership_path``.
        now: the current time in epoch milliseconds.
        min_age_days: ``owner_min_age_days``.

    Returns:
        The refusal reason while the newest membership event is a ``CREATE``
        younger than the minimum age, else None.
    """
    if recent_join(events, path, now, min_age_days) is None:
        return None
    return f"the owner joined less than {min_age_days} days ago"


def keepass_xml(entries: Mapping[str, Mapping[str, Any]]) -> bytes:
    """
    Args:
        entries: per secret path below the workspace, its fields.

    Returns:
        A KeePass XML export with one entry per field.
    """
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<KeePassFile><Root><Group><Name>Workspace</Name>",
    ]
    for path in sorted(entries):
        for field, value in sorted(entries[path].items()):
            title = html.escape(f"{path}#{field}")
            secret = html.escape(str(value))
            lines.append(
                f"<Entry><String><Key>Title</Key><Value>{title}</Value></String>"
                f"<String><Key>Password</Key><Value>{secret}</Value></String></Entry>"
            )
    lines.append("</Group></Root></KeePassFile>")
    return "\n".join(lines).encode()


def build_archive(
    entries: Mapping[str, Mapping[str, Any]], recipient: str, workdir: Path
) -> Path:
    """
    Args:
        entries: see ``keepass_xml``.
        recipient: the owner's age recipient.
        workdir: the task directory, a tmpfs.

    Returns:
        The tar holding exactly ``secrets.kdbx`` and ``passphrase.age``.
    """
    passphrase = secrets.token_bytes(32).hex()
    xml = workdir / "secrets.xml"
    kdbx = workdir / "secrets.kdbx"
    sealed = workdir / "passphrase.age"
    descriptor = os.open(xml, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(keepass_xml(entries))
        subprocess.run(
            ["keepassxc-cli", "import", "--set-password", str(xml), str(kdbx)],
            input=f"{passphrase}\n{passphrase}\n",
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        xml.unlink(missing_ok=True)
    subprocess.run(
        ["age", "-r", recipient, "-o", str(sealed)],
        input=passphrase,
        text=True,
        capture_output=True,
        check=True,
    )
    archive = workdir / "export.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(kdbx, arcname=kdbx.name)
        tar.add(sealed, arcname=sealed.name)
    kdbx.unlink()
    sealed.unlink()
    return archive


class Export(ExportTask):
    def __init__(
        self, environ: Mapping[str, str], opener: Opener, bao: OpenBaoClient
    ) -> None:
        """
        Args:
            environ: the task environment; see ``REQUIRED_ENV``.
            opener: see ``ExportTask``.
            bao: see ``ExportTask``.
        """
        super().__init__(environ, REQUIRED_ENV, opener, bao)
        if not UUID.fullmatch(environ["WORKSPACE"]):
            raise ExportRefusedError("WORKSPACE is no lowercase UUID")
        if not UUID.fullmatch(environ["EXPORT_FOR"]):
            raise ExportRefusedError("EXPORT_FOR is no Keycloak user id")
        self.workspace = environ["WORKSPACE"]
        self.user_id = environ["EXPORT_FOR"]

    def pinned_group(self) -> str:
        """
        Returns:
            The pinned ``Owner`` group id of the workspace, after the task
            token login and the Keycloak login.
        """
        self.login(f"ws-{self.workspace}")
        owners = self.bao.read_all(PLATFORM_MOUNT, f"{OWNERS_PATH}ws-{self.workspace}")
        self.keycloak_login()
        return str(owners["group"])

    def check(
        self, organization: str, group: str, now: int
    ) -> tuple[str, list[Mapping[str, Any]]]:
        """
        Args:
            organization: the Keycloak id of the marked organization.
            group: the pinned ``Owner`` group id.
            now: the current time in epoch milliseconds.

        Returns:
            The owner's recipient, read from Keycloak alone, and the direct
            members of the pinned group; raises ``ExportRefusedError`` otherwise.
        """
        members = self.members(organization, group)
        if self.user_id not in {member.get("id") for member in members}:
            raise ExportRefusedError(
                "EXPORT_FOR is no direct member of the pinned Owner group"
            )
        recipient = recipient_of(self.user(self.user_id))
        path = membership_path(organization, group, self.user_id)
        reason = age_refusal(
            self.membership_events(path),
            path,
            now,
            int(self.env["EXPORT_OWNER_MIN_AGE_DAYS"]),
        )
        if reason:
            raise ExportRefusedError(reason)
        return recipient, members

    def announce(self, members: list[Mapping[str, Any]], what: str) -> None:
        stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        self.mail(
            members,
            f"Secret export of workspace ws-{self.workspace}",
            f"Workspace: ws-{self.workspace}\nOwner: {self.user_id}\nTime: {stamp}\n{what}\n",
        )

    def entries(self) -> dict[str, dict[str, Any]]:
        prefix = f"ws-{self.workspace}/"
        return {
            path: self.bao.read_all("tenant", prefix + path)
            for path in self.bao.list_tree("tenant", prefix)
        }

    def deliver(self, archive: Path) -> str:
        s3 = self.s3_credentials()
        url = f"{self.bucket_url()}/ws-{self.workspace}/{self.env['SEMAPHORE_TASK_ID']}.tar"
        now = dt.datetime.now(dt.UTC)
        region = self.env["EXPORT_S3_REGION"]
        self._call(
            "PUT",
            presign("PUT", url, s3, region, now, LINK_SECONDS, {}),
            archive.read_bytes(),
            {"x-amz-content-sha256": "UNSIGNED-PAYLOAD"},
        )
        return presign("GET", url, s3, region, now, LINK_SECONDS, {})


def run(environ: Mapping[str, str], opener: Opener, workdir: Path) -> str:
    """
    Args:
        environ: see ``Export``.
        opener: see ``Export``.
        workdir: the task directory.

    Returns:
        The presigned link, printed as the last output line.
    """
    export = Export(environ, opener, bao_client(environ))
    group = export.pinned_group()
    organization = export.organization(export.workspace)
    try:
        recipient, members = export.check(organization, group, now_ms())
    except ExportRefusedError as exc:
        export.announce(export.members(organization, group), f"Refused: {exc}")
        raise
    export.announce(members, "An export of the workspace secrets starts now.")
    archive = build_archive(export.entries(), recipient, workdir)
    try:
        return export.deliver(archive)
    finally:
        archive.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if argv:
        print(f"export: takes no argument, got {argv[0]!r}", file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory() as workdir:
            link = run(os.environ, task_opener(os.environ), Path(workdir))
    except (ExportRefusedError, OpenBaoError) as exc:
        print(f"export refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError, smtplib.SMTPException) as exc:
        print(f"export failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(link)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
