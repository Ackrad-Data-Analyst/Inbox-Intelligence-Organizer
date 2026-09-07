from __future__ import annotations

from pathlib import Path

from ..mime import gmail_body
from ..models import Action, MailMessage, PlannedOperation
from .base import MailProvider


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailProvider(MailProvider):
    name = "gmail"

    def __init__(self, credentials_path: str | Path, token_path: str | Path):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.service = None

    def connect(self) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        credentials = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
            credentials = flow.run_local_server(port=0, open_browser=True)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def _api(self):
        if self.service is None:
            raise RuntimeError("Connect Gmail first")
        return self.service.users()

    def list_folders(self) -> list[str]:
        labels = self._api().labels().list(userId="me").execute().get("labels", [])
        return [item["id"] for item in labels]

    def fetch_messages(self, folder: str = "INBOX", limit: int = 250) -> list[MailMessage]:
        messages: list[MailMessage] = []
        token = None
        query = "-in:spam -in:trash" if folder == "ALL" else None
        while len(messages) < limit:
            page = self._api().messages().list(
                userId="me", labelIds=None if folder == "ALL" else [folder], q=query,
                maxResults=min(500, limit - len(messages)), pageToken=token,
            ).execute()
            for item in page.get("messages", []):
                raw = self._api().messages().get(userId="me", id=item["id"], format="full").execute()
                headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
                messages.append(MailMessage(
                    provider_id=raw["id"], thread_id=raw.get("threadId"),
                    subject=headers.get("subject", "(no subject)"), sender=headers.get("from", ""),
                    recipients=[headers.get("to", "")], date=headers.get("date", ""),
                    body_text=gmail_body(raw.get("payload", {})), folder=folder,
                    labels=raw.get("labelIds", []), size_bytes=int(raw.get("sizeEstimate", 0)),
                ))
                if len(messages) >= limit:
                    break
            token = page.get("nextPageToken")
            if not token:
                break
        return messages

    def _label_id(self, name: str) -> str:
        labels = self._api().labels().list(userId="me").execute().get("labels", [])
        existing = next((item for item in labels if item["name"].casefold() == name.casefold()), None)
        if existing:
            return existing["id"]
        created = self._api().labels().create(userId="me", body={
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"
        }).execute()
        return created["id"]

    def apply(self, operation: PlannedOperation) -> None:
        messages = self._api().messages()
        if operation.action == Action.KEEP:
            return
        if operation.action == Action.TRASH:
            messages.trash(userId="me", id=operation.provider_id).execute()
            return
        label = self._label_id(operation.destination or operation.category.value)
        body = {"addLabelIds": [label], "removeLabelIds": ["INBOX"] if operation.action == Action.MOVE else []}
        messages.modify(userId="me", id=operation.provider_id, body=body).execute()

