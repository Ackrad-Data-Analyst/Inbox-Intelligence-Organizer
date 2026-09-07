from __future__ import annotations

from .models import Action, Category, Classification, MailMessage, PlannedOperation


AUTO_TRASH_CATEGORIES = {Category.JOB_REJECTION, Category.PROMOTION_AD}


def recommended_action(classification: Classification) -> Action:
    if (
        classification.category in AUTO_TRASH_CATEGORIES
        and classification.confidence >= 0.95
        and not classification.protected
    ):
        return Action.TRASH
    if classification.category == Category.NEWSLETTER and classification.confidence >= 0.95:
        return Action.CATEGORY
    return Action.KEEP


def plan_operation(message: MailMessage, classification: Classification, action: Action,
                   destination: str | None = None, override_protected: bool = False) -> PlannedOperation:
    if action == Action.TRASH and classification.protected and not override_protected:
        raise ValueError("Protected messages cannot be trashed without an explicit per-message override")
    if action in {Action.MOVE, Action.COPY, Action.CATEGORY} and not destination:
        raise ValueError(f"A destination is required for {action.value}")
    return PlannedOperation(
        message.provider_id, message.subject, classification.category,
        classification.confidence, action, destination, classification.protected,
    )


def validate_confirmation(operations: list[PlannedOperation], typed: str) -> None:
    if not operations:
        raise ValueError("No operations are selected")
    if any(item.action == Action.TRASH for item in operations) and typed != "MOVE TO TRASH":
        raise ValueError("Type MOVE TO TRASH exactly to confirm recoverable trash operations")
    if any(item.action != Action.KEEP for item in operations) and typed not in {"APPLY", "MOVE TO TRASH"}:
        raise ValueError("Type APPLY exactly to confirm mailbox changes")

