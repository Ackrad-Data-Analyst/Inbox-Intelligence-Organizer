from __future__ import annotations

from collections.abc import Callable, Iterable

from .audit import append_audit
from .classifier import SemanticClassifier, conservative_fallback
from .models import Classification, MailMessage, PlannedOperation
from .providers.base import MailProvider


def classify_messages(messages: Iterable[MailMessage], classifier: SemanticClassifier,
                      progress: Callable[[int, int], None] | None = None) -> list[tuple[MailMessage, Classification]]:
    items = list(messages)
    results = []
    for index, message in enumerate(items, 1):
        try:
            classification = classifier.classify(message)
        except Exception:
            classification = conservative_fallback(message)
        results.append((message, classification))
        if progress:
            progress(index, len(items))
    return results


def apply_operations(provider: MailProvider, operations: list[PlannedOperation], audit_path: str) -> list[dict]:
    results = []
    for operation in operations:
        try:
            provider.apply(operation)
            status = "applied"
        except Exception as exc:
            status = f"failed: {type(exc).__name__}: {exc}"
        append_audit(audit_path, provider.name, operation, status)
        results.append({"message_id": operation.provider_id, "status": status})
    return results

