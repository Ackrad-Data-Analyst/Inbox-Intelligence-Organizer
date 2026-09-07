from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import MailMessage, PlannedOperation


class MailProvider(ABC):
    name = "mail"

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def list_folders(self) -> list[str]: ...

    @abstractmethod
    def fetch_messages(self, folder: str, limit: int = 250) -> list[MailMessage]: ...

    @abstractmethod
    def apply(self, operation: PlannedOperation) -> None: ...

    def close(self) -> None:
        return None

