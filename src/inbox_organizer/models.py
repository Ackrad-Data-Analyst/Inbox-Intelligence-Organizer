from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Category(StrEnum):
    JOB_REJECTION = "job_rejection"
    PROMOTION_AD = "promotion_ad"
    NEWSLETTER = "newsletter"
    RECRUITER_ACTION = "recruiter_response_or_action"
    JOB_OFFER = "job_offer_or_interview"
    RECEIPT_FINANCIAL = "receipt_or_financial"
    SECURITY_ACCOUNT = "security_or_account"
    PERSONAL = "personal"
    OTHER = "other"


class Action(StrEnum):
    KEEP = "keep"
    CATEGORY = "category"
    MOVE = "move"
    COPY = "copy"
    TRASH = "trash"


@dataclass(slots=True)
class MailMessage:
    provider_id: str
    subject: str
    sender: str
    recipients: list[str]
    date: str
    body_text: str
    folder: str = ""
    labels: list[str] = field(default_factory=list)
    thread_id: str | None = None
    size_bytes: int = 0

    def classifier_text(self, max_chars: int = 60000) -> str:
        body = self.body_text.strip()
        if len(body) > max_chars:
            half = max_chars // 2
            body = body[:half] + "\n[...middle truncated...]\n" + body[-half:]
        return (
            f"From: {self.sender}\nTo: {', '.join(self.recipients)}\nDate: {self.date}\n"
            f"Subject: {self.subject}\n\nFull message body:\n{body}"
        )


@dataclass(slots=True)
class Classification:
    category: Category
    confidence: float
    rationale: str
    protected: bool
    evidence: list[str] = field(default_factory=list)
    model: str = ""

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.rationale = self.rationale[:600]
        self.evidence = [str(item)[:200] for item in self.evidence[:5]]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


@dataclass(slots=True)
class PlannedOperation:
    provider_id: str
    subject: str
    category: Category
    confidence: float
    action: Action
    destination: str | None = None
    protected: bool = False

