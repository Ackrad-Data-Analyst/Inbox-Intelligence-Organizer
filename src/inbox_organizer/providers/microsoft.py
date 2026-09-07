from __future__ import annotations

import html
import re

from ..mime import html_to_text
from ..models import Action, MailMessage, PlannedOperation
from .base import MailProvider


GRAPH = "https://graph.microsoft.com/v1.0"


class MicrosoftProvider(MailProvider):
    name = "microsoft"

    def __init__(self, client_id: str, tenant: str = "common"):
        self.client_id, self.tenant = client_id, tenant
        self.access_token = ""

    def connect(self) -> None:
        import msal
        app = msal.PublicClientApplication(
            self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}"
        )
        accounts = app.get_accounts()
        result = app.acquire_token_silent(["Mail.ReadWrite"], account=accounts[0]) if accounts else None
        if not result:
            result = app.acquire_token_interactive(scopes=["Mail.ReadWrite"], prompt="select_account")
        if "access_token" not in result:
            raise RuntimeError(result.get("error_description", "Microsoft sign-in failed"))
        self.access_token = result["access_token"]

    def _request(self, method: str, url: str, body: dict | None = None) -> dict:
        import requests
        if not self.access_token:
            raise RuntimeError("Connect Microsoft first")
        response = requests.request(method, url, json=body, timeout=60, headers={
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        })
        response.raise_for_status()
        return response.json() if response.content else {}

    def list_folders(self) -> list[str]:
        payload = self._request("GET", f"{GRAPH}/me/mailFolders?$top=100&$select=id,displayName")
        return [f"{item['displayName']}|{item['id']}" for item in payload.get("value", [])]

    def fetch_messages(self, folder: str = "inbox", limit: int = 250) -> list[MailMessage]:
        folder_id = folder.rsplit("|", 1)[-1]
        select = "id,conversationId,subject,from,toRecipients,receivedDateTime,body,categories,parentFolderId"
        url = f"{GRAPH}/me/mailFolders/{folder_id}/messages?$top={min(100, limit)}&$select={select}"
        output: list[MailMessage] = []
        while url and len(output) < limit:
            page = self._request("GET", url)
            for raw in page.get("value", []):
                sender = raw.get("from", {}).get("emailAddress", {})
                body = raw.get("body", {})
                content = body.get("content", "")
                if body.get("contentType", "").lower() == "html":
                    content = html_to_text(content)
                output.append(MailMessage(
                    provider_id=raw["id"], thread_id=raw.get("conversationId"),
                    subject=raw.get("subject") or "(no subject)",
                    sender=f"{sender.get('name', '')} <{sender.get('address', '')}>",
                    recipients=[item.get("emailAddress", {}).get("address", "") for item in raw.get("toRecipients", [])],
                    date=raw.get("receivedDateTime", ""), body_text=content,
                    folder=raw.get("parentFolderId", ""), labels=raw.get("categories", []),
                ))
                if len(output) >= limit:
                    break
            url = page.get("@odata.nextLink", "")
        return output

    def _folder_id(self, destination: str) -> str:
        return destination.rsplit("|", 1)[-1]

    def apply(self, operation: PlannedOperation) -> None:
        if operation.action == Action.KEEP:
            return
        endpoint = f"{GRAPH}/me/messages/{operation.provider_id}"
        if operation.action == Action.TRASH:
            self._request("POST", endpoint + "/move", {"destinationId": "deleteditems"})
        elif operation.action == Action.MOVE:
            self._request("POST", endpoint + "/move", {"destinationId": self._folder_id(operation.destination or "")})
        elif operation.action == Action.COPY:
            self._request("POST", endpoint + "/copy", {"destinationId": self._folder_id(operation.destination or "")})
        elif operation.action == Action.CATEGORY:
            self._request("PATCH", endpoint, {"categories": [operation.destination]})

