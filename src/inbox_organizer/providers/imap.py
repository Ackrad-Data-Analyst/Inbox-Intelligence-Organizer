from __future__ import annotations

import imaplib
import re
from email.header import decode_header, make_header
from email.utils import getaddresses

from ..mime import message_text, parse_rfc822
from ..models import Action, MailMessage, PlannedOperation
from .base import MailProvider


def _decode(value: str | None) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


class ImapProvider(MailProvider):
    name = "imap"

    def __init__(self, host: str, username: str, app_password: str, port: int = 993):
        self.host, self.username, self.app_password, self.port = host, username, app_password, port
        self.client: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        self.client = imaplib.IMAP4_SSL(self.host, self.port)
        self.client.login(self.username, self.app_password)

    def _imap(self) -> imaplib.IMAP4_SSL:
        if self.client is None:
            raise RuntimeError("Connect IMAP first")
        return self.client

    def list_folders(self) -> list[str]:
        status, rows = self._imap().list()
        if status != "OK":
            raise RuntimeError("Could not list IMAP folders")
        folders = []
        for row in rows:
            text = row.decode(errors="replace")
            match = re.match(r'^\([^)]*\)\s+(?:"[^"]*"|NIL)\s+(.+)$', text)
            folders.append((match.group(1) if match else text.rsplit(" ", 1)[-1]).strip('"'))
        return folders

    def fetch_messages(self, folder: str = "INBOX", limit: int = 250) -> list[MailMessage]:
        client = self._imap()
        status, _ = client.select(f'"{folder}"', readonly=True)
        if status != "OK":
            raise ValueError(f"Could not open folder: {folder}")
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        uids = data[0].split()[-limit:]
        output: list[MailMessage] = []
        for uid in reversed(uids):
            status, fetched = client.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            raw = fetched[0][1]
            parsed = parse_rfc822(raw)
            recipients = [address for _, address in getaddresses(parsed.get_all("to", []))]
            output.append(MailMessage(
                provider_id=f"{folder}|{uid.decode()}", subject=_decode(parsed.get("subject")),
                sender=_decode(parsed.get("from")), recipients=recipients,
                date=_decode(parsed.get("date")), body_text=message_text(parsed),
                folder=folder, size_bytes=len(raw),
            ))
        return output

    def _split(self, provider_id: str) -> tuple[str, str]:
        folder, uid = provider_id.rsplit("|", 1)
        return folder, uid

    def _trash_folder(self) -> str:
        folders = self.list_folders()
        for candidate in ("Trash", "Deleted Items", "Deleted", "Bin", "[Gmail]/Trash"):
            match = next((name for name in folders if name.casefold() == candidate.casefold()), None)
            if match:
                return match
        raise ValueError("Trash folder was not found; choose a destination instead")

    def apply(self, operation: PlannedOperation) -> None:
        if operation.action == Action.KEEP:
            return
        folder, uid = self._split(operation.provider_id)
        client = self._imap()
        if client.select(f'"{folder}"', readonly=False)[0] != "OK":
            raise ValueError(f"Could not open source folder: {folder}")
        destination = self._trash_folder() if operation.action == Action.TRASH else operation.destination
        if operation.action in {Action.COPY, Action.CATEGORY}:
            if client.uid("COPY", uid, f'"{destination}"')[0] != "OK":
                raise RuntimeError("IMAP copy failed")
            return
        capabilities = {item.decode().upper() if isinstance(item, bytes) else str(item).upper() for item in client.capabilities}
        if "MOVE" in capabilities:
            status, _ = client.uid("MOVE", uid, f'"{destination}"')
            if status != "OK":
                raise RuntimeError("IMAP move failed")
        else:
            if client.uid("COPY", uid, f'"{destination}"')[0] != "OK":
                raise RuntimeError("IMAP copy-before-move failed")
            client.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")
            # Do not EXPUNGE: that could permanently remove unrelated messages already marked
            # deleted by another client. The recoverable copy is in the destination folder.

    def close(self) -> None:
        if self.client:
            try:
                self.client.logout()
            finally:
                self.client = None
